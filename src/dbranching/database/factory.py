"""Database adapter factory and driver registration system."""

import logging
from typing import Dict, Type, Optional, Set

from ..config import DatabaseConfig
from ..exceptions import DatabaseAdapterError
from .adapter import DatabaseAdapter
from .postgresql import PostgreSQLAdapter
from .mysql import MySQLAdapter
from .sqlite import SQLiteAdapter

logger = logging.getLogger(__name__)


class DatabaseDriverRegistry:
    """Registry for database drivers and their capabilities."""
    
    def __init__(self) -> None:
        """Initialize the driver registry."""
        self._drivers: Dict[str, Type[DatabaseAdapter]] = {}
        self._capabilities: Dict[str, Dict[str, any]] = {}
        self._register_builtin_drivers()
    
    def _register_builtin_drivers(self) -> None:
        """Register built-in database drivers."""
        # PostgreSQL driver
        self.register_driver(
            name="postgresql",
            adapter_class=PostgreSQLAdapter,
            capabilities={
                "supports_schemas": True,
                "supports_transactions": True,
                "supports_parallel_dump": True,
                "supports_compression": True,
                "supported_formats": {"custom", "tar", "plain", "directory"},
                "default_port": 5432,
                "requires_credentials": True,
                "supports_ssl": True,
                "backup_tool": "pg_dump",
                "restore_tool": "pg_restore",
                "connection_pooling": True,
            }
        )
        
        # MySQL driver
        self.register_driver(
            name="mysql",
            adapter_class=MySQLAdapter,
            capabilities={
                "supports_schemas": False,  # MySQL uses databases, not schemas
                "supports_transactions": True,
                "supports_parallel_dump": False,
                "supports_compression": False,  # mysqldump doesn't have built-in compression
                "supported_formats": {"plain"},
                "default_port": 3306,
                "requires_credentials": True,
                "supports_ssl": True,
                "backup_tool": "mysqldump",
                "restore_tool": "mysql",
                "connection_pooling": True,
            }
        )
        
        # SQLite driver
        self.register_driver(
            name="sqlite",
            adapter_class=SQLiteAdapter,
            capabilities={
                "supports_schemas": True,  # SQLite supports attached databases
                "supports_transactions": True,
                "supports_parallel_dump": False,
                "supports_compression": True,  # We handle compression manually
                "supported_formats": {"custom", "plain"},
                "default_port": None,  # File-based, no network port
                "requires_credentials": False,
                "supports_ssl": False,  # File-based database
                "backup_tool": "file_copy",
                "restore_tool": "file_copy",
                "connection_pooling": False,  # SQLite handles this internally
            }
        )
    
    def register_driver(
        self, 
        name: str, 
        adapter_class: Type[DatabaseAdapter], 
        capabilities: Dict[str, any]
    ) -> None:
        """
        Register a database driver.
        
        Args:
            name: Driver name (e.g., 'postgresql', 'mysql', 'sqlite')
            adapter_class: Database adapter class
            capabilities: Driver capabilities dictionary
        """
        if not issubclass(adapter_class, DatabaseAdapter):
            raise DatabaseAdapterError(
                f"Adapter class must inherit from DatabaseAdapter", name
            )
        
        self._drivers[name] = adapter_class
        self._capabilities[name] = capabilities
        
        logger.info(f"Registered database driver: {name}")
    
    def unregister_driver(self, name: str) -> None:
        """
        Unregister a database driver.
        
        Args:
            name: Driver name to unregister
        """
        if name in self._drivers:
            del self._drivers[name]
            del self._capabilities[name]
            logger.info(f"Unregistered database driver: {name}")
    
    def get_driver_class(self, name: str) -> Type[DatabaseAdapter]:
        """
        Get database adapter class by driver name.
        
        Args:
            name: Driver name
            
        Returns:
            Database adapter class
            
        Raises:
            DatabaseAdapterError: If driver not found
        """
        if name not in self._drivers:
            available = ", ".join(self._drivers.keys())
            raise DatabaseAdapterError(
                f"Unknown database driver: {name}. Available drivers: {available}",
                name
            )
        
        return self._drivers[name]
    
    def get_driver_capabilities(self, name: str) -> Dict[str, any]:
        """
        Get driver capabilities.
        
        Args:
            name: Driver name
            
        Returns:
            Driver capabilities dictionary
            
        Raises:
            DatabaseAdapterError: If driver not found
        """
        if name not in self._capabilities:
            available = ", ".join(self._drivers.keys())
            raise DatabaseAdapterError(
                f"Unknown database driver: {name}. Available drivers: {available}",
                name
            )
        
        return self._capabilities[name].copy()
    
    def list_drivers(self) -> Set[str]:
        """
        List all registered driver names.
        
        Returns:
            Set of driver names
        """
        return set(self._drivers.keys())
    
    def is_driver_available(self, name: str) -> bool:
        """
        Check if driver is available.
        
        Args:
            name: Driver name
            
        Returns:
            True if driver is available
        """
        return name in self._drivers
    
    def get_drivers_by_capability(self, capability: str, value: any = True) -> Set[str]:
        """
        Get drivers that support a specific capability.
        
        Args:
            capability: Capability name
            value: Expected capability value (default: True)
            
        Returns:
            Set of driver names that support the capability
        """
        matching_drivers = set()
        
        for name, capabilities in self._capabilities.items():
            if capabilities.get(capability) == value:
                matching_drivers.add(name)
        
        return matching_drivers


