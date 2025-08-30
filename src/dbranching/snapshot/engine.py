"""Core snapshot engine that orchestrates database snapshot operations."""

import asyncio
import logging
import time
import tempfile
from pathlib import Path
from typing import Optional, Callable, List, Dict

from ..config import DatabaseConfig
from ..database.adapter import DatabaseAdapter
from ..database.postgresql import PostgreSQLAdapter
from ..database.models import SnapshotOptions, RestoreOptions, ProgressCallback
from ..exceptions import SnapshotError, ValidationError, StorageError, DatabaseAdapterError

from .models import (
    SnapshotCreateOptions,
    SnapshotRestoreOptions,
    SnapshotInfo,
    SnapshotMetadata,
    ValidationResult,
    ProgressReport,
    OperationPhase,
    SnapshotStatus,
    DatabaseMetadata,
    FileMetadata,
    CompressionType
)
from .atomic import AtomicOperationManager
from .compression import CompressionEngine
from .progress import MultiPhaseProgressTracker, ProgressTracker
from .metadata import MetadataManager

logger = logging.getLogger(__name__)


class SnapshotEngineProgressCallback(ProgressCallback):
    """Progress callback adapter for database adapter operations."""
    
    def __init__(self, progress_tracker: ProgressTracker):
        super().__init__()
        self.progress_tracker = progress_tracker
    
    async def update(
        self,
        current: int,
        total: int,
        message: str = "",
        stage: str = "",
    ) -> None:
        """Update progress through the tracker."""
        await self.progress_tracker.update(current, message, stage)


