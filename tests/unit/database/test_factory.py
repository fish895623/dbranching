"""Tests for database factory and driver registration system."""

import pytest
from unittest.mock import Mock, patch

from dbranching.config import DatabaseConfig
from dbranching.database.adapter import DatabaseAdapter
from dbranching.database.factory import (
    DatabaseDriverRegistry,
    DatabaseFactory,
    create_adapter,
    create_adapter_from_url,
    get_driver_info,
    get_supported_drivers,
    register_custom_driver,
)
from dbranching.database.mysql import MySQLAdapter
from dbranching.database.postgresql import PostgreSQLAdapter
from dbranching.database.sqlite import SQLiteAdapter
from dbranching.exceptions import DatabaseAdapterError


class TestDatabaseDriverRegistry:
    """Test database driver registry functionality."""
    
    def test_registry_initialization(self):
        """Test registry initializes with built-in drivers."""
        registry = DatabaseDriverRegistry()
        
        drivers = registry.list_drivers()
        assert "postgresql" in drivers
        assert "mysql" in drivers
        assert "sqlite" in drivers
        assert len(drivers) == 3
    
    def test_get_driver_class(self):
        """Test getting driver class by name."""
        registry = DatabaseDriverRegistry()
        
        assert registry.get_driver_class("postgresql") == PostgreSQLAdapter
        assert registry.get_driver_class("mysql") == MySQLAdapter
        assert registry.get_driver_class("sqlite") == SQLiteAdapter
    
    def test_get_driver_class_unknown(self):
        """Test getting unknown driver raises error."""
        registry = DatabaseDriverRegistry()
        
        with pytest.raises(DatabaseAdapterError) as exc_info:
            registry.get_driver_class("unknown")
        
        assert "Unknown database driver: unknown" in str(exc_info.value)
        assert "Available drivers:" in str(exc_info.value)
    
    def test_get_driver_capabilities(self):
        """Test getting driver capabilities."""
        registry = DatabaseDriverRegistry()
        
        # Test PostgreSQL capabilities
        pg_caps = registry.get_driver_capabilities("postgresql")
        assert pg_caps["supports_schemas"] is True
        assert pg_caps["supports_transactions"] is True
        assert pg_caps["supports_parallel_dump"] is True
        assert pg_caps["default_port"] == 5432
        assert pg_caps["requires_credentials"] is True
        assert pg_caps["supports_ssl"] is True
        assert "custom" in pg_caps["supported_formats"]
        
        # Test MySQL capabilities
        mysql_caps = registry.get_driver_capabilities("mysql")
        assert mysql_caps["supports_schemas"] is False
        assert mysql_caps["supports_parallel_dump"] is False
        assert mysql_caps["default_port"] == 3306
        assert mysql_caps["supported_formats"] == {"plain"}
        
        # Test SQLite capabilities
        sqlite_caps = registry.get_driver_capabilities("sqlite")
        assert sqlite_caps["supports_schemas"] is True
        assert sqlite_caps["default_port"] is None
        assert sqlite_caps["requires_credentials"] is False
        assert sqlite_caps["supports_ssl"] is False
        assert sqlite_caps["connection_pooling"] is False
    
    def test_register_custom_driver(self):
        """Test registering custom driver."""
        class CustomAdapter(DatabaseAdapter):
            def __init__(self, config):
                self.config = config
            
            async def connect(self):
                return True
            
            async def disconnect(self):
                pass
            
            async def test_connection(self):
                return True
            
            async def create_snapshot(self, output_path, options=None, progress_callback=None):
                pass
            
            async def restore_snapshot(self, snapshot_path, options=None, progress_callback=None):
                pass
            
            async def get_database_info(self):
                pass
            
            async def validate_snapshot(self, snapshot_path):
                pass
            
            async def get_supported_formats(self):
                return {"custom"}
            
            async def estimate_snapshot_size(self, options=None):
                return 1000
            
            async def list_schemas(self):
                return []
            
            async def list_tables(self, schema=None):
                return []
        
        registry = DatabaseDriverRegistry()
        
        capabilities = {
            "supports_schemas": True,
            "default_port": 9999,
            "custom_feature": "enabled"
        }
        
        registry.register_driver("custom", CustomAdapter, capabilities)
        
        assert "custom" in registry.list_drivers()
        assert registry.get_driver_class("custom") == CustomAdapter
        assert registry.get_driver_capabilities("custom") == capabilities
    
    def test_register_invalid_adapter(self):
        """Test registering invalid adapter class raises error."""
        registry = DatabaseDriverRegistry()
        
        class NotAnAdapter:
            pass
        
        with pytest.raises(DatabaseAdapterError) as exc_info:
            registry.register_driver("invalid", NotAnAdapter, {})
        
        assert "Adapter class must inherit from DatabaseAdapter" in str(exc_info.value)
    
    def test_unregister_driver(self):
        """Test unregistering driver."""
        registry = DatabaseDriverRegistry()
        
        assert "postgresql" in registry.list_drivers()
        registry.unregister_driver("postgresql")
        assert "postgresql" not in registry.list_drivers()
    
    def test_is_driver_available(self):
        """Test checking if driver is available."""
        registry = DatabaseDriverRegistry()
        
        assert registry.is_driver_available("postgresql") is True
        assert registry.is_driver_available("mysql") is True
        assert registry.is_driver_available("sqlite") is True
        assert registry.is_driver_available("unknown") is False
    
    def test_get_drivers_by_capability(self):
        """Test getting drivers by capability."""
        registry = DatabaseDriverRegistry()
        
        # Test boolean capability
        pooling_drivers = registry.get_drivers_by_capability("connection_pooling", True)
        assert "postgresql" in pooling_drivers
        assert "mysql" in pooling_drivers
        assert "sqlite" not in pooling_drivers
        
        # Test set capability
        custom_format_drivers = registry.get_drivers_by_capability(
            "supported_formats", {"custom"}
        )
        assert "postgresql" in custom_format_drivers
        assert "sqlite" in custom_format_drivers
        assert "mysql" not in custom_format_drivers
        
        # Test value capability
        postgres_port_drivers = registry.get_drivers_by_capability("default_port", 5432)
        assert "postgresql" in postgres_port_drivers
        assert len(postgres_port_drivers) == 1