class DatabaseFactory:
    """Factory for creating database adapters."""
    
    def __init__(self) -> None:
        """Initialize the database factory."""
        self.registry = DatabaseDriverRegistry()
    
    def create_adapter(self, config: DatabaseConfig) -> DatabaseAdapter:
        """
        Create database adapter from configuration.
        
        Args:
            config: Database configuration
            
        Returns:
            Database adapter instance
            
        Raises:
            DatabaseAdapterError: If driver not found or creation fails
        """
        try:
            adapter_class = self.registry.get_driver_class(config.driver)
            return adapter_class(config)
        except Exception as e:
            raise DatabaseAdapterError(
                f"Failed to create adapter for driver '{config.driver}': {str(e)}",
                config.driver
            )
    
    def create_adapter_from_url(self, database_url: str, **kwargs) -> DatabaseAdapter:
        """
        Create database adapter from connection URL.
        
        Args:
            database_url: Database connection URL
            **kwargs: Additional configuration parameters
            
        Returns:
            Database adapter instance
            
        Raises:
            DatabaseAdapterError: If URL parsing fails or driver not found
        """
        config = self.parse_database_url(database_url, **kwargs)
        return self.create_adapter(config)
    
    def parse_database_url(self, url: str, **kwargs) -> DatabaseConfig:
        """
        Parse database URL into configuration.
        
        Args:
            url: Database URL (e.g., postgresql://user:pass@host:port/db)
            **kwargs: Additional configuration parameters
            
        Returns:
            Database configuration
            
        Raises:
            DatabaseAdapterError: If URL format is invalid
        """
        try:
            from urllib.parse import urlparse
            
            parsed = urlparse(url)
            
            if not parsed.scheme:
                raise ValueError("Missing database driver in URL")
            
            # Map URL schemes to driver names
            scheme_mapping = {
                'postgres': 'postgresql',
                'postgresql': 'postgresql',
                'mysql': 'mysql',
                'mysql+pymysql': 'mysql',
                'sqlite': 'sqlite',
                'sqlite3': 'sqlite',
            }
            
            driver = scheme_mapping.get(parsed.scheme.lower())
            if not driver:
                raise ValueError(f"Unsupported database scheme: {parsed.scheme}")
            
            # Build configuration
            config_data = {
                "driver": driver,
                **kwargs  # Allow override via kwargs
            }
            
            # For SQLite, the path is in the URL path
            if driver == "sqlite":
                if parsed.path:
                    config_data["database"] = parsed.path.lstrip('/')
                else:
                    raise ValueError("SQLite URL must include database file path")
            else:
                # Network-based databases
                if parsed.hostname:
                    config_data["host"] = parsed.hostname
                
                if parsed.port:
                    config_data["port"] = parsed.port
                else:
                    # Use default port based on driver
                    capabilities = self.registry.get_driver_capabilities(driver)
                    if capabilities.get("default_port"):
                        config_data["port"] = capabilities["default_port"]
                
                if parsed.path and len(parsed.path) > 1:
                    config_data["database"] = parsed.path.lstrip('/')
                
                if parsed.username:
                    config_data["username"] = parsed.username
                
                if parsed.password:
                    config_data["password"] = parsed.password
            
            return DatabaseConfig(**config_data)
            
        except Exception as e:
            raise DatabaseAdapterError(f"Invalid database URL format: {str(e)}", url)
    
    def get_supported_drivers(self) -> Set[str]:
        """
        Get set of supported driver names.
        
        Returns:
            Set of driver names
        """
        return self.registry.list_drivers()
    
    def get_driver_info(self, driver_name: str) -> Dict[str, any]:
        """
        Get comprehensive information about a driver.
        
        Args:
            driver_name: Name of the driver
            
        Returns:
            Dictionary with driver information
            
        Raises:
            DatabaseAdapterError: If driver not found
        """
        if not self.registry.is_driver_available(driver_name):
            raise DatabaseAdapterError(f"Driver not found: {driver_name}", driver_name)
        
        capabilities = self.registry.get_driver_capabilities(driver_name)
        adapter_class = self.registry.get_driver_class(driver_name)
        
        return {
            "name": driver_name,
            "class": adapter_class.__name__,
            "module": adapter_class.__module__,
            "capabilities": capabilities,
            "available": True,
        }
    
    def validate_driver_compatibility(
        self, 
        driver_name: str, 
        required_capabilities: Dict[str, any]
    ) -> Dict[str, bool]:
        """
        Validate if driver supports required capabilities.
        
        Args:
            driver_name: Name of the driver
            required_capabilities: Dictionary of required capabilities
            
        Returns:
            Dictionary mapping capability names to support status
            
        Raises:
            DatabaseAdapterError: If driver not found
        """
        capabilities = self.registry.get_driver_capabilities(driver_name)
        compatibility = {}
        
        for capability, required_value in required_capabilities.items():
            actual_value = capabilities.get(capability)
            
            if isinstance(required_value, bool):
                compatibility[capability] = bool(actual_value) == required_value
            elif isinstance(required_value, set):
                if isinstance(actual_value, set):
                    compatibility[capability] = required_value.issubset(actual_value)
                else:
                    compatibility[capability] = False
            else:
                compatibility[capability] = actual_value == required_value
        
        return compatibility
    
    def recommend_driver(
        self, 
        requirements: Dict[str, any],
        exclude_drivers: Optional[Set[str]] = None
    ) -> Optional[str]:
        """
        Recommend best driver based on requirements.
        
        Args:
            requirements: Dictionary of requirements/preferences
            exclude_drivers: Set of drivers to exclude from consideration
            
        Returns:
            Recommended driver name, or None if no suitable driver found
        """
        exclude_drivers = exclude_drivers or set()
        available_drivers = self.registry.list_drivers() - exclude_drivers
        
        if not available_drivers:
            return None
        
        # Score drivers based on requirements
        driver_scores = {}
        
        for driver in available_drivers:
            capabilities = self.registry.get_driver_capabilities(driver)
            score = 0
            
            # Check required capabilities
            for req_key, req_value in requirements.items():
                if req_key in capabilities:
                    cap_value = capabilities[req_key]
                    
                    if isinstance(req_value, bool) and cap_value == req_value:
                        score += 10
                    elif isinstance(req_value, set) and isinstance(cap_value, set):
                        if req_value.issubset(cap_value):
                            score += 10
                        else:
                            score -= 5
                    elif cap_value == req_value:
                        score += 10
                    else:
                        score -= 5
            
            driver_scores[driver] = score
        
        # Return driver with highest score
        if driver_scores:
            return max(driver_scores.items(), key=lambda x: x[1])[0]
        
        return None


