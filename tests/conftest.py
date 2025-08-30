"""Shared test fixtures and configuration."""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from dbranching.config import DatabaseConfig, Config
from dbranching.database.adapter import DatabaseAdapter
from dbranching.database.factory import DatabaseFactory


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def sample_config_dict() -> Dict[str, Any]:
    """Sample configuration dictionary for tests."""
    return {
        "database": {
            "type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "test_db",
            "username": "test_user",
            "password": "test_pass",
        },
        "storage": {
            "directory": "/tmp/dbranching_test",
            "compression": "gzip",
        },
        "logging": {
            "level": "INFO",
        },
    }


@pytest.fixture
def sample_config(sample_config_dict: Dict[str, Any]) -> Config:
    """Sample configuration object for tests."""
    return Config(**sample_config_dict)


@pytest.fixture
def sample_database_config() -> DatabaseConfig:
    """Sample database configuration for tests."""
    return DatabaseConfig(
        type="postgresql",
        host="localhost",
        port=5432,
        database="test_db",
        username="test_user",
        password="test_pass",
    )


@pytest.fixture
def config_file(temp_dir: Path, sample_config_dict: Dict[str, Any]) -> Path:
    """Create a temporary configuration file."""
    config_path = temp_dir / "dbranching.yaml"
    with config_path.open("w") as f:
        yaml.dump(sample_config_dict, f)
    return config_path


@pytest.fixture
def mock_database_adapter() -> MagicMock:
    """Mock database adapter for testing."""
    adapter = MagicMock(spec=DatabaseAdapter)
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    adapter.execute = AsyncMock()
    adapter.fetch_all = AsyncMock(return_value=[])
    adapter.fetch_one = AsyncMock(return_value=None)
    adapter.get_table_names = AsyncMock(return_value=[])
    adapter.get_table_schema = AsyncMock(return_value={})
    adapter.create_snapshot = AsyncMock()
    adapter.restore_snapshot = AsyncMock()
    return adapter


@pytest.fixture
def mock_database_factory() -> MagicMock:
    """Mock database factory for testing."""
    factory = MagicMock(spec=DatabaseFactory)
    mock_adapter = MagicMock(spec=DatabaseAdapter)
    factory.create = MagicMock(return_value=mock_adapter)
    return factory


@pytest.fixture(autouse=True)
def silence_logging():
    """Silence logging during tests unless explicitly enabled."""
    logging.getLogger("dbranching").setLevel(logging.CRITICAL)


@pytest.fixture
def sqlite_config() -> DatabaseConfig:
    """SQLite database configuration for testing."""
    return DatabaseConfig(
        driver="sqlite",
        database=":memory:",
    )


@pytest.fixture
def mysql_config() -> DatabaseConfig:
    """MySQL database configuration for testing."""
    return DatabaseConfig(
        driver="mysql",
        host="localhost",
        port=3306,
        database="test_db",
        username="root",
        password="testpass",
    )


@pytest.fixture
def postgresql_config() -> DatabaseConfig:
    """PostgreSQL database configuration for testing."""
    return DatabaseConfig(
        driver="postgresql",
        host="localhost",
        port=5432,
        database="test_db",
        username="postgres",
        password="testpass",
    )


@pytest.fixture
async def sqlite_adapter(sqlite_config: DatabaseConfig) -> AsyncGenerator[DatabaseAdapter, None]:
    """Real SQLite adapter for integration tests."""
    from dbranching.database.sqlite import SQLiteAdapter
    
    adapter = SQLiteAdapter(sqlite_config)
    await adapter.connect()
    try:
        yield adapter
    finally:
        await adapter.disconnect()


@pytest.fixture
async def mysql_adapter(mysql_config: DatabaseConfig) -> AsyncGenerator[DatabaseAdapter, None]:
    """Real MySQL adapter for integration tests (requires Docker)."""
    from dbranching.database.mysql import MySQLAdapter
    
    adapter = MySQLAdapter(mysql_config)
    try:
        await adapter.connect()
        yield adapter
    except Exception:
        pytest.skip("MySQL not available")
    finally:
        try:
            await adapter.disconnect()
        except Exception:
            pass


@pytest.fixture
async def postgresql_adapter(postgresql_config: DatabaseConfig) -> AsyncGenerator[DatabaseAdapter, None]:
    """Real PostgreSQL adapter for integration tests (requires Docker)."""
    from dbranching.database.postgresql import PostgreSQLAdapter
    
    adapter = PostgreSQLAdapter(postgresql_config)
    try:
        await adapter.connect()
        yield adapter
    except Exception:
        pytest.skip("PostgreSQL not available")
    finally:
        try:
            await adapter.disconnect()
        except Exception:
            pass


# Markers for test categorization
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (fast, isolated)"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (slower, real dependencies)"
    )
    config.addinivalue_line(
        "markers", "performance: marks tests as performance benchmarks"
    )
    config.addinivalue_line(
        "markers", "mysql: marks tests requiring MySQL database"
    )
    config.addinivalue_line(
        "markers", "postgresql: marks tests requiring PostgreSQL database"
    )
    config.addinivalue_line(
        "markers", "sqlite: marks tests requiring SQLite database"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test location."""
    for item in items:
        # Add markers based on test file location
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "performance" in str(item.fspath):
            item.add_marker(pytest.mark.performance)
        
        # Add database markers based on test names or fixtures
        if any(keyword in item.name.lower() for keyword in ["mysql", "mysql_"]):
            item.add_marker(pytest.mark.mysql)
        elif any(keyword in item.name.lower() for keyword in ["postgresql", "postgres"]):
            item.add_marker(pytest.mark.postgresql)
        elif any(keyword in item.name.lower() for keyword in ["sqlite"]):
            item.add_marker(pytest.mark.sqlite)