"""Data models for snapshot engine operations."""

import hashlib
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from pydantic import BaseModel, Field, ConfigDict


class SnapshotStatus(str, Enum):
    """Snapshot status enumeration."""
    CREATING = "creating"
    COMPLETED = "completed"
    FAILED = "failed"
    VALIDATING = "validating"
    RESTORING = "restoring"


class CompressionType(str, Enum):
    """Supported compression types."""
    NONE = "none"
    GZIP = "gzip"
    LZ4 = "lz4"
    ZSTD = "zstd"


class OperationPhase(str, Enum):
    """Phases of snapshot operations."""
    INITIALIZING = "initializing"
    COLLECTING_METADATA = "collecting_metadata"
    CREATING_SCHEMA_DUMP = "creating_schema_dump"
    CREATING_DATA_DUMP = "creating_data_dump"
    COMPRESSING = "compressing"
    VALIDATING = "validating"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class SnapshotCreateOptions(BaseModel):
    """Options for creating database snapshots."""
    
    name: str = Field(description="Snapshot name")
    description: Optional[str] = Field(default=None, description="Snapshot description")
    tags: List[str] = Field(default_factory=list, description="Snapshot tags")
    compression: CompressionType = Field(default=CompressionType.GZIP, description="Compression type")
    compression_level: int = Field(default=6, ge=1, le=9, description="Compression level (1-9)")
    parallel_jobs: int = Field(default=1, ge=1, le=16, description="Number of parallel jobs")
    include_schemas: Optional[Set[str]] = Field(default=None, description="Schemas to include")
    exclude_schemas: Optional[Set[str]] = Field(default=None, description="Schemas to exclude") 
    include_tables: Optional[Set[str]] = Field(default=None, description="Tables to include")
    exclude_tables: Optional[Set[str]] = Field(default=None, description="Tables to exclude")
    data_only: bool = Field(default=False, description="Include data only, no schema")
    schema_only: bool = Field(default=False, description="Include schema only, no data")
    include_large_objects: bool = Field(default=True, description="Include large objects")
    verify_integrity: bool = Field(default=True, description="Verify snapshot integrity after creation")
    atomic: bool = Field(default=True, description="Ensure atomic operation with rollback on failure")
    
    model_config = ConfigDict(use_enum_values=True)


class SnapshotRestoreOptions(BaseModel):
    """Options for restoring database snapshots."""
    
    clean_before_restore: bool = Field(default=False, description="Clean database before restore")
    create_database: bool = Field(default=False, description="Create database if not exists")
    if_exists: str = Field(default="fail", pattern="^(fail|replace|append)$", description="Action if database exists")
    parallel_jobs: int = Field(default=1, ge=1, le=16, description="Number of parallel jobs")
    disable_triggers: bool = Field(default=False, description="Disable triggers during restore")
    single_transaction: bool = Field(default=True, description="Restore in single transaction") 
    no_owner: bool = Field(default=True, description="Skip ownership commands")
    no_privileges: bool = Field(default=True, description="Skip privilege commands")
    include_schemas: Optional[Set[str]] = Field(default=None, description="Schemas to restore")
    exclude_schemas: Optional[Set[str]] = Field(default=None, description="Schemas to exclude")
    include_tables: Optional[Set[str]] = Field(default=None, description="Tables to restore")
    exclude_tables: Optional[Set[str]] = Field(default=None, description="Tables to exclude")
    verify_integrity: bool = Field(default=True, description="Verify snapshot integrity before restore")
    atomic: bool = Field(default=True, description="Ensure atomic restore with rollback on failure")
    backup_before_restore: bool = Field(default=True, description="Create backup before restore")


class FileMetadata(BaseModel):
    """Metadata for individual snapshot files."""
    
    name: str = Field(description="File name")
    size_bytes: int = Field(description="File size in bytes")
    checksum: str = Field(description="SHA256 checksum")
    compression: CompressionType = Field(description="Compression used")
    compression_ratio: Optional[float] = Field(default=None, description="Compression ratio")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")


class DatabaseMetadata(BaseModel):
    """Database metadata in snapshot."""
    
    type: str = Field(description="Database type (postgresql, mysql, sqlite)")
    version: str = Field(description="Database version")
    size_bytes: int = Field(description="Database size in bytes")
    table_count: int = Field(description="Number of tables")
    schema_count: int = Field(description="Number of schemas")
    schema_checksum: str = Field(description="Schema structure checksum")
    encoding: str = Field(description="Database encoding")
    collation: str = Field(description="Database collation")
    timezone: str = Field(description="Database timezone")
    extensions: List[str] = Field(default_factory=list, description="Installed extensions")


class CompatibilityInfo(BaseModel):
    """Snapshot compatibility information."""
    
    min_database_version: str = Field(description="Minimum supported database version")
    requires_extensions: List[str] = Field(default_factory=list, description="Required extensions")
    schema_changes: List[str] = Field(default_factory=list, description="Notable schema changes")
    warnings: List[str] = Field(default_factory=list, description="Compatibility warnings")


