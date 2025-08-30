"""Database abstraction layer for dbranching application."""

from .adapter import DatabaseAdapter
from .models import (
    DatabaseInfo,
    RestoreOptions,
    RestoreResult,
    SnapshotOptions,
    SnapshotResult,
    ValidationResult,
)
from .postgresql import PostgreSQLAdapter

# Import other adapters only if dependencies are available
try:
    from .mysql import MySQLAdapter
    _MYSQL_AVAILABLE = True
except ImportError:
    MySQLAdapter = None
    _MYSQL_AVAILABLE = False

try:
    from .sqlite import SQLiteAdapter
    _SQLITE_AVAILABLE = True
except ImportError:
    SQLiteAdapter = None
    _SQLITE_AVAILABLE = False

try:
    from .factory import (
        create_adapter,
        create_adapter_from_url,
        get_driver_info,
        get_supported_drivers,
        register_custom_driver,
    )
    _FACTORY_AVAILABLE = True
except ImportError:
    _FACTORY_AVAILABLE = False

__all__ = [
    # Core classes
    "DatabaseAdapter",
    "DatabaseInfo",
    "RestoreOptions",
    "RestoreResult",
    "SnapshotOptions",
    "SnapshotResult",
    "ValidationResult",
    # Database adapters
    "PostgreSQLAdapter",
]

# Add optional components to exports if available
if _MYSQL_AVAILABLE:
    __all__.append("MySQLAdapter")

if _SQLITE_AVAILABLE:
    __all__.append("SQLiteAdapter")

if _FACTORY_AVAILABLE:
    __all__.extend([
        "create_adapter",
        "create_adapter_from_url",
        "get_driver_info",
        "get_supported_drivers",
        "register_custom_driver",
    ])