class TestDatabaseFactory:
    """Test database factory functionality."""
    
    def test_create_adapter_postgresql(self):
        """Test creating PostgreSQL adapter."""
        factory = DatabaseFactory()
        
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            database="testdb"
        )
        
        adapter = factory.create_adapter(config)
        
        assert isinstance(adapter, PostgreSQLAdapter)
        assert adapter.config == config
    
    def test_create_adapter_mysql(self):
        """Test creating MySQL adapter."""
        factory = DatabaseFactory()
        
        config = DatabaseConfig(
            driver="mysql",
            host="localhost",
            database="testdb"
        )
        
        adapter = factory.create_adapter(config)
        
        assert isinstance(adapter, MySQLAdapter)
        assert adapter.config == config
    
    def test_create_adapter_sqlite(self):
        """Test creating SQLite adapter."""
        factory = DatabaseFactory()
        
        config = DatabaseConfig(
            driver="sqlite",
            database="/tmp/test.db"
        )
        
        adapter = factory.create_adapter(config)
        
        assert isinstance(adapter, SQLiteAdapter)
        assert adapter.config == config
    
    def test_create_adapter_unknown_driver(self):
        """Test creating adapter with unknown driver raises error."""
        factory = DatabaseFactory()
        
        config = DatabaseConfig(driver="unknown", database="test")
        
        with pytest.raises(DatabaseAdapterError) as exc_info:
            factory.create_adapter(config)
        
        assert "Failed to create adapter for driver 'unknown'" in str(exc_info.value)
    
    def test_create_adapter_from_url_postgresql(self):
        """Test creating adapter from PostgreSQL URL."""
        factory = DatabaseFactory()
        
        url = "postgresql://user:pass@localhost:5432/testdb"
        adapter = factory.create_adapter_from_url(url)
        
        assert isinstance(adapter, PostgreSQLAdapter)
        assert adapter.config.driver == "postgresql"
        assert adapter.config.host == "localhost"
        assert adapter.config.port == 5432
        assert adapter.config.database == "testdb"
        assert adapter.config.username == "user"
        assert adapter.config.password == "pass"
    
    def test_create_adapter_from_url_mysql(self):
        """Test creating adapter from MySQL URL."""
        factory = DatabaseFactory()
        
        url = "mysql://user:pass@localhost:3306/testdb"
        adapter = factory.create_adapter_from_url(url)
        
        assert isinstance(adapter, MySQLAdapter)
        assert adapter.config.driver == "mysql"
        assert adapter.config.host == "localhost"
        assert adapter.config.port == 3306
        assert adapter.config.database == "testdb"
        assert adapter.config.username == "user"
        assert adapter.config.password == "pass"
    
    def test_create_adapter_from_url_sqlite(self):
        """Test creating adapter from SQLite URL."""
        factory = DatabaseFactory()
        
        url = "sqlite:///tmp/test.db"
        adapter = factory.create_adapter_from_url(url)
        
        assert isinstance(adapter, SQLiteAdapter)
        assert adapter.config.driver == "sqlite"
        assert adapter.config.database == "tmp/test.db"
    
    def test_create_adapter_from_url_with_kwargs(self):
        """Test creating adapter from URL with additional kwargs."""
        factory = DatabaseFactory()
        
        url = "postgresql://user@localhost/testdb"
        adapter = factory.create_adapter_from_url(
            url,
            password="secret",
            pool_size=20
        )
        
        assert isinstance(adapter, PostgreSQLAdapter)
        assert adapter.config.password == "secret"
        assert adapter.config.pool_size == 20
    
    def test_parse_database_url_schemes(self):
        """Test parsing various URL schemes."""
        factory = DatabaseFactory()
        
        # Test scheme mapping
        test_cases = [
            ("postgres://localhost/db", "postgresql"),
            ("postgresql://localhost/db", "postgresql"),
            ("mysql://localhost/db", "mysql"),
            ("mysql+pymysql://localhost/db", "mysql"),
            ("sqlite:///path/to/db", "sqlite"),
            ("sqlite3:///path/to/db", "sqlite"),
        ]
        
        for url, expected_driver in test_cases:
            config = factory.parse_database_url(url)
            assert config.driver == expected_driver
    
    def test_parse_database_url_default_ports(self):
        """Test URL parsing uses default ports."""
        factory = DatabaseFactory()
        
        # PostgreSQL without port should default to 5432
        config = factory.parse_database_url("postgresql://user@localhost/db")
        assert config.port == 5432
        
        # MySQL without port should default to 3306
        config = factory.parse_database_url("mysql://user@localhost/db")
        assert config.port == 3306
        
        # SQLite should have no port
        config = factory.parse_database_url("sqlite:///tmp/db")
        assert not hasattr(config, 'port') or config.port is None
    
    def test_parse_database_url_invalid(self):
        """Test parsing invalid URLs raises error."""
        factory = DatabaseFactory()
        
        invalid_urls = [
            "not-a-url",
            "unsupported://localhost/db",
            "postgresql://",  # Missing database
            "sqlite://",      # Missing path for SQLite
        ]
        
        for url in invalid_urls:
            with pytest.raises(DatabaseAdapterError):
                factory.parse_database_url(url)
    
    def test_get_supported_drivers(self):
        """Test getting supported drivers."""
        factory = DatabaseFactory()
        
        drivers = factory.get_supported_drivers()
        assert "postgresql" in drivers
        assert "mysql" in drivers
        assert "sqlite" in drivers
    
    def test_get_driver_info(self):
        """Test getting driver information."""
        factory = DatabaseFactory()
        
        info = factory.get_driver_info("postgresql")
        
        assert info["name"] == "postgresql"
        assert info["class"] == "PostgreSQLAdapter"
        assert "postgresql" in info["module"]
        assert info["available"] is True
        assert isinstance(info["capabilities"], dict)
        assert info["capabilities"]["supports_schemas"] is True
    
    def test_get_driver_info_unknown(self):
        """Test getting info for unknown driver raises error."""
        factory = DatabaseFactory()
        
        with pytest.raises(DatabaseAdapterError):
            factory.get_driver_info("unknown")
    
    def test_validate_driver_compatibility(self):
        """Test validating driver compatibility."""
        factory = DatabaseFactory()
        
        # Test compatible requirements
        requirements = {
            "supports_schemas": True,
            "supports_transactions": True,
            "supported_formats": {"custom"},
        }
        
        compatibility = factory.validate_driver_compatibility("postgresql", requirements)
        
        assert compatibility["supports_schemas"] is True
        assert compatibility["supports_transactions"] is True
        assert compatibility["supported_formats"] is True
        
        # Test incompatible requirements
        requirements = {
            "supports_schemas": False,  # PostgreSQL supports schemas
            "default_port": 3306,      # PostgreSQL uses 5432
        }
        
        compatibility = factory.validate_driver_compatibility("postgresql", requirements)
        
        assert compatibility["supports_schemas"] is False
        assert compatibility["default_port"] is False
    
    def test_recommend_driver(self):
        """Test driver recommendation."""
        factory = DatabaseFactory()
        
        # Test requirements that favor PostgreSQL
        requirements = {
            "supports_schemas": True,
            "supports_parallel_dump": True,
            "supported_formats": {"custom", "tar"},
        }
        
        recommended = factory.recommend_driver(requirements)
        assert recommended == "postgresql"
        
        # Test requirements that favor SQLite
        requirements = {
            "requires_credentials": False,
            "supports_ssl": False,
        }
        
        recommended = factory.recommend_driver(requirements)
        assert recommended == "sqlite"
        
        # Test with exclusions
        recommended = factory.recommend_driver(
            requirements, 
            exclude_drivers={"sqlite"}
        )
        assert recommended != "sqlite"
    
    def test_recommend_driver_no_match(self):
        """Test driver recommendation with impossible requirements."""
        factory = DatabaseFactory()
        
        # Exclude all drivers
        recommended = factory.recommend_driver(
            {}, 
            exclude_drivers={"postgresql", "mysql", "sqlite"}
        )
        assert recommended is None


