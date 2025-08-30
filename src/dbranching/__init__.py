"""DBranching - Database branching and snapshot management tool."""

__version__ = "0.1.0"
__author__ = "fish895623"
__email__ = "dan990429@gmail.com"

from .config import Config, ConfigManager
from .database import DatabaseAdapter, PostgreSQLAdapter
from .exceptions import (
    ConfigurationError,
    DatabaseAdapterError,
    DatabaseConnectionError,
    DatabaseTimeoutError,
    DBranchingError,
    SnapshotError,
    StorageError,
    ValidationError,
)

__all__ = [
    "Config",
    "ConfigManager",
    "DatabaseAdapter",
    "PostgreSQLAdapter",
    "DBranchingError",
    "ConfigurationError",
    "DatabaseAdapterError",
    "DatabaseConnectionError",
    "DatabaseTimeoutError",
    "SnapshotError",
    "StorageError",
    "ValidationError",
]
