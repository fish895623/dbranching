"""Data models for database operations."""

import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from pydantic import BaseModel, ConfigDict, Field


class CompressionType(str, Enum):
    """Supported compression types for snapshots."""

    NONE = "none"
    GZIP = "gzip"
    LZ4 = "lz4"
    ZSTD = "zstd"


class SnapshotFormat(str, Enum):
    """Supported snapshot formats."""

    CUSTOM = "custom"
    TAR = "tar"
    PLAIN = "plain"
    DIRECTORY = "directory"


class SnapshotOptions(BaseModel):
    """Options for creating database snapshots."""

    format: SnapshotFormat = Field(
        default=SnapshotFormat.CUSTOM, description="Snapshot format"
    )
    compression: CompressionType = Field(
        default=CompressionType.GZIP, description="Compression type"
    )
    compression_level: int = Field(
        default=6, ge=0, le=9, description="Compression level (0-9)"
    )
    parallel_jobs: int = Field(
        default=1, ge=1, le=16, description="Number of parallel jobs for dump"
    )
    include_schemas: Optional[Set[str]] = Field(
        default=None, description="Schemas to include (all if None)"
    )
    exclude_schemas: Optional[Set[str]] = Field(
        default=None, description="Schemas to exclude"
    )
    include_tables: Optional[Set[str]] = Field(
        default=None, description="Tables to include (all if None)"
    )
    exclude_tables: Optional[Set[str]] = Field(
        default=None, description="Tables to exclude"
    )
    data_only: bool = Field(default=False, description="Include data only, no schema")
    schema_only: bool = Field(default=False, description="Include schema only, no data")
    include_large_objects: bool = Field(
        default=True, description="Include large objects"
    )
    verbose: bool = Field(default=False, description="Enable verbose output")

    model_config = ConfigDict(use_enum_values=True)


class RestoreOptions(BaseModel):
    """Options for restoring database snapshots."""

    parallel_jobs: int = Field(
        default=1, ge=1, le=16, description="Number of parallel jobs for restore"
    )
    clean: bool = Field(default=False, description="Clean database before restore")
    create: bool = Field(default=False, description="Create database if not exists")
    if_exists: str = Field(
        default="fail",
        pattern="^(fail|replace|append)$",
        description="Action if database exists",
    )
    disable_triggers: bool = Field(
        default=False, description="Disable triggers during restore"
    )
    single_transaction: bool = Field(
        default=False, description="Restore in single transaction"
    )
    no_owner: bool = Field(default=False, description="Skip ownership commands")
    no_privileges: bool = Field(default=False, description="Skip privilege commands")
    include_schemas: Optional[Set[str]] = Field(
        default=None, description="Schemas to restore (all if None)"
    )
    exclude_schemas: Optional[Set[str]] = Field(
        default=None, description="Schemas to exclude from restore"
    )
    include_tables: Optional[Set[str]] = Field(
        default=None, description="Tables to restore (all if None)"
    )
    exclude_tables: Optional[Set[str]] = Field(
        default=None, description="Tables to exclude from restore"
    )
    verbose: bool = Field(default=False, description="Enable verbose output")


class SnapshotResult(BaseModel):
    """Result of snapshot operation."""

    success: bool = Field(description="Whether snapshot was successful")
    snapshot_path: Path = Field(description="Path to created snapshot")
    size_bytes: int = Field(description="Size of snapshot in bytes")
    compressed_size_bytes: Optional[int] = Field(
        default=None, description="Compressed size if compression was used"
    )
    duration_seconds: float = Field(description="Time taken to create snapshot")
    database_size_bytes: int = Field(description="Original database size")
    tables_included: int = Field(description="Number of tables included")
    schemas_included: int = Field(description="Number of schemas included")
    compression_ratio: Optional[float] = Field(
        default=None, description="Compression ratio if compression was used"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if failed"
    )
    warnings: List[str] = Field(default_factory=list, description="Warning messages")

    def __str__(self) -> str:
        """String representation of snapshot result."""
        if self.success:
            size_mb = self.size_bytes / (1024 * 1024)
            return f"Snapshot successful: {self.snapshot_path} ({size_mb:.1f} MB, {self.duration_seconds:.1f}s)"
        else:
            return f"Snapshot failed: {self.error_message}"


