"""PostgreSQL database adapter implementation."""

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

import asyncpg
import psycopg2
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


class PostgreSQLAdapter(DatabaseAdapter):
    """PostgreSQL database adapter using pg_dump/pg_restore."""

    def __init__(self, config: DatabaseConfig) -> None:
        """
        Initialize PostgreSQL adapter.

        Args:
            config: Database configuration
        """
        if config.driver != "postgresql":
            raise DatabaseAdapterError(
                f"Invalid driver for PostgreSQL adapter: {config.driver}", "postgresql"
            )

        self.config = config
        self._connection: Optional[asyncpg.Connection] = None
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

    def _get_connection_string(self, include_password: bool = True) -> str:
        """Build PostgreSQL connection string."""
        parts = [
            f"host={self.config.host}",
            f"port={self.config.port}",
            f"dbname={self.config.database}",
        ]

        if self.config.username:
            parts.append(f"user={self.config.username}")

        if include_password and self.config.password:
            parts.append(f"password={self.config.password}")

        if self.config.ssl_mode != "prefer":
            parts.append(f"sslmode={self.config.ssl_mode}")

        return " ".join(parts)

    def _get_pg_dump_env(self) -> Dict[str, str]:
        """Get environment variables for pg_dump/pg_restore."""
        env = os.environ.copy()

        if self.config.password:
            env["PGPASSWORD"] = self.config.password

        return env

    async def connect(self) -> bool:
        """Establish and validate database connection."""
        async with self._connection_lock:
            if self._connection and not self._connection.is_closed():
                return True

            for attempt in range(self._connection_retries):
                try:
                    connection_string = self._get_connection_string()
                    self._connection = await asyncio.wait_for(
                        asyncpg.connect(connection_string),
                        timeout=self._connection_timeout,
                    )

                    # Test connection with simple query
                    await asyncio.wait_for(
                        self._connection.fetchval("SELECT 1"),
                        timeout=self._query_timeout,
                    )

                    logger.info(
                        f"Connected to PostgreSQL database: {self.config.host}:{self.config.port}/{self.config.database}"
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
                            error_msg, self._get_connection_string(False)
                        )
                    await asyncio.sleep(2**attempt)

            return False

    async def disconnect(self) -> None:
        """Close database connection and cleanup resources."""
        async with self._connection_lock:
            if self._connection and not self._connection.is_closed():
                try:
                    await self._connection.close()
                    logger.info("Disconnected from PostgreSQL database")
                except Exception as e:
                    logger.warning(f"Error during disconnect: {e}")
                finally:
                    self._connection = None

    async def test_connection(self) -> bool:
        """Test database connection without establishing permanent connection."""
        try:
            connection_string = self._get_connection_string()
            conn = await asyncio.wait_for(
                asyncpg.connect(connection_string), timeout=self._connection_timeout
            )

            await asyncio.wait_for(
                conn.fetchval("SELECT 1"), timeout=self._query_timeout
            )

            await conn.close()
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
        """Create database snapshot using pg_dump."""
        if options is None:
            options = SnapshotOptions()

        start_time = time.time()
        output_path = output_path.resolve()

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build pg_dump command
        cmd = await self._build_pg_dump_command(output_path, options)
        env = self._get_pg_dump_env()

        logger.info(f"Creating PostgreSQL snapshot: {output_path}")
        logger.debug(f"pg_dump command: {' '.join(cmd)}")

        try:
            # Get database info before snapshot
            db_info = await self.get_database_info()

            if progress_callback:
                await progress_callback.update(
                    0, 100, "Starting snapshot creation", "dump"
                )

            # Execute pg_dump
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
                error_msg = f"pg_dump failed (exit code {process.returncode}): {stderr.decode()}"
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
                    "pg_dump_version": await self._get_pg_dump_version(),
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
        """Restore database from snapshot using pg_restore."""
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

        # Build pg_restore command
        cmd = await self._build_pg_restore_command(snapshot_path, options)
        env = self._get_pg_dump_env()

        logger.info(f"Restoring PostgreSQL snapshot: {snapshot_path}")
        logger.debug(f"pg_restore command: {' '.join(cmd)}")

        try:
            if progress_callback:
                await progress_callback.update(
                    0, 100, "Starting snapshot restore", "restore"
                )

            # Execute pg_restore
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
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
                error_msg = f"pg_restore failed (exit code {process.returncode}): {stderr.decode()}"
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
                    "pg_restore_version": await self._get_pg_restore_version(),
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
        if not self._connection or self._connection.is_closed():
            await self.connect()

        try:
            # Get basic database info
            version_query = "SELECT version()"
            version = await self._connection.fetchval(version_query)

            # Parse version string
            version_match = re.search(r"PostgreSQL ([\d.]+)", version)
            version_str = version_match.group(1) if version_match else version

            # Get database size
            size_query = "SELECT pg_database_size(current_database())"
            size_bytes = await self._connection.fetchval(size_query)

            # Get table count
            table_query = """
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_catalog = current_database() 
                AND table_type = 'BASE TABLE'
            """
            table_count = await self._connection.fetchval(table_query)

            # Get schema count
            schema_query = """
                SELECT COUNT(*) 
                FROM information_schema.schemata 
                WHERE catalog_name = current_database()
                AND schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            """
            schema_count = await self._connection.fetchval(schema_query)

            # Get connection count
            conn_query = "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            connection_count = await self._connection.fetchval(conn_query)

            # Get database settings
            encoding_query = "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database()"
            encoding = await self._connection.fetchval(encoding_query)

            collation_query = (
                "SELECT datcollate FROM pg_database WHERE datname = current_database()"
            )
            collation = await self._connection.fetchval(collation_query)

            timezone_query = "SHOW timezone"
            timezone = await self._connection.fetchval(timezone_query)

            # Get uptime (PostgreSQL start time)
            uptime_query = (
                "SELECT EXTRACT(EPOCH FROM (now() - pg_postmaster_start_time()))"
            )
            uptime_seconds = await self._connection.fetchval(uptime_query)

            # Get schema names
            schemas_query = """
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE catalog_name = current_database()
                AND schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                ORDER BY schema_name
            """
            schemas = [row[0] for row in await self._connection.fetch(schemas_query)]

            # Get installed extensions
            extensions_query = "SELECT extname FROM pg_extension ORDER BY extname"
            extensions = [
                row[0] for row in await self._connection.fetch(extensions_query)
            ]

            # Get important settings
            settings_query = """
                SELECT name, setting 
                FROM pg_settings 
                WHERE name IN (
                    'max_connections', 'shared_buffers', 'effective_cache_size',
                    'work_mem', 'maintenance_work_mem', 'wal_level', 'log_statement'
                )
            """
            settings_rows = await self._connection.fetch(settings_query)
            settings = {row[0]: row[1] for row in settings_rows}

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
                uptime_seconds=int(uptime_seconds) if uptime_seconds else None,
                schemas=schemas,
                extensions=extensions,
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
        """Validate PostgreSQL snapshot using pg_restore."""
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

            # Test pg_restore with list-only mode
            cmd = ["pg_restore", "--list", str(snapshot_path)]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = f"Invalid snapshot format: {stderr.decode()}"
                return ValidationResult(
                    valid=False,
                    snapshot_path=snapshot_path,
                    format_valid=False,
                    size_bytes=file_size,
                    checksum=checksum,
                    compatible=False,
                    error_message=error_msg,
                )

            # Parse pg_restore output for metadata
            output_lines = stdout.decode().split("\n")

            # Count schemas and tables from output
            schema_count = 0
            table_count = 0
            database_version = None

            for line in output_lines:
                if "SCHEMA" in line:
                    schema_count += 1
                elif "TABLE" in line:
                    table_count += 1
                elif "PostgreSQL database dump" in line:
                    # Try to extract version from dump header
                    version_match = re.search(r"PostgreSQL ([\d.]+)", line)
                    if version_match:
                        database_version = version_match.group(1)

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
            estimated_restore_time = file_size / (10 * 1024 * 1024)  # ~10MB/second

            return ValidationResult(
                valid=True,
                snapshot_path=snapshot_path,
                format_valid=True,
                size_bytes=file_size,
                checksum=checksum,
                database_version=database_version,
                compatible=compatible,
                schema_count=schema_count,
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
        """Get supported snapshot formats for PostgreSQL."""
        return {
            SnapshotFormat.CUSTOM.value,
            SnapshotFormat.TAR.value,
            SnapshotFormat.PLAIN.value,
            SnapshotFormat.DIRECTORY.value,
        }

    async def estimate_snapshot_size(
        self, options: Optional[SnapshotOptions] = None
    ) -> int:
        """Estimate snapshot size based on database size and options."""
        db_info = await self.get_database_info()
        base_size = db_info.size_bytes

        if options:
            # Schema/table filtering adjustments first (affects base data size)
            if options.schema_only:
                base_size = int(base_size * 0.01)  # Schema is much smaller
            elif options.data_only:
                base_size = int(base_size * 0.95)  # Slightly less without schema

            # Apply compression ratio estimate to the filtered size
            if options.compression == CompressionType.GZIP:
                base_size = int(base_size * 0.3)  # ~70% compression
            elif options.compression == CompressionType.LZ4:
                base_size = int(base_size * 0.5)  # ~50% compression
            elif options.compression == CompressionType.ZSTD:
                base_size = int(base_size * 0.25)  # ~75% compression

        return base_size

    async def list_schemas(self) -> list[str]:
        """List all schemas in the database."""
        if not self._connection or self._connection.is_closed():
            await self.connect()

        query = """
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE catalog_name = current_database()
            AND schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            ORDER BY schema_name
        """

        rows = await self._connection.fetch(query)
        return [row[0] for row in rows]

    async def list_tables(self, schema: Optional[str] = None) -> list[str]:
        """List all tables in the database or specific schema."""
        if not self._connection or self._connection.is_closed():
            await self.connect()

        if schema:
            query = """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_catalog = current_database() 
                AND table_schema = $1
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
            rows = await self._connection.fetch(query, schema)
            return [row[0] for row in rows]
        else:
            query = """
                SELECT table_schema || '.' || table_name 
                FROM information_schema.tables 
                WHERE table_catalog = current_database() 
                AND table_type = 'BASE TABLE'
                AND table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                ORDER BY table_schema, table_name
            """
            rows = await self._connection.fetch(query)
            return [row[0] for row in rows]

    # Helper methods

    async def _build_pg_dump_command(
        self, output_path: Path, options: SnapshotOptions
    ) -> List[str]:
        """Build pg_dump command with options."""
        cmd = ["pg_dump"]

        # Connection parameters
        cmd.extend(["-h", self.config.host])
        cmd.extend(["-p", str(self.config.port)])
        cmd.extend(["-d", self.config.database])

        if self.config.username:
            cmd.extend(["-U", self.config.username])

        # Format options
        if options.format == SnapshotFormat.CUSTOM:
            cmd.extend(["-F", "c"])
        elif options.format == SnapshotFormat.TAR:
            cmd.extend(["-F", "t"])
        elif options.format == SnapshotFormat.PLAIN:
            cmd.extend(["-F", "p"])
        elif options.format == SnapshotFormat.DIRECTORY:
            cmd.extend(["-F", "d"])

        # Compression
        if options.compression != CompressionType.NONE and options.format in [
            SnapshotFormat.CUSTOM,
            SnapshotFormat.DIRECTORY,
        ]:
            cmd.extend(["-Z", str(options.compression_level)])

        # Parallel jobs
        if options.parallel_jobs > 1 and options.format in [
            SnapshotFormat.CUSTOM,
            SnapshotFormat.DIRECTORY,
        ]:
            cmd.extend(["-j", str(options.parallel_jobs)])

        # Schema/table filtering
        if options.include_schemas:
            for schema in options.include_schemas:
                cmd.extend(["-n", schema])

        if options.exclude_schemas:
            for schema in options.exclude_schemas:
                cmd.extend(["-N", schema])

        if options.include_tables:
            for table in options.include_tables:
                cmd.extend(["-t", table])

        if options.exclude_tables:
            for table in options.exclude_tables:
                cmd.extend(["-T", table])

        # Data/schema options
        if options.data_only:
            cmd.append("--data-only")
        elif options.schema_only:
            cmd.append("--schema-only")

        # Other options
        if options.include_large_objects:
            cmd.append("--blobs")
        else:
            cmd.append("--no-blobs")

        if options.verbose:
            cmd.append("--verbose")

        # Output file
        cmd.extend(["-f", str(output_path)])

        return cmd

    async def _build_pg_restore_command(
        self, snapshot_path: Path, options: RestoreOptions
    ) -> List[str]:
        """Build pg_restore command with options."""
        cmd = ["pg_restore"]

        # Connection parameters
        cmd.extend(["-h", self.config.host])
        cmd.extend(["-p", str(self.config.port)])
        cmd.extend(["-d", self.config.database])

        if self.config.username:
            cmd.extend(["-U", self.config.username])

        # Parallel jobs
        if options.parallel_jobs > 1:
            cmd.extend(["-j", str(options.parallel_jobs)])

        # Clean database
        if options.clean:
            cmd.append("--clean")

        # Create database
        if options.create:
            cmd.append("--create")

        # Transaction options
        if options.single_transaction:
            cmd.append("--single-transaction")

        if options.disable_triggers:
            cmd.append("--disable-triggers")

        # Ownership and privileges
        if options.no_owner:
            cmd.append("--no-owner")

        if options.no_privileges:
            cmd.append("--no-privileges")

        # Schema/table filtering
        if options.include_schemas:
            for schema in options.include_schemas:
                cmd.extend(["-n", schema])

        if options.exclude_schemas:
            for schema in options.exclude_schemas:
                cmd.extend(["-N", schema])

        if options.include_tables:
            for table in options.include_tables:
                cmd.extend(["-t", table])

        if options.exclude_tables:
            for table in options.exclude_tables:
                cmd.extend(["-T", table])

        # Verbose output
        if options.verbose:
            cmd.append("--verbose")

        # Input file
        cmd.append(str(snapshot_path))

        return cmd

    async def _get_pg_dump_version(self) -> str:
        """Get pg_dump version."""
        try:
            process = await asyncio.create_subprocess_exec(
                "pg_dump",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return stdout.decode().strip()
        except Exception:
            return "unknown"

    async def _get_pg_restore_version(self) -> str:
        """Get pg_restore version."""
        try:
            process = await asyncio.create_subprocess_exec(
                "pg_restore",
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
        """Monitor pg_dump progress and update callback."""
        # Simple progress monitoring - in real implementation would parse pg_dump output
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
        """Monitor pg_restore progress and update callback."""
        # Simple progress monitoring - in real implementation would parse pg_restore output
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