class SnapshotEngine:
    """
    Core snapshot engine that orchestrates database snapshot creation and restoration.
    
    Provides atomic operations, compression, metadata management, integrity validation,
    and performance optimization for large databases.
    """
    
    def __init__(
        self,
        database_config: DatabaseConfig,
        storage_base_path: Optional[Path] = None,
        temp_dir: Optional[Path] = None
    ):
        """
        Initialize snapshot engine.
        
        Args:
            database_config: Database configuration
            storage_base_path: Base path for snapshot storage
            temp_dir: Temporary directory for operations
            
        Raises:
            DatabaseAdapterError: If database adapter cannot be created
        """
        self.database_config = database_config
        self.storage_base_path = storage_base_path or Path.cwd() / "snapshots"
        
        # Initialize components
        self.atomic_manager = AtomicOperationManager(temp_dir)
        self.compression_engine = CompressionEngine()
        self.metadata_manager = MetadataManager()
        
        # Initialize database adapter
        self.adapter = self._create_database_adapter(database_config)
        
        # Ensure storage directory exists
        self.storage_base_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Snapshot engine initialized for {database_config.driver} database")
    
    def _create_database_adapter(self, config: DatabaseConfig) -> DatabaseAdapter:
        """Create appropriate database adapter based on configuration."""
        if config.driver == "postgresql":
            return PostgreSQLAdapter(config)
        else:
            raise DatabaseAdapterError(f"Unsupported database driver: {config.driver}")
    
    async def create_snapshot(
        self,
        options: SnapshotCreateOptions,
        progress_callback: Optional[Callable[[ProgressReport], None]] = None
    ) -> SnapshotInfo:
        """
        Create atomic database snapshot with compression and validation.
        
        Args:
            options: Snapshot creation options
            progress_callback: Optional callback for progress updates
            
        Returns:
            SnapshotInfo with operation details
            
        Raises:
            SnapshotError: If snapshot creation fails
            ValidationError: If options are invalid
            StorageError: If storage operations fail
        """
        start_time = time.time()
        snapshot_path = self.storage_base_path / options.name
        
        # Validate options
        await self._validate_create_options(options, snapshot_path)
        
        # Setup multi-phase progress tracking
        phase_weights = {
            OperationPhase.INITIALIZING: 0.05,
            OperationPhase.COLLECTING_METADATA: 0.10,
            OperationPhase.CREATING_SCHEMA_DUMP: 0.20,
            OperationPhase.CREATING_DATA_DUMP: 0.40,
            OperationPhase.COMPRESSING: 0.15,
            OperationPhase.VALIDATING: 0.08,
            OperationPhase.FINALIZING: 0.02,
        }
        
        progress_tracker = MultiPhaseProgressTracker(phase_weights, progress_callback)
        
        try:
            # Use atomic operation for safety
            async with self.atomic_manager.atomic_operation(
                target_path=snapshot_path,
                backup_existing=True,
                cleanup_on_success=True
            ) as atomic_ctx:
                
                # Phase 1: Initialize
                init_tracker = await progress_tracker.start_phase(
                    OperationPhase.INITIALIZING, 100, "Initializing snapshot creation"
                )
                
                await self.adapter.connect()
                await init_tracker.update(50, "Connected to database")
                
                # Create snapshot directory structure
                snapshot_temp_dir = await self.atomic_manager.get_temp_dir_path(
                    atomic_ctx, options.name
                )
                await init_tracker.update(100, "Initialization completed")
                await progress_tracker.complete_phase(OperationPhase.INITIALIZING)
                
                # Phase 2: Collect metadata
                metadata_tracker = await progress_tracker.start_phase(
                    OperationPhase.COLLECTING_METADATA, 100, "Collecting database metadata"
                )
                
                db_info = await self.adapter.get_database_info()
                database_metadata = DatabaseMetadata(
                    type=self.database_config.driver,
                    version=db_info.version,
                    size_bytes=db_info.size_bytes,
                    table_count=db_info.table_count,
                    schema_count=db_info.schema_count,
                    schema_checksum="",  # Will be calculated from schema dump
                    encoding=db_info.encoding,
                    collation=db_info.collation,
                    timezone=db_info.timezone,
                    extensions=db_info.extensions
                )
                
                await metadata_tracker.update(100, "Database metadata collected")
                await progress_tracker.complete_phase(OperationPhase.COLLECTING_METADATA)
                
                # Convert options to database adapter format
                snapshot_opts = self._convert_to_snapshot_options(options)
                
                # Phase 3: Create schema dump
                schema_tracker = await progress_tracker.start_phase(
                    OperationPhase.CREATING_SCHEMA_DUMP, 100, "Creating schema dump"
                )
                
                schema_file = await self._create_schema_dump(
                    snapshot_temp_dir, snapshot_opts, schema_tracker
                )
                await progress_tracker.complete_phase(OperationPhase.CREATING_SCHEMA_DUMP)
                
                # Phase 4: Create data dump (if not schema-only)
                data_file = None
                if not options.schema_only:
                    data_tracker = await progress_tracker.start_phase(
                        OperationPhase.CREATING_DATA_DUMP, 100, "Creating data dump"
                    )
                    
                    data_file = await self._create_data_dump(
                        snapshot_temp_dir, snapshot_opts, data_tracker
                    )
                    await progress_tracker.complete_phase(OperationPhase.CREATING_DATA_DUMP)
                
                # Phase 5: Compress files
                compression_tracker = await progress_tracker.start_phase(
                    OperationPhase.COMPRESSING, 100, "Compressing snapshot files"
                )
                
                compressed_files = await self._compress_snapshot_files(
                    snapshot_temp_dir,
                    [f for f in [schema_file, data_file] if f],
                    options,
                    compression_tracker
                )
                await progress_tracker.complete_phase(OperationPhase.COMPRESSING)
                
                # Collect file metadata
                file_metadata_list = []
                for file_path in compressed_files:
                    file_meta = await self.metadata_manager.extract_file_metadata(
                        file_path, options.compression, calculate_checksum=True
                    )
                    file_metadata_list.append(file_meta)
                
                # Phase 6: Create and validate metadata
                validation_tracker = await progress_tracker.start_phase(
                    OperationPhase.VALIDATING, 100, "Creating and validating metadata"
                )
                
                creation_duration = time.time() - start_time
                snapshot_metadata = await self.metadata_manager.create_metadata(
                    name=options.name,
                    description=options.description,
                    tags=options.tags,
                    database_metadata=database_metadata,
                    file_metadata_list=file_metadata_list,
                    compression=options.compression,
                    compression_level=options.compression_level,
                    creation_duration=creation_duration,
                    verify_integrity=options.verify_integrity
                )
                
                await validation_tracker.update(50, "Metadata created")
                
                # Save metadata
                await self.metadata_manager.save_metadata(snapshot_metadata, snapshot_temp_dir)
                await validation_tracker.update(75, "Metadata saved")
                
                # Validate snapshot if requested
                if options.verify_integrity:
                    validation_result = await self.validate_snapshot(options.name)
                    if not validation_result.valid:
                        raise SnapshotError(f"Snapshot validation failed: {validation_result.error_message}")
                
                await validation_tracker.update(100, "Validation completed")
                await progress_tracker.complete_phase(OperationPhase.VALIDATING)
                
                # Phase 7: Finalize
                finalize_tracker = await progress_tracker.start_phase(
                    OperationPhase.FINALIZING, 100, "Finalizing snapshot"
                )
                
                # Atomic operation will commit the snapshot
                await finalize_tracker.update(100, "Snapshot finalized")
                await progress_tracker.complete_phase(OperationPhase.FINALIZING)
            
            # Create snapshot info
            total_duration = time.time() - start_time
            snapshot_info = SnapshotInfo(
                name=options.name,
                path=snapshot_path,
                status=SnapshotStatus.COMPLETED,
                created_at=snapshot_metadata.created_at,
                size_bytes=snapshot_metadata.total_size_bytes,
                database_type=database_metadata.type,
                database_version=database_metadata.version,
                compression_ratio=snapshot_metadata.compression_ratio,
                table_count=database_metadata.table_count,
                schema_count=database_metadata.schema_count,
                tags=options.tags,
                description=options.description
            )
            
            logger.info(f"Snapshot created successfully: {snapshot_info}")
            return snapshot_info
            
        except Exception as e:
            logger.error(f"Snapshot creation failed for {options.name}: {e}")
            
            # Update progress to failed state
            if progress_callback:
                failed_report = ProgressReport(
                    phase=OperationPhase.FAILED,
                    current=0,
                    total=100,
                    percentage=0,
                    message=f"Snapshot creation failed: {str(e)}"
                )
                try:
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(failed_report)
                    else:
                        progress_callback(failed_report)
                except Exception:
                    pass
            
            if isinstance(e, (SnapshotError, ValidationError, StorageError)):
                raise
            else:
                raise SnapshotError(f"Snapshot creation failed: {str(e)}")
        
        finally:
            await self.adapter.disconnect()
    
    async def restore_snapshot(
        self,
        name: str,
        options: Optional[SnapshotRestoreOptions] = None,
        progress_callback: Optional[Callable[[ProgressReport], None]] = None
    ) -> SnapshotInfo:
        """
        Restore database from snapshot with atomic rollback on failure.
        
        Args:
            name: Snapshot name to restore
            options: Restore options, uses defaults if None
            progress_callback: Optional callback for progress updates
            
        Returns:
            SnapshotInfo with restoration details
            
        Raises:
            SnapshotError: If restore fails
            ValidationError: If snapshot is invalid
        """
        if options is None:
            options = SnapshotRestoreOptions()
        
        start_time = time.time()
        snapshot_path = self.storage_base_path / name
        
        if not snapshot_path.exists():
            raise SnapshotError(f"Snapshot not found: {name}")
        
        # Setup progress tracking
        phase_weights = {
            OperationPhase.INITIALIZING: 0.10,
            OperationPhase.VALIDATING: 0.15,
            OperationPhase.CREATING_SCHEMA_DUMP: 0.10,  # Backup phase
            OperationPhase.RESTORING: 0.60,
            OperationPhase.FINALIZING: 0.05,
        }
        
        progress_tracker = MultiPhaseProgressTracker(phase_weights, progress_callback)
        
        try:
            # Phase 1: Initialize
            init_tracker = await progress_tracker.start_phase(
                OperationPhase.INITIALIZING, 100, "Initializing snapshot restore"
            )
            
            await self.adapter.connect()
            await init_tracker.update(100, "Initialization completed")
            await progress_tracker.complete_phase(OperationPhase.INITIALIZING)
            
            # Phase 2: Validate snapshot
            if options.verify_integrity:
                validation_tracker = await progress_tracker.start_phase(
                    OperationPhase.VALIDATING, 100, "Validating snapshot integrity"
                )
                
                validation_result = await self.validate_snapshot(name)
                if not validation_result.valid:
                    raise ValidationError(f"Snapshot validation failed: {validation_result.error_message}")
                
                await validation_tracker.update(100, "Snapshot validated")
                await progress_tracker.complete_phase(OperationPhase.VALIDATING)
            
            # Load snapshot metadata
            snapshot_metadata = await self.metadata_manager.load_metadata(snapshot_path)
            
            # Phase 3: Create backup if requested
            backup_path = None
            if options.backup_before_restore:
                backup_tracker = await progress_tracker.start_phase(
                    OperationPhase.CREATING_SCHEMA_DUMP, 100, "Creating backup before restore"
                )
                
                backup_name = f"{name}_backup_{int(time.time())}"
                backup_options = SnapshotCreateOptions(
                    name=backup_name,
                    description=f"Automatic backup before restoring {name}",
                    atomic=False  # Skip atomic operation for backup
                )
                
                backup_info = await self.create_snapshot(backup_options)
                backup_path = backup_info.path
                
                await backup_tracker.update(100, "Backup created")
                await progress_tracker.complete_phase(OperationPhase.CREATING_SCHEMA_DUMP)
            
            # Phase 4: Restore snapshot
            restore_tracker = await progress_tracker.start_phase(
                OperationPhase.RESTORING, 100, "Restoring snapshot"
            )
            
            # Convert options and restore
            restore_opts = self._convert_to_restore_options(options)
            
            # Find main snapshot file (largest compressed file, typically data)
            main_file = max(
                (snapshot_path / f.name for f in snapshot_metadata.files),
                key=lambda p: p.stat().st_size if p.exists() else 0
            )
            
            # Create progress callback for adapter
            adapter_callback = SnapshotEngineProgressCallback(restore_tracker)
            
            restore_result = await self.adapter.restore_snapshot(
                main_file, restore_opts, adapter_callback
            )
            
            if not restore_result.success:
                raise SnapshotError(f"Database restore failed: {restore_result.error_message}")
            
            await progress_tracker.complete_phase(OperationPhase.RESTORING)
            
            # Phase 5: Finalize
            finalize_tracker = await progress_tracker.start_phase(
                OperationPhase.FINALIZING, 100, "Finalizing restore"
            )
            
            await finalize_tracker.update(100, "Restore finalized")
            await progress_tracker.complete_phase(OperationPhase.FINALIZING)
            
            # Create result snapshot info
            total_duration = time.time() - start_time
            snapshot_info = SnapshotInfo(
                name=name,
                path=snapshot_path,
                status=SnapshotStatus.COMPLETED,
                created_at=snapshot_metadata.created_at,
                size_bytes=snapshot_metadata.total_size_bytes,
                database_type=snapshot_metadata.database.type,
                database_version=snapshot_metadata.database.version,
                compression_ratio=snapshot_metadata.compression_ratio,
                table_count=snapshot_metadata.database.table_count,
                schema_count=snapshot_metadata.database.schema_count,
                tags=snapshot_metadata.tags,
                description=snapshot_metadata.description
            )
            
            logger.info(f"Snapshot restored successfully: {snapshot_info} (duration: {total_duration:.1f}s)")
            return snapshot_info
            
        except Exception as e:
            logger.error(f"Snapshot restore failed for {name}: {e}")
            
            # Update progress to failed state
            if progress_callback:
                failed_report = ProgressReport(
                    phase=OperationPhase.FAILED,
                    current=0,
                    total=100,
                    percentage=0,
                    message=f"Snapshot restore failed: {str(e)}"
                )
                try:
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(failed_report)
                    else:
                        progress_callback(failed_report)
                except Exception:
                    pass
            
            # Rollback to backup if available and restore failed
            if backup_path and backup_path.exists():
                logger.warning(f"Attempting to rollback to backup: {backup_path}")
                try:
                    rollback_options = SnapshotRestoreOptions(
                        backup_before_restore=False,
                        verify_integrity=False
                    )
                    await self.restore_snapshot(backup_path.name, rollback_options)
                    logger.info("Successfully rolled back to backup")
                except Exception as rollback_error:
                    logger.error(f"Rollback failed: {rollback_error}")
            
            if isinstance(e, (SnapshotError, ValidationError)):
                raise
            else:
                raise SnapshotError(f"Snapshot restore failed: {str(e)}")
        
        finally:
            await self.adapter.disconnect()
    
    async def validate_snapshot(self, name: str) -> ValidationResult:
        """
        Validate snapshot integrity and compatibility.
        
        Args:
            name: Snapshot name to validate
            
        Returns:
            ValidationResult with validation details
            
        Raises:
            StorageError: If snapshot files cannot be read
        """
        snapshot_path = self.storage_base_path / name
        
        if not snapshot_path.exists():
            return ValidationResult(
                valid=False,
                snapshot_path=snapshot_path,
                metadata_valid=False,
                files_valid=False,
                checksums_valid=False,
                compatibility_valid=False,
                total_files=0,
                valid_files=0,
                size_bytes=0,
                validation_time_seconds=0,
                error_message=f"Snapshot directory not found: {snapshot_path}"
            )
        
        start_time = time.time()
        
        try:
            # Load and validate metadata
            metadata = await self.metadata_manager.load_metadata(snapshot_path)
            metadata_valid = True
            
            # Validate metadata against actual files
            validation_warnings = await self.metadata_manager.validate_metadata(metadata, snapshot_path)
            
            # Check file existence and integrity
            total_files = len(metadata.files)
            valid_files = 0
            corrupted_files = []
            missing_files = []
            
            total_size = 0
            
            for file_meta in metadata.files:
                file_path = snapshot_path / file_meta.name
                
                if not file_path.exists():
                    missing_files.append(file_meta.name)
                    continue
                
                file_size = file_path.stat().st_size
                total_size += file_size
                
                # Verify file size
                if file_size != file_meta.size_bytes:
                    corrupted_files.append(file_meta.name)
                    continue
                
                # Verify checksum if available
                if file_meta.checksum:
                    actual_checksum = await self.metadata_manager._calculate_file_checksum(file_path)
                    if actual_checksum != file_meta.checksum:
                        corrupted_files.append(file_meta.name)
                        continue
                
                valid_files += 1
            
            # Determine validation results
            files_valid = len(corrupted_files) == 0 and len(missing_files) == 0
            checksums_valid = len(corrupted_files) == 0
            compatibility_valid = len(validation_warnings) == 0
            overall_valid = metadata_valid and files_valid and checksums_valid
            
            validation_time = time.time() - start_time
            
            error_message = None
            if not overall_valid:
                error_parts = []
                if not metadata_valid:
                    error_parts.append("invalid metadata")
                if missing_files:
                    error_parts.append(f"missing files: {', '.join(missing_files)}")
                if corrupted_files:
                    error_parts.append(f"corrupted files: {', '.join(corrupted_files)}")
                error_message = "; ".join(error_parts)
            
            result = ValidationResult(
                valid=overall_valid,
                snapshot_path=snapshot_path,
                metadata_valid=metadata_valid,
                files_valid=files_valid,
                checksums_valid=checksums_valid,
                compatibility_valid=compatibility_valid,
                total_files=total_files,
                valid_files=valid_files,
                corrupted_files=corrupted_files,
                missing_files=missing_files,
                metadata=metadata,
                size_bytes=total_size,
                validation_time_seconds=validation_time,
                error_message=error_message,
                warnings=validation_warnings
            )
            
            logger.info(f"Snapshot validation completed: {result}")
            return result
            
        except Exception as e:
            validation_time = time.time() - start_time
            return ValidationResult(
                valid=False,
                snapshot_path=snapshot_path,
                metadata_valid=False,
                files_valid=False,
                checksums_valid=False,
                compatibility_valid=False,
                total_files=0,
                valid_files=0,
                size_bytes=0,
                validation_time_seconds=validation_time,
                error_message=f"Validation error: {str(e)}"
            )
    
    async def get_snapshot_info(self, name: str) -> SnapshotInfo:
        """
        Get detailed snapshot metadata and statistics.
        
        Args:
            name: Snapshot name
            
        Returns:
            SnapshotInfo with comprehensive snapshot information
            
        Raises:
            SnapshotError: If snapshot not found or cannot be read
        """
        snapshot_path = self.storage_base_path / name
        
        if not snapshot_path.exists():
            raise SnapshotError(f"Snapshot not found: {name}")
        
        try:
            metadata = await self.metadata_manager.load_metadata(snapshot_path)
            
            return SnapshotInfo(
                name=name,
                path=snapshot_path,
                status=SnapshotStatus.COMPLETED,  # Assume completed if metadata loads
                created_at=metadata.created_at,
                size_bytes=metadata.total_size_bytes,
                database_type=metadata.database.type,
                database_version=metadata.database.version,
                compression_ratio=metadata.compression_ratio,
                table_count=metadata.database.table_count,
                schema_count=metadata.database.schema_count,
                tags=metadata.tags,
                description=metadata.description
            )
            
        except Exception as e:
            raise SnapshotError(f"Failed to get snapshot info: {str(e)}")
    
    async def list_snapshots(self) -> List[SnapshotInfo]:
        """
        List all available snapshots.
        
        Returns:
            List of SnapshotInfo objects for all snapshots
        """
        snapshots = []
        
        if not self.storage_base_path.exists():
            return snapshots
        
        for snapshot_dir in self.storage_base_path.iterdir():
            if snapshot_dir.is_dir():
                try:
                    snapshot_info = await self.get_snapshot_info(snapshot_dir.name)
                    snapshots.append(snapshot_info)
                except Exception as e:
                    logger.warning(f"Failed to load snapshot {snapshot_dir.name}: {e}")
        
        # Sort by creation time, newest first
        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        return snapshots
    
    # Helper methods
    
    async def _validate_create_options(self, options: SnapshotCreateOptions, snapshot_path: Path) -> None:
        """Validate snapshot creation options."""
        if snapshot_path.exists() and not options.atomic:
            raise ValidationError(f"Snapshot already exists: {options.name}")
        
        if options.compression not in self.compression_engine.get_supported_types():
            raise ValidationError(f"Unsupported compression type: {options.compression}")
        
        if options.schema_only and options.data_only:
            raise ValidationError("Cannot specify both schema_only and data_only")
    
    def _convert_to_snapshot_options(self, options: SnapshotCreateOptions) -> SnapshotOptions:
        """Convert engine options to database adapter options."""
        from ..database.models import CompressionType as AdapterCompressionType
        
        # Map compression types
        compression_map = {
            CompressionType.NONE: AdapterCompressionType.NONE,
            CompressionType.GZIP: AdapterCompressionType.GZIP,
        }
        
        return SnapshotOptions(
            compression=compression_map.get(options.compression, AdapterCompressionType.GZIP),
            compression_level=options.compression_level,
            parallel_jobs=options.parallel_jobs,
            include_schemas=options.include_schemas,
            exclude_schemas=options.exclude_schemas,
            include_tables=options.include_tables,
            exclude_tables=options.exclude_tables,
            data_only=options.data_only,
            schema_only=options.schema_only,
            include_large_objects=options.include_large_objects,
            verbose=False
        )
    
    def _convert_to_restore_options(self, options: SnapshotRestoreOptions) -> RestoreOptions:
        """Convert engine options to database adapter options.""" 
        return RestoreOptions(
            parallel_jobs=options.parallel_jobs,
            clean=options.clean_before_restore,
            create=options.create_database,
            if_exists=options.if_exists,
            disable_triggers=options.disable_triggers,
            single_transaction=options.single_transaction,
            no_owner=options.no_owner,
            no_privileges=options.no_privileges,
            include_schemas=options.include_schemas,
            exclude_schemas=options.exclude_schemas,
            include_tables=options.include_tables,
            exclude_tables=options.exclude_tables,
            verbose=False
        )
    
    async def _create_schema_dump(
        self,
        output_dir: Path,
        options: SnapshotOptions,
        progress_tracker: ProgressTracker
    ) -> Path:
        """Create schema dump file."""
        schema_file = output_dir / "schema.sql"
        
        # Create schema-only options
        schema_options = SnapshotOptions(
            **options.dict(),
            schema_only=True,
            data_only=False
        )
        
        # Create progress callback
        callback = SnapshotEngineProgressCallback(progress_tracker)
        
        # Create schema dump
        result = await self.adapter.create_snapshot(schema_file, schema_options, callback)
        
        if not result.success:
            raise SnapshotError(f"Schema dump failed: {result.error_message}")
        
        return schema_file
    
    async def _create_data_dump(
        self,
        output_dir: Path,
        options: SnapshotOptions,
        progress_tracker: ProgressTracker
    ) -> Path:
        """Create data dump file."""
        data_file = output_dir / "data.sql"
        
        # Create data-only options
        data_options = SnapshotOptions(
            **options.dict(),
            schema_only=False,
            data_only=True
        )
        
        # Create progress callback
        callback = SnapshotEngineProgressCallback(progress_tracker)
        
        # Create data dump
        result = await self.adapter.create_snapshot(data_file, data_options, callback)
        
        if not result.success:
            raise SnapshotError(f"Data dump failed: {result.error_message}")
        
        return data_file
    
    async def _compress_snapshot_files(
        self,
        snapshot_dir: Path,
        files_to_compress: List[Path],
        options: SnapshotCreateOptions,
        progress_tracker: ProgressTracker
    ) -> List[Path]:
        """Compress snapshot files and return list of compressed files."""
        compressed_files = []
        total_files = len(files_to_compress)
        
        for i, file_path in enumerate(files_to_compress):
            if not file_path.exists():
                continue
            
            progress_message = f"Compressing {file_path.name} ({i+1}/{total_files})"
            await progress_tracker.update(
                int((i / total_files) * 100),
                progress_message
            )
            
            if options.compression == CompressionType.NONE:
                # No compression - keep original file
                compressed_files.append(file_path)
            else:
                # Compress file
                compressed_file = file_path.with_suffix(file_path.suffix + '.gz')
                
                await self.compression_engine.compress_file(
                    file_path,
                    compressed_file,
                    options.compression,
                    options.compression_level,
                    verify_integrity=options.verify_integrity
                )
                
                # Remove original uncompressed file
                file_path.unlink()
                compressed_files.append(compressed_file)
        
        await progress_tracker.update(100, f"Compression completed ({len(compressed_files)} files)")
        return compressed_files