class RestoreResult(BaseModel):
    """Result of restore operation."""

    success: bool = Field(description="Whether restore was successful")
    snapshot_path: Path = Field(description="Path to restored snapshot")
    duration_seconds: float = Field(description="Time taken to restore snapshot")
    tables_restored: int = Field(description="Number of tables restored")
    schemas_restored: int = Field(description="Number of schemas restored")
    rows_processed: Optional[int] = Field(
        default=None, description="Number of rows processed"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if failed"
    )
    warnings: List[str] = Field(default_factory=list, description="Warning messages")

    def __str__(self) -> str:
        """String representation of restore result."""
        if self.success:
            return f"Restore successful: {self.tables_restored} tables in {self.duration_seconds:.1f}s"
        else:
            return f"Restore failed: {self.error_message}"


class DatabaseInfo(BaseModel):
    """Database information and metadata."""

    name: str = Field(description="Database name")
    version: str = Field(description="Database server version")
    size_bytes: int = Field(description="Total database size in bytes")
    table_count: int = Field(description="Number of tables")
    schema_count: int = Field(description="Number of schemas")
    connection_count: int = Field(description="Current connection count")
    encoding: str = Field(description="Database encoding")
    collation: str = Field(description="Database collation")
    timezone: str = Field(description="Database timezone")
    uptime_seconds: Optional[int] = Field(
        default=None, description="Server uptime in seconds"
    )
    schemas: List[str] = Field(default_factory=list, description="List of schema names")
    extensions: List[str] = Field(
        default_factory=list, description="Installed extensions"
    )
    settings: Dict[str, str] = Field(
        default_factory=dict, description="Important database settings"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    collected_at: datetime = Field(
        default_factory=datetime.now, description="When info was collected"
    )


class ValidationResult(BaseModel):
    """Result of snapshot validation."""

    valid: bool = Field(description="Whether snapshot is valid")
    snapshot_path: Path = Field(description="Path to validated snapshot")
    format_valid: bool = Field(description="Whether format is valid")
    size_bytes: int = Field(description="Snapshot file size")
    checksum: Optional[str] = Field(default=None, description="File checksum")
    database_version: Optional[str] = Field(
        default=None, description="Database version from snapshot"
    )
    created_at: Optional[datetime] = Field(
        default=None, description="When snapshot was created"
    )
    compatible: bool = Field(
        description="Whether snapshot is compatible with current database"
    )
    schema_count: Optional[int] = Field(
        default=None, description="Number of schemas in snapshot"
    )
    table_count: Optional[int] = Field(
        default=None, description="Number of tables in snapshot"
    )
    estimated_restore_time: Optional[float] = Field(
        default=None, description="Estimated restore time in seconds"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if invalid"
    )
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional validation metadata"
    )

    def __str__(self) -> str:
        """String representation of validation result."""
        if self.valid:
            size_mb = self.size_bytes / (1024 * 1024)
            return f"Snapshot valid: {self.snapshot_path} ({size_mb:.1f} MB)"
        else:
            return f"Snapshot invalid: {self.error_message}"


class ProgressCallback:
    """Callback for progress reporting during long-running operations."""

    def __init__(self) -> None:
        """Initialize progress callback."""
        self._cancelled = False
        self._lock = asyncio.Lock()

    async def update(
        self,
        current: int,
        total: int,
        message: str = "",
        stage: str = "",
    ) -> None:
        """
        Update progress.

        Args:
            current: Current progress value
            total: Total expected value
            message: Optional progress message
            stage: Current operation stage
        """
        pass  # Override in subclasses

    async def cancel(self) -> None:
        """Cancel the operation."""
        async with self._lock:
            self._cancelled = True

    async def is_cancelled(self) -> bool:
        """Check if operation was cancelled."""
        async with self._lock:
            return self._cancelled