# Global factory instance
_factory = DatabaseFactory()


def create_adapter(config: DatabaseConfig) -> DatabaseAdapter:
    """
    Create database adapter from configuration.
    
    Args:
        config: Database configuration
        
    Returns:
        Database adapter instance
    """
    return _factory.create_adapter(config)


def create_adapter_from_url(database_url: str, **kwargs) -> DatabaseAdapter:
    """
    Create database adapter from connection URL.
    
    Args:
        database_url: Database connection URL
        **kwargs: Additional configuration parameters
        
    Returns:
        Database adapter instance
    """
    return _factory.create_adapter_from_url(database_url, **kwargs)


def get_supported_drivers() -> Set[str]:
    """
    Get set of supported driver names.
    
    Returns:
        Set of driver names
    """
    return _factory.get_supported_drivers()


def get_driver_info(driver_name: str) -> Dict[str, any]:
    """
    Get comprehensive information about a driver.
    
    Args:
        driver_name: Name of the driver
        
    Returns:
        Dictionary with driver information
    """
    return _factory.get_driver_info(driver_name)


def register_custom_driver(
    name: str, 
    adapter_class: Type[DatabaseAdapter], 
    capabilities: Dict[str, any]
) -> None:
    """
    Register a custom database driver.
    
    Args:
        name: Driver name
        adapter_class: Database adapter class
        capabilities: Driver capabilities
    """
    _factory.registry.register_driver(name, adapter_class, capabilities)