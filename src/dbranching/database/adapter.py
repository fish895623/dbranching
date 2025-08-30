"""Abstract base class for database adapters."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from .models import (
    DatabaseInfo,
    ProgressCallback,
    RestoreOptions,
    RestoreResult,
    SnapshotOptions,
    SnapshotResult,
    ValidationResult,
)


class DatabaseAdapter(ABC):
    """Abstract base class for database adapters."""

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish and validate database connection.

        Returns:
            True if connection successful, False otherwise

        Raises:
            DatabaseConnectionError: If connection fails with non-recoverable error
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close database connection and cleanup resources.

        This method should be idempotent and not raise exceptions.
        """
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Test database connection without establishing permanent connection.

        Returns:
            True if connection test successful, False otherwise
        """
        pass

    @abstractmethod
    async def create_snapshot(
        self,
        output_path: Path,
        options: Optional[SnapshotOptions] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> SnapshotResult:
        """
        Create database snapshot to specified path.

        Args:
            output_path: Path where snapshot should be created
            options: Snapshot options, uses defaults if None
            progress_callback: Optional callback for progress updates

        Returns:
            SnapshotResult with operation details

        Raises:
            SnapshotError: If snapshot creation fails
            StorageError: If output path is not writable
        """
        pass

    @abstractmethod
    async def restore_snapshot(
        self,
        snapshot_path: Path,
        options: Optional[RestoreOptions] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> RestoreResult:
        """
        Restore database from snapshot.

        Args:
            snapshot_path: Path to snapshot file
            options: Restore options, uses defaults if None
            progress_callback: Optional callback for progress updates

        Returns:
            RestoreResult with operation details

        Raises:
            SnapshotError: If restore fails
            ValidationError: If snapshot is invalid or incompatible
        """
        pass

    @abstractmethod
    async def get_database_info(self) -> DatabaseInfo:
        """
        Get database metadata and statistics.

        Returns:
            DatabaseInfo with comprehensive database information

        Raises:
            DatabaseConnectionError: If database query fails
        """
        pass

    @abstractmethod
    async def validate_snapshot(self, snapshot_path: Path) -> ValidationResult:
        """
        Validate snapshot integrity and compatibility.

        Args:
            snapshot_path: Path to snapshot file to validate

        Returns:
            ValidationResult with validation details

        Raises:
            StorageError: If snapshot file cannot be read
        """
        pass

    @abstractmethod
    async def get_supported_formats(self) -> set[str]:
        """
        Get supported snapshot formats for this adapter.

        Returns:
            Set of supported format names
        """
        pass

    @abstractmethod
    async def estimate_snapshot_size(
        self, options: Optional[SnapshotOptions] = None
    ) -> int:
        """
        Estimate the size of a snapshot before creating it.

        Args:
            options: Snapshot options to use for estimation

        Returns:
            Estimated snapshot size in bytes

        Raises:
            DatabaseConnectionError: If database query fails
        """
        pass

    @abstractmethod
    async def list_schemas(self) -> list[str]:
        """
        List all schemas in the database.

        Returns:
            List of schema names

        Raises:
            DatabaseConnectionError: If database query fails
        """
        pass

    @abstractmethod
    async def list_tables(self, schema: Optional[str] = None) -> list[str]:
        """
        List all tables in the database or specific schema.

        Args:
            schema: Schema name to filter by, all schemas if None

        Returns:
            List of table names (qualified with schema if schema is None)

        Raises:
            DatabaseConnectionError: If database query fails
        """
        pass

    async def __aenter__(self) -> "DatabaseAdapter":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
