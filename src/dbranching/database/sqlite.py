"""SQLite database adapter implementation."""

import asyncio
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiosqlite
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


class SQLiteAdapter(DatabaseAdapter):
    """SQLite database adapter using file operations and sqlite3."""

    def __init__(self, config: DatabaseConfig) -> None:
        """
        Initialize SQLite adapter.

        Args:
            config: Database configuration
        """
        if config.driver != "sqlite":
            raise DatabaseAdapterError(
                f"Invalid driver for SQLite adapter: {config.driver}", "sqlite"
            )

        self.config = config
        self._connection: Optional[aiosqlite.Connection] = None
        self._connection_lock = asyncio.Lock()
        self._connection_timeout = self._parse_timeout(config.connect_timeout)
        self._query_timeout = self._parse_timeout(config.query_timeout)
        
        # For SQLite, the database field contains the file path
        self.db_path = Path(self.config.database).resolve()

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

    async def connect(self) -> bool:
        """Establish and validate database connection."""
        async with self._connection_lock:
            if self._connection:
                return True

            try:
                # Ensure parent directory exists
                if self.db_path.parent != Path("."):
                    self.db_path.parent.mkdir(parents=True, exist_ok=True)

                # Enable WAL mode for better performance and concurrency
                self._connection = await asyncio.wait_for(
                    aiosqlite.connect(
                        str(self.db_path),
                        timeout=self._connection_timeout
                    ),
                    timeout=self._connection_timeout,
                )
                
                # Configure SQLite for optimal performance
                await self._connection.execute("PRAGMA journal_mode=WAL")
                await self._connection.execute("PRAGMA synchronous=NORMAL")
                await self._connection.execute("PRAGMA foreign_keys=ON")
                await self._connection.execute("PRAGMA temp_store=MEMORY")
                await self._connection.commit()

                # Test connection with simple query
                await asyncio.wait_for(
                    self._connection.execute("SELECT 1"),
                    timeout=self._query_timeout,
                )

                logger.info(f"Connected to SQLite database: {self.db_path}")
                return True

            except asyncio.TimeoutError:
                error_msg = f"Connection timeout after {self._connection_timeout}s"
                logger.error(error_msg)
                raise DatabaseTimeoutError(error_msg, self._connection_timeout)

            except Exception as e:
                error_msg = f"Connection failed: {str(e)}"
                logger.error(error_msg)
                raise DatabaseConnectionError(error_msg, str(self.db_path))

    async def disconnect(self) -> None:
        """Close database connection and cleanup resources."""
        async with self._connection_lock:
            if self._connection:
                try:
                    await self._connection.close()
                    logger.info("Disconnected from SQLite database")
                except Exception as e:
                    logger.warning(f"Error during disconnect: {e}")
                finally:
                    self._connection = None

    async def test_connection(self) -> bool:
        """Test database connection without establishing permanent connection."""
        try:
            if not self.db_path.exists():
                # For SQLite, if file doesn't exist, we can still "connect" (it would create the file)
                return self.db_path.parent.exists() and os.access(self.db_path.parent, os.W_OK)
            
            conn = await asyncio.wait_for(
                aiosqlite.connect(str(self.db_path), timeout=self._connection_timeout),
                timeout=self._connection_timeout
            )

            await asyncio.wait_for(
                conn.execute("SELECT 1"), timeout=self._query_timeout
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
        """Create database snapshot by copying SQLite file or exporting SQL."""
        if options is None:
            options = SnapshotOptions()

        start_time = time.time()
        output_path = output_path.resolve()

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Creating SQLite snapshot: {output_path}")

        try:
            # Get database info before snapshot
            db_info = await self.get_database_info()

            if progress_callback:
                await progress_callback.update(
                    0, 100, "Starting snapshot creation", "dump"
                )

            if options.format == SnapshotFormat.PLAIN:
                # Export as SQL dump
                await self._create_sql_dump(output_path, options, progress_callback)
            else:
                # Copy database file (default for SQLite)
                await self._create_file_copy(output_path, options, progress_callback)

            # Calculate file sizes and metadata
            if not output_path.exists():
                raise SnapshotError(f"Snapshot file was not created: {output_path}")

            file_size = output_path.stat().st_size
            duration = time.time() - start_time

            # Apply compression if requested
            if options.compression != CompressionType.NONE:
                compressed_path = await self._compress_file(output_path, options)
                if compressed_path != output_path:
                    output_path.unlink()  # Remove uncompressed file
                    output_path = compressed_path
                    file_size = output_path.stat().st_size

            # Calculate compression ratio if compressed
            compression_ratio = None
            compressed_size = None
            if options.compression != CompressionType.NONE:
                compressed_size = file_size
                compression_ratio = (
                    db_info.size_bytes / file_size if file_size > 0 else 0
                )

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
                warnings=[],
                metadata={
                    "sqlite_version": await self._get_sqlite_version(),
                    "database_version": db_info.version,
                    "options": options.dict(),
                    "format": options.format.value,
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
        """Restore database from snapshot."""
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

        logger.info(f"Restoring SQLite snapshot: {snapshot_path}")

        try:
            if progress_callback:
                await progress_callback.update(
                    0, 100, "Starting snapshot restore", "restore"
                )

            # Handle clean option
            if options.clean and self.db_path.exists():
                backup_path = self.db_path.with_suffix('.backup')
                shutil.move(str(self.db_path), str(backup_path))
                logger.info(f"Backed up existing database to: {backup_path}")

            # Decompress if needed
            working_path = snapshot_path
            if self._is_compressed_file(snapshot_path):
                working_path = await self._decompress_file(snapshot_path)

            # Determine restore method based on file format
            if self._is_sql_dump(working_path):
                await self._restore_from_sql_dump(working_path, options, progress_callback)
            else:
                await self._restore_from_file_copy(working_path, options, progress_callback)

            # Clean up temporary decompressed file
            if working_path != snapshot_path:
                working_path.unlink()

            duration = time.time() - start_time

            # Get post-restore database info
            db_info = await self.get_database_info()

            result = RestoreResult(
                success=True,
                snapshot_path=snapshot_path,
                duration_seconds=duration,
                tables_restored=db_info.table_count,
                schemas_restored=db_info.schema_count,
                warnings=[],
                metadata={
                    "sqlite_version": await self._get_sqlite_version(),
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
        if not self._connection:
            await self.connect()

        try:
            # Get SQLite version
            cursor = await self._connection.execute("SELECT sqlite_version()")
            version_result = await cursor.fetchone()
            version = version_result[0] if version_result else "Unknown"
            await cursor.close()

            # Get database size
            size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0

            # Get table count
            cursor = await self._connection.execute("""
                SELECT COUNT(*) 
                FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            table_result = await cursor.fetchone()
            table_count = table_result[0] if table_result else 0
            await cursor.close()

            # SQLite has a single main database, schema_count is always 1
            schema_count = 1

            # Get connection count (SQLite allows multiple readers, one writer)
            connection_count = 1  # Current connection

            # SQLite settings
            settings = {}
            pragma_queries = [
                ("journal_mode", "PRAGMA journal_mode"),
                ("synchronous", "PRAGMA synchronous"),
                ("foreign_keys", "PRAGMA foreign_keys"),
                ("page_size", "PRAGMA page_size"),
                ("cache_size", "PRAGMA cache_size"),
            ]

            for setting_name, query in pragma_queries:
                cursor = await self._connection.execute(query)
                result = await cursor.fetchone()
                if result:
                    settings[setting_name] = str(result[0])
                await cursor.close()

            # Get schema names (attached databases)
            cursor = await self._connection.execute("PRAGMA database_list")
            schemas_result = await cursor.fetchall()
            schemas = [row[1] for row in schemas_result]  # Database names
            await cursor.close()

            return DatabaseInfo(
                name=self.config.database,
                version=version,
                size_bytes=size_bytes,
                table_count=table_count,
                schema_count=schema_count,
                connection_count=connection_count,
                encoding="UTF-8",  # SQLite uses UTF-8 by default
                collation="BINARY",  # Default SQLite collation
                timezone="UTC",  # SQLite stores timestamps as UTC
                uptime_seconds=None,  # Not applicable to SQLite
                schemas=schemas,
                extensions=[],  # Extensions would require additional querying
                settings=settings,
                metadata={
                    "database_path": str(self.db_path),
                    "file_exists": self.db_path.exists(),
                },
            )

        except Exception as e:
            raise DatabaseConnectionError(f"Failed to get database info: {str(e)}")

    async def validate_snapshot(self, snapshot_path: Path) -> ValidationResult:
        """Validate SQLite snapshot by checking file format and structure."""
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

            # Check if it's a compressed file first
            working_path = snapshot_path
            if self._is_compressed_file(snapshot_path):
                working_path = await self._decompress_file(snapshot_path)

            # Check if it's an SQL dump or SQLite database file
            if self._is_sql_dump(working_path):
                result = await self._validate_sql_dump(working_path, snapshot_path, file_size, checksum)
            else:
                result = await self._validate_sqlite_file(working_path, snapshot_path, file_size, checksum)

            # Clean up temporary decompressed file
            if working_path != snapshot_path:
                working_path.unlink()

            return result

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
        """Get supported snapshot formats for SQLite."""
        return {
            SnapshotFormat.CUSTOM.value,  # SQLite database file
            SnapshotFormat.PLAIN.value,   # SQL dump
        }

    async def estimate_snapshot_size(
        self, options: Optional[SnapshotOptions] = None
    ) -> int:
        """Estimate snapshot size based on database size and options."""
        db_info = await self.get_database_info()
        base_size = db_info.size_bytes

        if options:
            # For SQL dump, estimate larger size due to text format
            if options.format == SnapshotFormat.PLAIN:
                base_size = int(base_size * 2.5)  # SQL text is larger than binary

            # Schema/table filtering adjustments
            if options.schema_only:
                base_size = int(base_size * 0.01)  # Schema is much smaller
            elif options.data_only:
                base_size = int(base_size * 0.95)  # Slightly less without schema

            # Apply compression ratio estimate
            if options.compression == CompressionType.GZIP:
                if options.format == SnapshotFormat.PLAIN:
                    base_size = int(base_size * 0.2)  # SQL text compresses well
                else:
                    base_size = int(base_size * 0.7)  # Binary doesn't compress as much
            elif options.compression == CompressionType.LZ4:
                base_size = int(base_size * 0.5)  # ~50% compression
            elif options.compression == CompressionType.ZSTD:
                if options.format == SnapshotFormat.PLAIN:
                    base_size = int(base_size * 0.15)  # Excellent compression for text
                else:
                    base_size = int(base_size * 0.6)  # Good compression for binary

        return base_size

    async def list_schemas(self) -> list[str]:
        """List all attached databases in SQLite."""
        if not self._connection:
            await self.connect()

        cursor = await self._connection.execute("PRAGMA database_list")
        results = await cursor.fetchall()
        await cursor.close()
        
        return [row[1] for row in results]  # Database names

    async def list_tables(self, schema: Optional[str] = None) -> list[str]:
        """List all tables in the database or specific schema."""
        if not self._connection:
            await self.connect()

        if schema and schema != "main":
            # For attached databases
            query = f"""
                SELECT name 
                FROM {schema}.sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """
        else:
            query = """
                SELECT name 
                FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """

        cursor = await self._connection.execute(query)
        results = await cursor.fetchall()
        await cursor.close()
        
        if schema and schema != "main":
            return [f"{schema}.{row[0]}" for row in results]
        else:
            return [row[0] for row in results]

    # Helper methods

    async def _create_file_copy(
        self, output_path: Path, options: SnapshotOptions, progress_callback: Optional[ProgressCallback]
    ) -> None:
        """Create snapshot by copying SQLite database file."""
        if not self.db_path.exists():
            raise SnapshotError(f"Database file does not exist: {self.db_path}")

        if progress_callback:
            await progress_callback.update(25, 100, "Copying database file...", "copy")

        # Use SQLite backup API for consistent copy
        if self._connection:
            await self._connection.close()
            self._connection = None

        # Use sqlite3 backup API for atomic copy
        def backup_database():
            source_conn = sqlite3.connect(str(self.db_path))
            backup_conn = sqlite3.connect(str(output_path))
            
            with backup_conn:
                source_conn.backup(backup_conn)
                
            source_conn.close()
            backup_conn.close()

        await asyncio.get_event_loop().run_in_executor(None, backup_database)

        if progress_callback:
            await progress_callback.update(100, 100, "File copy completed", "copy")

    async def _create_sql_dump(
        self, output_path: Path, options: SnapshotOptions, progress_callback: Optional[ProgressCallback]
    ) -> None:
        """Create snapshot as SQL dump."""
        if not self._connection:
            await self.connect()

        if progress_callback:
            await progress_callback.update(25, 100, "Creating SQL dump...", "dump")

        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            f.write("-- SQLite database dump\n")
            f.write(f"-- Generated by dbranching\n")
            f.write(f"-- Database: {self.db_path}\n\n")
            
            # Get all table creation statements
            cursor = await self._connection.execute("""
                SELECT sql FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%' 
                ORDER BY name
            """)
            
            table_schemas = await cursor.fetchall()
            await cursor.close()

            if not options.data_only:
                # Write table schemas
                for schema_row in table_schemas:
                    if schema_row[0]:
                        f.write(f"{schema_row[0]};\n\n")

            if progress_callback:
                await progress_callback.update(50, 100, "Exporting table data...", "dump")

            if not options.schema_only:
                # Export data for each table
                cursor = await self._connection.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """)
                
                tables = await cursor.fetchall()
                await cursor.close()

                for table_row in tables:
                    table_name = table_row[0]
                    
                    # Skip excluded tables
                    if options.exclude_tables and table_name in options.exclude_tables:
                        continue
                    if options.include_tables and table_name not in options.include_tables:
                        continue

                    cursor = await self._connection.execute(f"SELECT * FROM {table_name}")
                    rows = await cursor.fetchall()
                    
                    if rows:
                        # Get column info
                        column_cursor = await self._connection.execute(f"PRAGMA table_info({table_name})")
                        columns = await column_cursor.fetchall()
                        await column_cursor.close()
                        
                        column_names = [col[1] for col in columns]
                        
                        for row in rows:
                            values = []
                            for value in row:
                                if value is None:
                                    values.append('NULL')
                                elif isinstance(value, str):
                                    escaped_value = value.replace("'", "''")
                                    values.append(f"'{escaped_value}'")
                                else:
                                    values.append(str(value))
                            
                            f.write(f"INSERT INTO {table_name} ({', '.join(column_names)}) VALUES ({', '.join(values)});\n")
                    
                    await cursor.close()
                    f.write("\n")

        if progress_callback:
            await progress_callback.update(100, 100, "SQL dump completed", "dump")

    async def _restore_from_file_copy(
        self, snapshot_path: Path, options: RestoreOptions, progress_callback: Optional[ProgressCallback]
    ) -> None:
        """Restore database by copying SQLite file."""
        if progress_callback:
            await progress_callback.update(25, 100, "Copying database file...", "restore")

        # Close existing connection
        if self._connection:
            await self._connection.close()
            self._connection = None

        # Copy file
        shutil.copy2(str(snapshot_path), str(self.db_path))

        if progress_callback:
            await progress_callback.update(100, 100, "File restore completed", "restore")

    async def _restore_from_sql_dump(
        self, snapshot_path: Path, options: RestoreOptions, progress_callback: Optional[ProgressCallback]
    ) -> None:
        """Restore database from SQL dump."""
        if progress_callback:
            await progress_callback.update(25, 100, "Executing SQL dump...", "restore")

        # Ensure we have a connection
        if not self._connection:
            await self.connect()

        # Read and execute SQL file
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        # Split into individual statements and execute
        statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip()]
        
        total_statements = len(statements)
        for i, statement in enumerate(statements):
            if statement and not statement.startswith('--'):
                await self._connection.execute(statement)
                
                if progress_callback and i % 100 == 0:
                    progress = 25 + int((i / total_statements) * 70)
                    await progress_callback.update(progress, 100, f"Executing statement {i+1}/{total_statements}", "restore")

        await self._connection.commit()

        if progress_callback:
            await progress_callback.update(100, 100, "SQL restore completed", "restore")

    def _is_compressed_file(self, file_path: Path) -> bool:
        """Check if file is compressed."""
        return file_path.suffix.lower() in ['.gz', '.bz2', '.xz', '.zst']

    def _is_sql_dump(self, file_path: Path) -> bool:
        """Check if file is an SQL dump."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(100).decode('utf-8', errors='ignore')
                return 'CREATE TABLE' in header.upper() or 'INSERT INTO' in header.upper()
        except:
            return False

    async def _compress_file(self, file_path: Path, options: SnapshotOptions) -> Path:
        """Compress file based on compression options."""
        if options.compression == CompressionType.NONE:
            return file_path

        compressed_path = file_path.with_suffix(file_path.suffix + f'.{options.compression.value}')
        
        def compress():
            if options.compression == CompressionType.GZIP:
                import gzip
                with open(file_path, 'rb') as f_in:
                    with gzip.open(compressed_path, 'wb', compresslevel=options.compression_level) as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif options.compression == CompressionType.LZ4:
                import lz4.frame
                with open(file_path, 'rb') as f_in:
                    with lz4.frame.open(compressed_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif options.compression == CompressionType.ZSTD:
                import zstandard as zstd
                cctx = zstd.ZstdCompressor(level=options.compression_level)
                with open(file_path, 'rb') as f_in:
                    with open(compressed_path, 'wb') as f_out:
                        cctx.copy_stream(f_in, f_out)

        await asyncio.get_event_loop().run_in_executor(None, compress)
        return compressed_path

    async def _decompress_file(self, file_path: Path) -> Path:
        """Decompress file and return path to decompressed file."""
        if not self._is_compressed_file(file_path):
            return file_path

        temp_path = file_path.with_suffix('')  # Remove compression extension
        
        def decompress():
            suffix = file_path.suffix.lower()
            if suffix == '.gz':
                import gzip
                with gzip.open(file_path, 'rb') as f_in:
                    with open(temp_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif suffix == '.bz2':
                import bz2
                with bz2.open(file_path, 'rb') as f_in:
                    with open(temp_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif suffix in ['.xz', '.lzma']:
                import lzma
                with lzma.open(file_path, 'rb') as f_in:
                    with open(temp_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
            elif suffix == '.zst':
                import zstandard as zstd
                dctx = zstd.ZstdDecompressor()
                with open(file_path, 'rb') as f_in:
                    with open(temp_path, 'wb') as f_out:
                        dctx.copy_stream(f_in, f_out)

        await asyncio.get_event_loop().run_in_executor(None, decompress)
        return temp_path

    async def _validate_sqlite_file(
        self, file_path: Path, original_path: Path, file_size: int, checksum: str
    ) -> ValidationResult:
        """Validate SQLite database file."""
        try:
            # Check SQLite file signature
            with open(file_path, 'rb') as f:
                header = f.read(16)
                if not header.startswith(b'SQLite format 3\x00'):
                    return ValidationResult(
                        valid=False,
                        snapshot_path=original_path,
                        format_valid=False,
                        size_bytes=file_size,
                        checksum=checksum,
                        compatible=False,
                        error_message="File is not a valid SQLite database",
                    )

            # Try to open and query the database
            conn = sqlite3.connect(str(file_path))
            cursor = conn.cursor()
            
            # Get database info
            cursor.execute("SELECT sqlite_version()")
            version_result = cursor.fetchone()
            database_version = version_result[0] if version_result else None

            # Count tables
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            table_count = cursor.fetchone()[0]

            cursor.close()
            conn.close()

            # Estimate restore time based on file size
            estimated_restore_time = file_size / (50 * 1024 * 1024)  # ~50MB/second

            return ValidationResult(
                valid=True,
                snapshot_path=original_path,
                format_valid=True,
                size_bytes=file_size,
                checksum=checksum,
                database_version=database_version,
                compatible=True,
                schema_count=1,
                table_count=table_count,
                estimated_restore_time=estimated_restore_time,
                warnings=[],
            )

        except Exception as e:
            return ValidationResult(
                valid=False,
                snapshot_path=original_path,
                format_valid=False,
                size_bytes=file_size,
                checksum=checksum,
                compatible=False,
                error_message=f"SQLite validation failed: {str(e)}",
            )

    async def _validate_sql_dump(
        self, file_path: Path, original_path: Path, file_size: int, checksum: str
    ) -> ValidationResult:
        """Validate SQL dump file."""
        try:
            table_count = 0
            has_create_statements = False
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f):
                    if line_num > 1000:  # Don't read entire file
                        break
                        
                    line_upper = line.strip().upper()
                    if line_upper.startswith('CREATE TABLE'):
                        table_count += 1
                        has_create_statements = True
                    elif 'CREATE TABLE' in line_upper:
                        table_count += 1
                        has_create_statements = True

            if not has_create_statements:
                return ValidationResult(
                    valid=False,
                    snapshot_path=original_path,
                    format_valid=False,
                    size_bytes=file_size,
                    checksum=checksum,
                    compatible=False,
                    error_message="File does not appear to be a valid SQL dump",
                )

            # Estimate restore time based on file size
            estimated_restore_time = file_size / (10 * 1024 * 1024)  # ~10MB/second for SQL

            return ValidationResult(
                valid=True,
                snapshot_path=original_path,
                format_valid=True,
                size_bytes=file_size,
                checksum=checksum,
                database_version=None,  # Can't determine from SQL dump
                compatible=True,
                schema_count=1,
                table_count=table_count,
                estimated_restore_time=estimated_restore_time,
                warnings=[],
            )

        except Exception as e:
            return ValidationResult(
                valid=False,
                snapshot_path=original_path,
                format_valid=False,
                size_bytes=file_size,
                checksum=checksum,
                compatible=False,
                error_message=f"SQL dump validation failed: {str(e)}",
            )

    async def _get_sqlite_version(self) -> str:
        """Get SQLite version."""
        try:
            if self._connection:
                cursor = await self._connection.execute("SELECT sqlite_version()")
                result = await cursor.fetchone()
                await cursor.close()
                return result[0] if result else "unknown"
            else:
                return sqlite3.sqlite_version
        except Exception:
            return "unknown"

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