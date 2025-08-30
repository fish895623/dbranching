"""Integration tests for database operations with real databases."""

import pytest
import asyncio
from typing import List, Dict, Any

from dbranching.database.adapter import DatabaseAdapter
from dbranching.database.factory import DatabaseFactory
from dbranching.config import DatabaseConfig


@pytest.mark.integration
@pytest.mark.sqlite
class TestSQLiteIntegration:
    """Integration tests with real SQLite database."""

    @pytest.mark.asyncio
    async def test_sqlite_connection_lifecycle(self, sqlite_config: DatabaseConfig):
        """Test SQLite connection lifecycle."""
        factory = DatabaseFactory()
        adapter = factory.create_adapter(sqlite_config)
        
        # Test connection
        await adapter.connect()
        assert adapter.is_connected()
        
        # Test disconnection
        await adapter.disconnect()
        assert not adapter.is_connected()

    @pytest.mark.asyncio
    async def test_sqlite_table_operations(self, sqlite_adapter: DatabaseAdapter):
        """Test SQLite table operations."""
        # Create a test table
        await sqlite_adapter.execute("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert test data
        await sqlite_adapter.execute(
            "INSERT INTO test_table (name) VALUES (?), (?)",
            ("test1", "test2")
        )
        
        # Test table listing
        tables = await sqlite_adapter.get_table_names()
        assert "test_table" in tables
        
        # Test data retrieval
        rows = await sqlite_adapter.fetch_all("SELECT name FROM test_table ORDER BY name")
        assert len(rows) == 2
        assert rows[0]["name"] == "test1"
        assert rows[1]["name"] == "test2"
        
        # Test schema retrieval
        schema = await sqlite_adapter.get_table_schema("test_table")
        assert "id" in schema
        assert "name" in schema
        assert "created_at" in schema

    @pytest.mark.asyncio
    async def test_sqlite_transaction_support(self, sqlite_adapter: DatabaseAdapter):
        """Test SQLite transaction support."""
        # Create test table
        await sqlite_adapter.execute("""
            CREATE TABLE transaction_test (
                id INTEGER PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Test successful transaction
        async with sqlite_adapter.transaction():
            await sqlite_adapter.execute(
                "INSERT INTO transaction_test (value) VALUES (?)", ("success",)
            )
        
        rows = await sqlite_adapter.fetch_all("SELECT value FROM transaction_test")
        assert len(rows) == 1
        assert rows[0]["value"] == "success"
        
        # Test rollback on exception
        try:
            async with sqlite_adapter.transaction():
                await sqlite_adapter.execute(
                    "INSERT INTO transaction_test (value) VALUES (?)", ("rollback",)
                )
                raise Exception("Force rollback")
        except Exception:
            pass
        
        rows = await sqlite_adapter.fetch_all("SELECT value FROM transaction_test")
        assert len(rows) == 1  # Should still be 1, rollback happened


@pytest.mark.integration
@pytest.mark.mysql
class TestMySQLIntegration:
    """Integration tests with real MySQL database (requires Docker)."""

    @pytest.mark.asyncio
    async def test_mysql_connection_lifecycle(self, mysql_config: DatabaseConfig):
        """Test MySQL connection lifecycle."""
        factory = DatabaseFactory()
        adapter = factory.create_adapter(mysql_config)
        
        try:
            await adapter.connect()
            assert adapter.is_connected()
            await adapter.disconnect()
            assert not adapter.is_connected()
        except Exception:
            pytest.skip("MySQL not available")

    @pytest.mark.asyncio
    async def test_mysql_table_operations(self, mysql_adapter: DatabaseAdapter):
        """Test MySQL table operations."""
        # Create a test table
        await mysql_adapter.execute("""
            CREATE TABLE IF NOT EXISTS test_table (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Clear any existing data
        await mysql_adapter.execute("DELETE FROM test_table")
        
        # Insert test data
        await mysql_adapter.execute(
            "INSERT INTO test_table (name) VALUES (%s), (%s)",
            ("test1", "test2")
        )
        
        # Test table listing
        tables = await mysql_adapter.get_table_names()
        assert "test_table" in tables
        
        # Test data retrieval
        rows = await mysql_adapter.fetch_all("SELECT name FROM test_table ORDER BY name")
        assert len(rows) == 2
        assert rows[0]["name"] == "test1"
        assert rows[1]["name"] == "test2"

    @pytest.mark.asyncio
    async def test_mysql_large_dataset(self, mysql_adapter: DatabaseAdapter):
        """Test MySQL with larger datasets."""
        await mysql_adapter.execute("""
            CREATE TABLE IF NOT EXISTS large_test (
                id INT PRIMARY KEY AUTO_INCREMENT,
                data VARCHAR(1000)
            )
        """)
        
        await mysql_adapter.execute("DELETE FROM large_test")
        
        # Insert 1000 rows
        values = [(f"data_{i}",) for i in range(1000)]
        for i in range(0, len(values), 100):  # Batch inserts
            batch = values[i:i+100]
            placeholders = ",".join(["(%s)"] * len(batch))
            query = f"INSERT INTO large_test (data) VALUES {placeholders}"
            flattened_values = [item for sublist in batch for item in sublist]
            await mysql_adapter.execute(query, flattened_values)
        
        # Verify count
        result = await mysql_adapter.fetch_one("SELECT COUNT(*) as count FROM large_test")
        assert result["count"] == 1000


@pytest.mark.integration
@pytest.mark.postgresql
class TestPostgreSQLIntegration:
    """Integration tests with real PostgreSQL database (requires Docker)."""

    @pytest.mark.asyncio
    async def test_postgresql_connection_lifecycle(self, postgresql_config: DatabaseConfig):
        """Test PostgreSQL connection lifecycle."""
        factory = DatabaseFactory()
        adapter = factory.create_adapter(postgresql_config)
        
        try:
            await adapter.connect()
            assert adapter.is_connected()
            await adapter.disconnect()
            assert not adapter.is_connected()
        except Exception:
            pytest.skip("PostgreSQL not available")

    @pytest.mark.asyncio
    async def test_postgresql_table_operations(self, postgresql_adapter: DatabaseAdapter):
        """Test PostgreSQL table operations."""
        # Create a test table
        await postgresql_adapter.execute("""
            CREATE TABLE IF NOT EXISTS test_table (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Clear any existing data
        await postgresql_adapter.execute("DELETE FROM test_table")
        
        # Insert test data
        await postgresql_adapter.execute(
            "INSERT INTO test_table (name) VALUES ($1), ($2)",
            ("test1", "test2")
        )
        
        # Test table listing
        tables = await postgresql_adapter.get_table_names()
        assert "test_table" in tables
        
        # Test data retrieval
        rows = await postgresql_adapter.fetch_all("SELECT name FROM test_table ORDER BY name")
        assert len(rows) == 2
        assert rows[0]["name"] == "test1"
        assert rows[1]["name"] == "test2"

    @pytest.mark.asyncio
    async def test_postgresql_advanced_features(self, postgresql_adapter: DatabaseAdapter):
        """Test PostgreSQL-specific features."""
        # Test JSON column support
        await postgresql_adapter.execute("""
            CREATE TABLE IF NOT EXISTS json_test (
                id SERIAL PRIMARY KEY,
                data JSONB
            )
        """)
        
        await postgresql_adapter.execute("DELETE FROM json_test")
        
        # Insert JSON data
        json_data = {"key": "value", "numbers": [1, 2, 3]}
        await postgresql_adapter.execute(
            "INSERT INTO json_test (data) VALUES ($1)",
            (json_data,)
        )
        
        # Query JSON data
        result = await postgresql_adapter.fetch_one(
            "SELECT data FROM json_test WHERE data->>'key' = $1",
            ("value",)
        )
        assert result["data"]["key"] == "value"
        assert result["data"]["numbers"] == [1, 2, 3]


@pytest.mark.integration
class TestCrossDatabase:
    """Integration tests across different database types."""

    @pytest.mark.asyncio
    async def test_factory_creates_correct_adapters(self):
        """Test that factory creates correct adapter types for different configs."""
        factory = DatabaseFactory()
        
        # Test SQLite
        sqlite_config = DatabaseConfig(driver="sqlite", database=":memory:")
        sqlite_adapter = factory.create_adapter(sqlite_config)
        assert sqlite_adapter.__class__.__name__ == "SQLiteAdapter"
        
        # Test MySQL config (don't connect)
        mysql_config = DatabaseConfig(
            driver="mysql", host="localhost", database="test", username="user"
        )
        mysql_adapter = factory.create_adapter(mysql_config)
        assert mysql_adapter.__class__.__name__ == "MySQLAdapter"
        
        # Test PostgreSQL config (don't connect)
        pg_config = DatabaseConfig(
            driver="postgresql", host="localhost", database="test", username="user"
        )
        pg_adapter = factory.create_adapter(pg_config)
        assert pg_adapter.__class__.__name__ == "PostgreSQLAdapter"

    @pytest.mark.asyncio
    async def test_database_independence(self):
        """Test that database operations are independent."""
        factory = DatabaseFactory()
        
        # Create two SQLite adapters with different databases
        config1 = DatabaseConfig(driver="sqlite", database=":memory:")
        config2 = DatabaseConfig(driver="sqlite", database=":memory:")
        
        adapter1 = factory.create_adapter(config1)
        adapter2 = factory.create_adapter(config2)
        
        await adapter1.connect()
        await adapter2.connect()
        
        try:
            # Create table in first database
            await adapter1.execute("""
                CREATE TABLE test (id INTEGER, value TEXT)
            """)
            await adapter1.execute("INSERT INTO test VALUES (1, 'db1')")
            
            # Create table in second database
            await adapter2.execute("""
                CREATE TABLE test (id INTEGER, value TEXT)
            """)
            await adapter2.execute("INSERT INTO test VALUES (2, 'db2')")
            
            # Verify independence
            result1 = await adapter1.fetch_one("SELECT value FROM test")
            result2 = await adapter2.fetch_one("SELECT value FROM test")
            
            assert result1["value"] == "db1"
            assert result2["value"] == "db2"
            
        finally:
            await adapter1.disconnect()
            await adapter2.disconnect()