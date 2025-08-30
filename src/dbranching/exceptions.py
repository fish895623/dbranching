"""Custom exceptions for dbranching application."""

from typing import Optional


class DBranchingError(Exception):
    """Base exception for all dbranching errors."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ConfigurationError(DBranchingError):
    """Raised when there's an error with configuration."""

    def __init__(self, message: str, config_path: Optional[str] = None) -> None:
        self.config_path = config_path
        if config_path:
            message = f"Configuration error in {config_path}: {message}"
        super().__init__(message, exit_code=2)


class DatabaseConnectionError(DBranchingError):
    """Raised when database connection fails."""

    def __init__(self, message: str, database_url: Optional[str] = None) -> None:
        self.database_url = database_url
        if database_url:
            message = f"Database connection error ({database_url}): {message}"
        super().__init__(message, exit_code=3)


class SnapshotError(DBranchingError):
    """Raised when snapshot operations fail."""

    def __init__(self, message: str, snapshot_name: Optional[str] = None) -> None:
        self.snapshot_name = snapshot_name
        if snapshot_name:
            message = f"Snapshot error ({snapshot_name}): {message}"
        super().__init__(message, exit_code=4)


class ValidationError(DBranchingError):
    """Raised when validation fails."""

    def __init__(self, message: str, field: Optional[str] = None) -> None:
        self.field = field
        if field:
            message = f"Validation error for {field}: {message}"
        super().__init__(message, exit_code=5)


class StorageError(DBranchingError):
    """Raised when storage operations fail."""

    def __init__(self, message: str, path: Optional[str] = None) -> None:
        self.path = path
        if path:
            message = f"Storage error ({path}): {message}"
        super().__init__(message, exit_code=6)