class TestFactoryFunctions:
    """Test module-level factory functions."""
    
    def test_create_adapter_function(self):
        """Test create_adapter function."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        
        adapter = create_adapter(config)
        
        assert isinstance(adapter, SQLiteAdapter)
        assert adapter.config == config
    
    def test_create_adapter_from_url_function(self):
        """Test create_adapter_from_url function."""
        url = "sqlite:///tmp/test.db"
        
        adapter = create_adapter_from_url(url)
        
        assert isinstance(adapter, SQLiteAdapter)
        assert adapter.config.driver == "sqlite"
    
    def test_get_supported_drivers_function(self):
        """Test get_supported_drivers function."""
        drivers = get_supported_drivers()
        
        assert "postgresql" in drivers
        assert "mysql" in drivers
        assert "sqlite" in drivers
    
    def test_get_driver_info_function(self):
        """Test get_driver_info function."""
        info = get_driver_info("mysql")
        
        assert info["name"] == "mysql"
        assert info["class"] == "MySQLAdapter"
        assert info["available"] is True
    
    def test_register_custom_driver_function(self):
        """Test register_custom_driver function."""
        class TestAdapter(DatabaseAdapter):
            def __init__(self, config):
                pass
                
            async def connect(self):
                return True
            
            # Implement other abstract methods minimally
            async def disconnect(self): pass
            async def test_connection(self): return True
            async def create_snapshot(self, *args, **kwargs): pass
            async def restore_snapshot(self, *args, **kwargs): pass
            async def get_database_info(self): pass
            async def validate_snapshot(self, *args): pass
            async def get_supported_formats(self): return set()
            async def estimate_snapshot_size(self, *args): return 0
            async def list_schemas(self): return []
            async def list_tables(self, *args): return []
        
        capabilities = {"test_capability": True}
        
        register_custom_driver("test", TestAdapter, capabilities)
        
        # Verify registration
        drivers = get_supported_drivers()
        assert "test" in drivers
        
        info = get_driver_info("test")
        assert info["name"] == "test"
        assert info["class"] == "TestAdapter"
        assert info["capabilities"]["test_capability"] is True


class TestDatabaseFactoryEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_factory_with_modified_registry(self):
        """Test factory behavior when registry is modified."""
        factory = DatabaseFactory()
        
        # Remove a driver from registry
        factory.registry.unregister_driver("mysql")
        
        # Should not be able to create MySQL adapter
        config = DatabaseConfig(driver="mysql", database="test")
        
        with pytest.raises(DatabaseAdapterError):
            factory.create_adapter(config)
        
        # Should still work for other drivers
        config = DatabaseConfig(driver="postgresql", database="test")
        adapter = factory.create_adapter(config)
        assert isinstance(adapter, PostgreSQLAdapter)
    
    def test_concurrent_registry_access(self):
        """Test concurrent access to registry (basic thread safety)."""
        factory = DatabaseFactory()
        
        # This test mainly ensures no exceptions are raised
        # when accessing registry from multiple "concurrent" operations
        for _ in range(10):
            drivers = factory.get_supported_drivers()
            assert len(drivers) >= 2  # At least postgresql and sqlite should remain
            
            info = factory.get_driver_info("postgresql")
            assert info["available"] is True
    
    def test_url_parsing_edge_cases(self):
        """Test URL parsing edge cases."""
        factory = DatabaseFactory()
        
        # URL with query parameters (should be ignored)
        config = factory.parse_database_url("postgresql://user@host/db?sslmode=require")
        assert config.driver == "postgresql"
        assert config.database == "db"
        
        # URL with fragment (should be ignored)  
        config = factory.parse_database_url("postgresql://user@host/db#fragment")
        assert config.driver == "postgresql"
        assert config.database == "db"
        
        # SQLite with absolute path
        config = factory.parse_database_url("sqlite:////absolute/path/to/db")
        assert config.driver == "sqlite"
        assert config.database == "/absolute/path/to/db"
    
    def test_recommendation_with_complex_requirements(self):
        """Test recommendation with complex overlapping requirements."""
        factory = DatabaseFactory()
        
        # Requirements that multiple drivers might partially satisfy
        requirements = {
            "supports_schemas": True,      # PostgreSQL and SQLite
            "supports_transactions": True, # All drivers
            "requires_credentials": True,  # PostgreSQL and MySQL
            "supports_ssl": True,          # PostgreSQL and MySQL
        }
        
        recommended = factory.recommend_driver(requirements)
        
        # PostgreSQL should win as it satisfies all requirements
        assert recommended == "postgresql"
        
        # Now exclude PostgreSQL
        recommended = factory.recommend_driver(
            requirements,
            exclude_drivers={"postgresql"}
        )
        
        # MySQL should be next best (doesn't support schemas but satisfies others)
        assert recommended == "mysql"