class SnapshotMetadata(BaseModel):
    """Complete snapshot metadata."""
    
    version: str = Field(default="1.0", description="Metadata schema version")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    name: str = Field(description="Snapshot name")
    description: Optional[str] = Field(default=None, description="Snapshot description")
    tags: List[str] = Field(default_factory=list, description="Snapshot tags")
    
    database: DatabaseMetadata = Field(description="Database metadata")
    
    # Snapshot details
    compression: CompressionType = Field(description="Compression type used")
    compression_level: int = Field(description="Compression level used")
    total_size_bytes: int = Field(description="Total snapshot size")
    files: List[FileMetadata] = Field(description="Snapshot file metadata")
    
    # Compatibility and validation
    compatibility: CompatibilityInfo = Field(description="Compatibility information")
    integrity_verified: bool = Field(default=False, description="Whether integrity was verified")
    
    # Performance metrics
    creation_duration_seconds: float = Field(description="Time taken to create snapshot")
    compression_ratio: float = Field(description="Overall compression ratio")
    
    model_config = ConfigDict(use_enum_values=True)
    
    def calculate_checksum(self) -> str:
        """Calculate checksum of metadata for integrity verification."""
        # Create a deterministic representation excluding dynamic fields
        data = {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "database": self.database.dict(),
            "files": [f.dict() for f in self.files],
        }
        
        import json
        json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()


class CompressionMetrics(BaseModel):
    """Compression performance metrics."""
    
    original_size_bytes: int = Field(description="Original file size")
    compressed_size_bytes: int = Field(description="Compressed file size")
    compression_ratio: float = Field(description="Compression ratio (original/compressed)")
    compression_time_seconds: float = Field(description="Time taken to compress")
    compression_speed_mbps: float = Field(description="Compression speed in MB/s")


class ProgressReport(BaseModel):
    """Progress reporting for long-running operations."""
    
    phase: OperationPhase = Field(description="Current operation phase")
    current: int = Field(description="Current progress value")
    total: int = Field(description="Total expected value")
    percentage: float = Field(description="Progress percentage (0-100)")
    message: str = Field(default="", description="Progress message")
    stage: str = Field(default="", description="Current stage description")
    eta_seconds: Optional[float] = Field(default=None, description="Estimated time to completion")
    speed_mbps: Optional[float] = Field(default=None, description="Current processing speed MB/s")
    
    def __str__(self) -> str:
        """String representation of progress."""
        eta_str = f", ETA: {self.eta_seconds:.1f}s" if self.eta_seconds else ""
        speed_str = f", {self.speed_mbps:.1f} MB/s" if self.speed_mbps else ""
        return f"{self.phase.value}: {self.percentage:.1f}% - {self.message}{eta_str}{speed_str}"


class AtomicOperationContext(BaseModel):
    """Context for atomic operations with rollback capability."""
    
    operation_id: str = Field(description="Unique operation identifier")
    temp_dir: Path = Field(description="Temporary directory for operation")
    target_path: Path = Field(description="Final target path")
    backup_path: Optional[Path] = Field(default=None, description="Backup path for rollback")
    cleanup_paths: List[Path] = Field(default_factory=list, description="Paths to clean up")
    created_files: List[Path] = Field(default_factory=list, description="Files created during operation")
    checkpoints: List[str] = Field(default_factory=list, description="Operation checkpoints")
    
    model_config = ConfigDict(arbitrary_types_allowed=True)


class SnapshotInfo(BaseModel):
    """High-level snapshot information."""
    
    name: str = Field(description="Snapshot name")
    path: Path = Field(description="Snapshot directory path")
    status: SnapshotStatus = Field(description="Current snapshot status")
    created_at: datetime = Field(description="Creation timestamp")
    size_bytes: int = Field(description="Total snapshot size")
    database_type: str = Field(description="Database type")
    database_version: str = Field(description="Database version")
    compression_ratio: float = Field(description="Compression ratio")
    table_count: int = Field(description="Number of tables")
    schema_count: int = Field(description="Number of schemas")
    tags: List[str] = Field(default_factory=list, description="Snapshot tags")
    description: Optional[str] = Field(default=None, description="Snapshot description")
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def __str__(self) -> str:
        """String representation of snapshot info."""
        size_mb = self.size_bytes / (1024 * 1024)
        return f"Snapshot {self.name}: {size_mb:.1f} MB, {self.table_count} tables ({self.status.value})"


class ValidationResult(BaseModel):
    """Result of snapshot validation."""
    
    valid: bool = Field(description="Whether snapshot is valid")
    snapshot_path: Path = Field(description="Path to validated snapshot")
    metadata_valid: bool = Field(description="Whether metadata is valid")
    files_valid: bool = Field(description="Whether all files are valid")
    checksums_valid: bool = Field(description="Whether checksums are valid")
    compatibility_valid: bool = Field(description="Whether snapshot is compatible")
    
    # Detailed validation info
    total_files: int = Field(description="Total number of files checked")
    valid_files: int = Field(description="Number of valid files")
    corrupted_files: List[str] = Field(default_factory=list, description="List of corrupted files")
    missing_files: List[str] = Field(default_factory=list, description="List of missing files")
    
    # Metadata extracted during validation
    metadata: Optional[SnapshotMetadata] = Field(default=None, description="Snapshot metadata")
    
    # Validation results
    size_bytes: int = Field(description="Total validated size")
    validation_time_seconds: float = Field(description="Time taken to validate")
    
    # Errors and warnings
    error_message: Optional[str] = Field(default=None, description="Error message if invalid")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def __str__(self) -> str:
        """String representation of validation result."""
        if self.valid:
            size_mb = self.size_bytes / (1024 * 1024)
            return f"Snapshot valid: {self.snapshot_path} ({size_mb:.1f} MB, {self.total_files} files)"
        else:
            return f"Snapshot invalid: {self.error_message}"