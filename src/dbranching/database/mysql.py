"""MySQL database adapter implementation."""

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiomysql
import pymysql
from pydantic import ValidationError as PydanticValidationError

from ..config import DatabaseConfig
from ..exceptions import (
    DatabaseAdapterError,
    DatabaseConnectionError,
    DatabaseTimeoutError,
    SnapshotError,
    StorageError,
    ValidationError,
)
from .adapter import DatabaseAdapter
from .models import (
    CompressionType,
    DatabaseInfo,
    ProgressCallback,
    RestoreOptions,
    RestoreResult,
    SnapshotFormat,
    SnapshotOptions,
    SnapshotResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class MySQLAdapter(DatabaseAdapter):
    """MySQL database adapter using mysqldump/mysql."""

    def __init__(self, config: DatabaseConfig) -> None:
        """
        Initialize MySQL adapter.

        Args:
            config: Database configuration
        """
        if config.driver != "mysql":
            raise DatabaseAdapterError(
                f"Invalid driver for MySQL adapter: {config.driver}", "mysql"
            )

        self.config = config
        # Set default MySQL port if using PostgreSQL default
        if self.config.port == 5432:
            self.config.port = 3306
            
        self._pool: Optional[aiomysql.Pool] = None
        self._connection_lock = asyncio.Lock()
        self._connection_retries = 3
        self._connection_timeout = self._parse_timeout(config.connect_timeout)
        self._query_timeout = self._parse_timeout(config.query_timeout)

    @staticmethod
    def _parse_timeout(timeout_str: str) -> float:
        """Parse timeout string to seconds."""
        if timeout_str.endswith("s"):
            return float(timeout_str[:-1])
        elif timeout_str.endswith("m"):
            return float(timeout_str[:-1]) * 60
        elif timeout_str.endswith("h"):
            return float(timeout_str[:-1]) * 3600
        else:
            return float(timeout_str)

    def _get_connection_kwargs(self) -> Dict[str, Any]:
        """Build MySQL connection parameters."""
        kwargs = {
            "host": self.config.host,
            "port": self.config.port,
            "db": self.config.database,
            "autocommit": False,
        }

        if self.config.username:
            kwargs["user"] = self.config.username

        if self.config.password:
            kwargs["password"] = self.config.password

        # MySQL SSL configuration
        if self.config.ssl_mode != "disable":
            kwargs["ssl"] = {}
            if self.config.ssl_mode in ["require", "verify-ca", "verify-full"]:
                kwargs["ssl"]["disabled"] = False
            else:
                kwargs["ssl"]["disabled"] = True

        return kwargs

    def _get_mysqldump_env(self) -> Dict[str, str]:
        """Get environment variables for mysqldump/mysql."""
        env = os.environ.copy()

        if self.config.password:
            env["MYSQL_PWD"] = self.config.password

        return env

    async def connect(self) -> bool:
        """Establish and validate database connection pool."""
        async with self._connection_lock:
            if self._pool and not self._pool.closed:
                return True

            kwargs = self._get_connection_kwargs()

            for attempt in range(self._connection_retries):
                try:
                    self._pool = await asyncio.wait_for(
                        aiomysql.create_pool(
                            minsize=1,
                            maxsize=self.config.pool_size,
                            **kwargs
                        ),
                        timeout=self._connection_timeout,
                    )

                    # Test connection with simple query
                    async with self._pool.acquire() as conn:
                        async with conn.cursor() as cursor:
                            await asyncio.wait_for(
                                cursor.execute("SELECT 1"),
                                timeout=self._query_timeout,
                            )

                    logger.info(
                        f"Connected to MySQL database: {self.config.host}:{self.config.port}/{self.config.database}"
                    )
                    return True

                except asyncio.TimeoutError:
                    error_msg = f"Connection timeout after {self._connection_timeout}s"
                    logger.warning(
                        f"Connection attempt {attempt + 1} failed: {error_msg}"
                    )
                    if attempt == self._connection_retries - 1:
                        raise DatabaseTimeoutError(error_msg, self._connection_timeout)
                    await asyncio.sleep(2**attempt)  # Exponential backoff

                except Exception as e:
                    error_msg = f"Connection failed: {str(e)}"
                    logger.warning(
                        f"Connection attempt {attempt + 1} failed: {error_msg}"
                    )
                    if attempt == self._connection_retries - 1:
                        raise DatabaseConnectionError(
                            error_msg, f"{self.config.host}:{self.config.port}/{self.config.database}"
                        )
                    await asyncio.sleep(2**attempt)

            return False

    async def disconnect(self) -> None:
        """Close database connection pool and cleanup resources."""
        async with self._connection_lock:
            if self._pool and not self._pool.closed:
                try:
                    self._pool.close()
                    await self._pool.wait_closed()
                    logger.info("Disconnected from MySQL database")
                except Exception as e:
                    logger.warning(f"Error during disconnect: {e}")
                finally:
                    self._pool = None

    async def test_connection(self) -> bool:
        """Test database connection without establishing permanent connection."""
        try:
            kwargs = self._get_connection_kwargs()
            
            conn = await asyncio.wait_for(
                aiomysql.connect(**kwargs), timeout=self._connection_timeout
            )

            async with conn.cursor() as cursor:
                await asyncio.wait_for(
                    cursor.execute("SELECT 1"), timeout=self._query_timeout
                )

            conn.close()
            return True

        except Exception as e:
            logger.debug(f"Connection test failed: {e}")
            return False

    async def create_snapshot(
        self,
        output_path: Path,
        options: Optional[SnapshotOptions] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> SnapshotResult:
        """Create database snapshot using mysqldump."""
        if options is None:
            options = SnapshotOptions()

        start_time = time.time()
        output_path = output_path.resolve()

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build mysqldump command
        cmd = await self._build_mysqldump_command(output_path, options)
        env = self._get_mysqldump_env()

        logger.info(f"Creating MySQL snapshot: {output_path}")
        logger.debug(f"mysqldump command: {' '.join(cmd)}")

        try:
            # Get database info before snapshot
            db_info = await self.get_database_info()

            if progress_callback:
                await progress_callback.update(
                    0, 100, "Starting snapshot creation", "dump"
                )

            # Execute mysqldump
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Monitor progress if callback provided
            if progress_callback:
                asyncio.create_task(
                    self._monitor_dump_progress(process, progress_callback)
                )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = f"mysqldump failed (exit code {process.returncode}): {stderr.decode()}"
                logger.error(error_msg)
                raise SnapshotError(error_msg)

            # Calculate file sizes and metadata
            if not output_path.exists():
                raise SnapshotError(f"Snapshot file was not created: {output_path}")

            file_size = output_path.stat().st_size
            duration = time.time() - start_time

            # Calculate compression ratio if compressed
            compression_ratio = None
            compressed_size = None
            if options.compression != CompressionType.NONE:
                compressed_size = file_size
                compression_ratio = (
                    db_info.size_bytes / file_size if file_size > 0 else 0
                )

            warnings = []
            if stderr:
                # Parse stderr for warnings (not errors since returncode == 0)
                warning_lines = [
                    line for line in stderr.decode().split("\n") if line.strip()
                ]
                warnings.extend(warning_lines)

            result = SnapshotResult(
                success=True,
                snapshot_path=output_path,
                size_bytes=file_size,
                compressed_size_bytes=compressed_size,
                duration_seconds=duration,
                database_size_bytes=db_info.size_bytes,
                tables_included=db_info.table_count,
                schemas_included=db_info.schema_count,
                compression_ratio=compression_ratio,
                warnings=warnings,
                metadata={
                    "mysqldump_version": await self._get_mysqldump_version(),
                    "database_version": db_info.version,
                    "options": options.dict(),
                },
            )

            logger.info(f"Snapshot created successfully: {result}")
            return result

        except Exception as e:
            # Clean up partial snapshot on error
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to clean up partial snapshot: {cleanup_error}"
                    )

            if isinstance(e, SnapshotError):
                raise
            else:
                raise SnapshotError(f"Snapshot creation failed: {str(e)}")

    async def restore_snapshot(
        self,
        snapshot_path: Path,
        options: Optional[RestoreOptions] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> RestoreResult:
        """Restore database from snapshot using mysql client."""
        if options is None:
            options = RestoreOptions()

        start_time = time.time()
        snapshot_path = snapshot_path.resolve()

        if not snapshot_path.exists():
            raise SnapshotError(f"Snapshot file not found: {snapshot_path}")

        # Validate snapshot first
        validation = await self.validate_snapshot(snapshot_path)
        if not validation.valid:
            raise ValidationError(f"Invalid snapshot: {validation.error_message}")

        # Build mysql command
        cmd = await self._build_mysql_command(snapshot_path, options)
        env = self._get_mysqldump_env()

        logger.info(f"Restoring MySQL snapshot: {snapshot_path}")
        logger.debug(f"mysql command: {' '.join(cmd)}")

        try:
            if progress_callback:
                await progress_callback.update(
                    0, 100, "Starting snapshot restore", "restore"
                )

            # Execute mysql
            with open(snapshot_path, 'rb') as input_file:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdin=input_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Monitor progress if callback provided
                if progress_callback:
                    asyncio.create_task(
                        self._monitor_restore_progress(process, progress_callback)
                    )

                stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = f"mysql restore failed (exit code {process.returncode}): {stderr.decode()}"
                logger.error(error_msg)
                raise SnapshotError(error_msg)

            duration = time.time() - start_time

            # Get post-restore database info
            db_info = await self.get_database_info()

            warnings = []
            if stderr:
                # Parse stderr for warnings (not errors since returncode == 0)
                warning_lines = [
                    line for line in stderr.decode().split("\n") if line.strip()
                ]
                warnings.extend(warning_lines)

            result = RestoreResult(
                success=True,
                snapshot_path=snapshot_path,
                duration_seconds=duration,
                tables_restored=db_info.table_count,
                schemas_restored=db_info.schema_count,
                warnings=warnings,
                metadata={
                    "mysql_version": await self._get_mysql_version(),
                    "database_version": db_info.version,
                    "options": options.dict(),
                },
            )

            logger.info(f"Snapshot restored successfully: {result}")
            return result

        except Exception as e:
            if isinstance(e, SnapshotError):
                raise
            else:
                raise SnapshotError(f"Snapshot restore failed: {str(e)}")

    async def get_database_info(self) -> DatabaseInfo:
        """Get comprehensive database information."""
        if not self._pool or self._pool.closed:
            await self.connect()

        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get basic database info
                    await cursor.execute("SELECT VERSION()")
                    version_result = await cursor.fetchone()
                    version = version_result[0] if version_result else "Unknown"

                    # Parse version string
                    version_match = re.search(r"(\d+\.\d+\.\d+)", version)
                    version_str = version_match.group(1) if version_match else version

                    # Get database size
                    size_query = """
                        SELECT 
                            SUM(data_length + index_length) as size_bytes
                        FROM information_schema.tables 
                        WHERE table_schema = %s
                    """
                    await cursor.execute(size_query, (self.config.database,))
                    size_result = await cursor.fetchone()
                    size_bytes = size_result[0] if size_result and size_result[0] else 0

                    # Get table count
                    table_query = """
                        SELECT COUNT(*) 
                        FROM information_schema.tables 
                        WHERE table_schema = %s 
                        AND table_type = 'BASE TABLE'
                    """
                    await cursor.execute(table_query, (self.config.database,))
                    table_result = await cursor.fetchone()
                    table_count = table_result[0] if table_result else 0

                    # MySQL doesn't have schemas like PostgreSQL, schema_count is always 1 for a database
                    schema_count = 1

                    # Get connection count
                    conn_query = "SHOW STATUS LIKE 'Threads_connected'"
                    await cursor.execute(conn_query)
                    conn_result = await cursor.fetchone()
                    connection_count = int(conn_result[1]) if conn_result else 0

                    # Get database settings
                    await cursor.execute("SHOW VARIABLES LIKE 'character_set_database'")
                    encoding_result = await cursor.fetchone()
                    encoding = encoding_result[1] if encoding_result else "utf8"

                    await cursor.execute("SHOW VARIABLES LIKE 'collation_database'")
                    collation_result = await cursor.fetchone()
                    collation = collation_result[1] if collation_result else "utf8_general_ci"

                    await cursor.execute("SHOW VARIABLES LIKE 'time_zone'")
                    timezone_result = await cursor.fetchone()
                    timezone = timezone_result[1] if timezone_result else "SYSTEM"

                    # Get uptime
                    await cursor.execute("SHOW STATUS LIKE 'Uptime'")
                    uptime_result = await cursor.fetchone()
                    uptime_seconds = int(uptime_result[1]) if uptime_result else None

                    # Get schemas (databases in MySQL terminology)
                    schemas_query = "SHOW DATABASES"
                    await cursor.execute(schemas_query)
                    schemas_result = await cursor.fetchall()
                    schemas = [row[0] for row in schemas_result if row[0] not in ['information_schema', 'mysql', 'performance_schema', 'sys']]

                    # Get important settings
                    settings = {}
                    setting_vars = [
                        'max_connections', 'innodb_buffer_pool_size', 'query_cache_size',
                        'sort_buffer_size', 'join_buffer_size', 'binlog_format'
                    ]
                    
                    for var in setting_vars:
                        await cursor.execute(f"SHOW VARIABLES LIKE '{var}'")
                        result = await cursor.fetchone()
                        if result:
                            settings[var] = result[1]

                    return DatabaseInfo(
                        name=self.config.database,
                        version=version_str,
                        size_bytes=size_bytes,
                        table_count=table_count,
                        schema_count=schema_count,
                        connection_count=connection_count,
                        encoding=encoding,
                        collation=collation,
                        timezone=timezone,
                        uptime_seconds=uptime_seconds,
                        schemas=schemas,
                        extensions=[],  # MySQL doesn't have extensions like PostgreSQL
                        settings=settings,
                        metadata={
                            "full_version": version,
                            "host": self.config.host,
                            "port": self.config.port,
                        },
                    )

        except Exception as e:
            raise DatabaseConnectionError(f"Failed to get database info: {str(e)}")

    async def validate_snapshot(self, snapshot_path: Path) -> ValidationResult:
        """Validate MySQL snapshot by checking file format and basic structure."""
        snapshot_path = snapshot_path.resolve()

        if not snapshot_path.exists():
            return ValidationResult(
                valid=False,
                snapshot_path=snapshot_path,
                format_valid=False,
                size_bytes=0,
                compatible=False,
                error_message="Snapshot file not found",
            )

        file_size = snapshot_path.stat().st_size

        try:
            # Calculate file checksum
            checksum = await self._calculate_file_checksum(snapshot_path)

            # Basic validation: check if file looks like a MySQL dump
            with open(snapshot_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_lines = []
                for i, line in enumerate(f):
                    if i >= 10:  # Read first 10 lines
                        break
                    first_lines.append(line.strip())

            # Check for MySQL dump markers
            is_mysql_dump = any(
                "MySQL dump" in line or "mysqldump" in line 
                for line in first_lines
            )

            if not is_mysql_dump:
                return ValidationResult(
                    valid=False,
                    snapshot_path=snapshot_path,
                    format_valid=False,
                    size_bytes=file_size,
                    checksum=checksum,
                    compatible=False,
                    error_message="File does not appear to be a MySQL dump",
                )

            # Extract version and metadata
            database_version = None
            table_count = 0
            
            with open(snapshot_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f):
                    if line_num > 1000:  # Don't read entire file
                        break
                        
                    if "Server version" in line:
                        version_match = re.search(r"(\d+\.\d+\.\d+)", line)
                        if version_match:
                            database_version = version_match.group(1)
                    elif line.startswith("CREATE TABLE") or "CREATE TABLE" in line:
                        table_count += 1

            # Check compatibility with current database
            compatible = True
            warnings = []

            if database_version:
                try:
                    current_info = await self.get_database_info()
                    current_version = current_info.version

                    # Simple version compatibility check
                    if database_version != current_version:
                        warnings.append(
                            f"Version mismatch: snapshot={database_version}, current={current_version}"
                        )
                except Exception:
                    warnings.append("Could not verify version compatibility")

            # Estimate restore time based on file size (rough heuristic)
            estimated_restore_time = file_size / (5 * 1024 * 1024)  # ~5MB/second

            return ValidationResult(
                valid=True,
                snapshot_path=snapshot_path,
                format_valid=True,
                size_bytes=file_size,
                checksum=checksum,
                database_version=database_version,
                compatible=compatible,
                schema_count=1,  # MySQL dumps typically contain one database
                table_count=table_count,
                estimated_restore_time=estimated_restore_time,
                warnings=warnings,
            )

        except Exception as e:
            return ValidationResult(
                valid=False,
                snapshot_path=snapshot_path,
                format_valid=False,
                size_bytes=file_size,
                compatible=False,
                error_message=f"Validation failed: {str(e)}",
            )

    async def get_supported_formats(self) -> set[str]:
        """Get supported snapshot formats for MySQL."""
        return {
            SnapshotFormat.PLAIN.value,  # SQL text format
        }

    async def estimate_snapshot_size(
        self, options: Optional[SnapshotOptions] = None
    ) -> int:
        """Estimate snapshot size based on database size and options."""
        db_info = await self.get_database_info()
        base_size = db_info.size_bytes

        if options:
            # Schema/table filtering adjustments first
            if options.schema_only:
                base_size = int(base_size * 0.01)  # Schema is much smaller
            elif options.data_only:
                base_size = int(base_size * 0.95)  # Slightly less without schema

            # Apply compression ratio estimate (mysqldump text format compresses well)
            if options.compression == CompressionType.GZIP:
                base_size = int(base_size * 0.2)  # ~80% compression for text
            elif options.compression == CompressionType.LZ4:
                base_size = int(base_size * 0.4)  # ~60% compression
            elif options.compression == CompressionType.ZSTD:
                base_size = int(base_size * 0.15)  # ~85% compression

        return base_size

    async def list_schemas(self) -> list[str]:
        """List all databases in MySQL."""
        if not self._pool or self._pool.closed:
            await self.connect()

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SHOW DATABASES")
                results = await cursor.fetchall()
                # Filter out system databases
                schemas = [row[0] for row in results if row[0] not in ['information_schema', 'mysql', 'performance_schema', 'sys']]
                return schemas

    async def list_tables(self, schema: Optional[str] = None) -> list[str]:
        """List all tables in the database or specific schema."""
        if not self._pool or self._pool.closed:
            await self.connect()

        database = schema if schema else self.config.database

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """
                await cursor.execute(query, (database,))
                results = await cursor.fetchall()
                
                if schema:
                    return [row[0] for row in results]
                else:
                    return [f"{database}.{row[0]}" for row in results]

    # Helper methods

    async def _build_mysqldump_command(
        self, output_path: Path, options: SnapshotOptions
    ) -> List[str]:
        """Build mysqldump command with options."""
        cmd = ["mysqldump"]

        # Connection parameters
        cmd.extend(["-h", self.config.host])
        cmd.extend(["-P", str(self.config.port)])

        if self.config.username:
            cmd.extend(["-u", self.config.username])

        # MySQL specific options
        cmd.extend(["--single-transaction"])  # For consistent backups
        cmd.extend(["--routines"])  # Include stored procedures and functions
        cmd.extend(["--triggers"])  # Include triggers

        # Schema/data options
        if options.data_only:
            cmd.append("--no-create-info")
        elif options.schema_only:
            cmd.append("--no-data")

        # Table filtering
        if options.include_tables:
            for table in options.include_tables:
                cmd.extend(["--tables", table])
        
        if options.exclude_tables:
            for table in options.exclude_tables:
                cmd.extend([f"--ignore-table={self.config.database}.{table}"])

        # Other options
        if options.verbose:
            cmd.append("--verbose")

        # Add database name
        cmd.append(self.config.database)

        return cmd

    async def _build_mysql_command(
        self, snapshot_path: Path, options: RestoreOptions
    ) -> List[str]:
        """Build mysql command with options."""
        cmd = ["mysql"]

        # Connection parameters
        cmd.extend(["-h", self.config.host])
        cmd.extend(["-P", str(self.config.port)])

        if self.config.username:
            cmd.extend(["-u", self.config.username])

        # Add database name
        cmd.append(self.config.database)

        return cmd

    async def _get_mysqldump_version(self) -> str:
        """Get mysqldump version."""
        try:
            process = await asyncio.create_subprocess_exec(
                "mysqldump",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return stdout.decode().strip()
        except Exception:
            return "unknown"

    async def _get_mysql_version(self) -> str:
        """Get mysql client version."""
        try:
            process = await asyncio.create_subprocess_exec(
                "mysql",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return stdout.decode().strip()
        except Exception:
            return "unknown"

    async def _monitor_dump_progress(
        self, process: asyncio.subprocess.Process, callback: ProgressCallback
    ) -> None:
        """Monitor mysqldump progress and update callback."""
        progress = 0
        while process.returncode is None:
            if await callback.is_cancelled():
                process.terminate()
                break

            progress = min(progress + 5, 95)  # Increment progress
            await callback.update(progress, 100, "Creating snapshot...", "dump")
            await asyncio.sleep(1)

        if process.returncode == 0:
            await callback.update(100, 100, "Snapshot completed", "dump")

    async def _monitor_restore_progress(
        self, process: asyncio.subprocess.Process, callback: ProgressCallback
    ) -> None:
        """Monitor mysql restore progress and update callback."""
        progress = 0
        while process.returncode is None:
            if await callback.is_cancelled():
                process.terminate()
                break

            progress = min(progress + 5, 95)  # Increment progress
            await callback.update(progress, 100, "Restoring snapshot...", "restore")
            await asyncio.sleep(1)

        if process.returncode == 0:
            await callback.update(100, 100, "Restore completed", "restore")

    async def _calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file."""
        hash_sha256 = hashlib.sha256()

        def _read_file_chunks():
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    hash_sha256.update(chunk)

        # Run in thread to avoid blocking
        await asyncio.get_event_loop().run_in_executor(None, _read_file_chunks)
        return hash_sha256.hexdigest()