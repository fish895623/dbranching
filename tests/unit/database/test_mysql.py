"""Tests for MySQL database adapter."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from dbranching.config import DatabaseConfig
from dbranching.database.models import (
    CompressionType,
    SnapshotFormat,
    SnapshotOptions,
    RestoreOptions,
)
from dbranching.database.mysql import MySQLAdapter
from dbranching.exceptions import (
    DatabaseAdapterError,
    DatabaseConnectionError,
    DatabaseTimeoutError,
    SnapshotError,
)


class TestMySQLAdapterInit:
    """Test MySQL adapter initialization."""
    
    def test_valid_initialization(self):
        """Test valid adapter initialization."""
        config = DatabaseConfig(
            driver="mysql",
            host="localhost",
            port=3306,
            database="test",
            username="user",
            password="pass"
        )
        
        adapter = MySQLAdapter(config)
        assert adapter.config == config
        assert adapter._pool is None
        assert adapter._connection_retries == 3
    
    def test_invalid_driver_initialization(self):
        """Test initialization with invalid driver."""
        config = DatabaseConfig(
            driver="postgresql",  # Wrong driver
            host="localhost",
            database="test"
        )
        
        with pytest.raises(DatabaseAdapterError) as exc_info:
            MySQLAdapter(config)
        
        assert "Invalid driver for MySQL adapter" in str(exc_info.value)
        assert "postgresql" in str(exc_info.value)
    
    def test_port_default_correction(self):
        """Test that PostgreSQL default port is corrected to MySQL default."""
        config = DatabaseConfig(
            driver="mysql",
            port=5432,  # PostgreSQL default
            database="test"
        )
        
        adapter = MySQLAdapter(config)
        assert adapter.config.port == 3306
    
    def test_timeout_parsing(self):
        """Test timeout string parsing."""
        config = DatabaseConfig(
            driver="mysql",
            connect_timeout="45s",
            query_timeout="2m"
        )
        
        adapter = MySQLAdapter(config)
        assert adapter._connection_timeout == 45.0
        assert adapter._query_timeout == 120.0
    
    def test_timeout_parsing_edge_cases(self):
        """Test edge cases in timeout parsing."""
        # Test hours
        assert MySQLAdapter._parse_timeout("1h") == 3600.0
        
        # Test numeric only
        assert MySQLAdapter._parse_timeout("30") == 30.0
        
        # Test decimal
        assert MySQLAdapter._parse_timeout("1.5m") == 90.0


class TestConnectionParams:
    """Test connection parameter building."""
    
    def test_basic_connection_params(self):
        """Test basic connection parameters."""
        config = DatabaseConfig(
            driver="mysql",
            host="localhost",
            port=3306,
            database="testdb",
            username="testuser",
            password="testpass"
        )
        
        adapter = MySQLAdapter(config)
        kwargs = adapter._get_connection_kwargs()
        
        assert kwargs["host"] == "localhost"
        assert kwargs["port"] == 3306
        assert kwargs["db"] == "testdb"
        assert kwargs["user"] == "testuser"
        assert kwargs["password"] == "testpass"
        assert kwargs["autocommit"] is False
    
    def test_ssl_configuration(self):
        """Test SSL configuration."""
        config = DatabaseConfig(
            driver="mysql",
            ssl_mode="require"
        )
        
        adapter = MySQLAdapter(config)
        kwargs = adapter._get_connection_kwargs()
        
        assert "ssl" in kwargs
        assert kwargs["ssl"]["disabled"] is False
    
    def test_ssl_disabled(self):
        """Test SSL disabled configuration."""
        config = DatabaseConfig(
            driver="mysql",
            ssl_mode="disable"
        )
        
        adapter = MySQLAdapter(config)
        kwargs = adapter._get_connection_kwargs()
        
        assert "ssl" not in kwargs or kwargs.get("ssl", {}).get("disabled") is True


class TestMySQLAdapterConnection:
    """Test MySQL adapter connection methods."""
    
    @pytest.mark.asyncio
    async def test_successful_connection(self):
        """Test successful database connection."""
        config = DatabaseConfig(driver="mysql", database="test")
        adapter = MySQLAdapter(config)
        
        # Mock aiomysql.create_pool
        mock_pool = AsyncMock()
        mock_pool.closed = False
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        
        with patch('dbranching.database.mysql.aiomysql.create_pool') as mock_create_pool:
            mock_create_pool.return_value = mock_pool
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
            
            result = await adapter.connect()
            
            assert result is True
            assert adapter._pool == mock_pool
            mock_create_pool.assert_called_once()
            mock_cursor.execute.assert_called_once_with("SELECT 1")
    
    @pytest.mark.asyncio
    async def test_connection_timeout(self):
        """Test connection timeout handling."""
        config = DatabaseConfig(driver="mysql", connect_timeout="1s")
        adapter = MySQLAdapter(config)
        
        with patch('dbranching.database.mysql.aiomysql.create_pool') as mock_create_pool:
            mock_create_pool.side_effect = asyncio.TimeoutError()
            
            with pytest.raises(DatabaseTimeoutError):
                await adapter.connect()
    
    @pytest.mark.asyncio
    async def test_connection_retry_logic(self):
        """Test connection retry logic."""
        config = DatabaseConfig(driver="mysql", database="test")
        adapter = MySQLAdapter(config)
        
        call_count = 0
        async def mock_create_pool(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:  # Fail first 2 attempts
                raise Exception("Connection failed")
            # Succeed on 3rd attempt
            mock_pool = AsyncMock()
            mock_pool.closed = False
            return mock_pool
        
        with patch('dbranching.database.mysql.aiomysql.create_pool', side_effect=mock_create_pool):
            with patch('asyncio.sleep'):  # Speed up the test
                mock_pool = AsyncMock()
                mock_conn = AsyncMock()
                mock_cursor = AsyncMock()
                
                with patch.object(adapter, '_pool', mock_pool):
                    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
                    mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
                    
                    result = await adapter.connect()
                    
                    assert result is True
                    assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test database disconnection."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        # Mock pool
        mock_pool = AsyncMock()
        mock_pool.closed = False
        adapter._pool = mock_pool
        
        await adapter.disconnect()
        
        mock_pool.close.assert_called_once()
        mock_pool.wait_closed.assert_called_once()
        assert adapter._pool is None
    
    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        """Test successful connection test."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        
        with patch('dbranching.database.mysql.aiomysql.connect') as mock_connect:
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
            
            result = await adapter.test_connection()
            
            assert result is True
            mock_cursor.execute.assert_called_once_with("SELECT 1")
            mock_conn.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        """Test connection test failure."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        with patch('dbranching.database.mysql.aiomysql.connect') as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")
            
            result = await adapter.test_connection()
            
            assert result is False


class TestMySQLDatabaseInfo:
    """Test database info retrieval."""
    
    @pytest.mark.asyncio
    async def test_get_database_info_success(self):
        """Test successful database info retrieval."""
        config = DatabaseConfig(driver="mysql", database="testdb")
        adapter = MySQLAdapter(config)
        
        # Mock pool and connection
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        
        adapter._pool = mock_pool
        mock_pool.closed = False
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        
        # Mock query responses
        mock_cursor.fetchone.side_effect = [
            ("8.0.33-0ubuntu0.22.04.2",),  # VERSION()
            (1024000,),  # Database size
            (5,),  # Table count
            (10,),  # Connection count
            ("utf8mb4",),  # Character set
            ("utf8mb4_0900_ai_ci",),  # Collation
            ("SYSTEM",),  # Timezone
            (86400,),  # Uptime
        ]
        
        mock_cursor.fetchall.side_effect = [
            [("information_schema",), ("mysql",), ("testdb",), ("performance_schema",)],  # SHOW DATABASES
            [("max_connections", "151"), ("innodb_buffer_pool_size", "134217728")]  # Settings
        ]
        
        db_info = await adapter.get_database_info()
        
        assert db_info.name == "testdb"
        assert db_info.version == "8.0.33"
        assert db_info.size_bytes == 1024000
        assert db_info.table_count == 5
        assert db_info.schema_count == 1
        assert db_info.connection_count == 10
        assert db_info.encoding == "utf8mb4"
        assert db_info.collation == "utf8mb4_0900_ai_ci"
        assert db_info.timezone == "SYSTEM"
        assert db_info.uptime_seconds == 86400
        assert "testdb" in db_info.schemas
        assert "information_schema" not in db_info.schemas  # System schemas filtered out
        assert db_info.extensions == []  # MySQL doesn't have extensions like PostgreSQL


class TestMySQLSnapshot:
    """Test MySQL snapshot operations."""
    
    @pytest.mark.asyncio
    async def test_create_snapshot_success(self):
        """Test successful snapshot creation."""
        config = DatabaseConfig(driver="mysql", database="testdb")
        adapter = MySQLAdapter(config)
        
        # Mock database info
        mock_db_info = Mock()
        mock_db_info.size_bytes = 1024000
        mock_db_info.table_count = 5
        mock_db_info.schema_count = 1
        mock_db_info.version = "8.0.33"
        
        output_path = Path("/tmp/test_snapshot.sql")
        
        with patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
             patch('asyncio.create_subprocess_exec') as mock_subprocess, \
             patch.object(output_path, 'exists', return_value=True), \
             patch.object(output_path, 'stat') as mock_stat, \
             patch.object(output_path.parent, 'mkdir'), \
             patch.object(adapter, '_get_mysqldump_version', return_value="mysqldump 8.0.33"):
            
            # Mock subprocess
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", b"")
            mock_subprocess.return_value = mock_process
            
            # Mock file stat
            mock_stat.return_value.st_size = 512000
            
            options = SnapshotOptions()
            result = await adapter.create_snapshot(output_path, options)
            
            assert result.success is True
            assert result.snapshot_path == output_path
            assert result.size_bytes == 512000
            assert result.database_size_bytes == 1024000
            assert result.tables_included == 5
            assert result.schemas_included == 1
    
    @pytest.mark.asyncio
    async def test_mysqldump_command_building(self):
        """Test mysqldump command building."""
        config = DatabaseConfig(
            driver="mysql",
            host="localhost",
            port=3306,
            username="testuser",
            database="testdb"
        )
        adapter = MySQLAdapter(config)
        
        options = SnapshotOptions(
            data_only=False,
            schema_only=False,
            verbose=True
        )
        
        cmd = await adapter._build_mysqldump_command(Path("/tmp/test.sql"), options)
        
        assert "mysqldump" == cmd[0]
        assert "-h" in cmd and "localhost" in cmd
        assert "-P" in cmd and "3306" in cmd
        assert "-u" in cmd and "testuser" in cmd
        assert "--single-transaction" in cmd
        assert "--routines" in cmd
        assert "--triggers" in cmd
        assert "--verbose" in cmd
        assert "testdb" in cmd
    
    @pytest.mark.asyncio
    async def test_mysqldump_command_options(self):
        """Test mysqldump command with various options."""
        config = DatabaseConfig(driver="mysql", database="testdb")
        adapter = MySQLAdapter(config)
        
        # Test data_only option
        options = SnapshotOptions(data_only=True)
        cmd = await adapter._build_mysqldump_command(Path("/tmp/test.sql"), options)
        assert "--no-create-info" in cmd
        
        # Test schema_only option
        options = SnapshotOptions(schema_only=True)
        cmd = await adapter._build_mysqldump_command(Path("/tmp/test.sql"), options)
        assert "--no-data" in cmd
        
        # Test table exclusion
        options = SnapshotOptions(exclude_tables={"temp_table", "log_table"})
        cmd = await adapter._build_mysqldump_command(Path("/tmp/test.sql"), options)
        assert "--ignore-table=testdb.temp_table" in cmd
        assert "--ignore-table=testdb.log_table" in cmd


class TestMySQLRestore:
    """Test MySQL restore operations."""
    
    @pytest.mark.asyncio
    async def test_restore_snapshot_success(self):
        """Test successful snapshot restore."""
        config = DatabaseConfig(driver="mysql", database="testdb")
        adapter = MySQLAdapter(config)
        
        snapshot_path = Path("/tmp/test_snapshot.sql")
        
        # Mock validation result
        mock_validation = Mock()
        mock_validation.valid = True
        
        # Mock database info
        mock_db_info = Mock()
        mock_db_info.table_count = 5
        mock_db_info.schema_count = 1
        mock_db_info.version = "8.0.33"
        
        with patch.object(adapter, 'validate_snapshot', return_value=mock_validation), \
             patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
             patch('asyncio.create_subprocess_exec') as mock_subprocess, \
             patch('builtins.open', mock_open_read_data(b"SELECT 1;")), \
             patch.object(snapshot_path, 'exists', return_value=True), \
             patch.object(adapter, '_get_mysql_version', return_value="mysql 8.0.33"):
            
            # Mock subprocess
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", b"")
            mock_subprocess.return_value = mock_process
            
            options = RestoreOptions()
            result = await adapter.restore_snapshot(snapshot_path, options)
            
            assert result.success is True
            assert result.snapshot_path == snapshot_path
            assert result.tables_restored == 5
            assert result.schemas_restored == 1
    
    @pytest.mark.asyncio
    async def test_mysql_command_building(self):
        """Test mysql command building."""
        config = DatabaseConfig(
            driver="mysql",
            host="localhost",
            port=3306,
            username="testuser",
            database="testdb"
        )
        adapter = MySQLAdapter(config)
        
        cmd = await adapter._build_mysql_command(Path("/tmp/test.sql"), RestoreOptions())
        
        assert "mysql" == cmd[0]
        assert "-h" in cmd and "localhost" in cmd
        assert "-P" in cmd and "3306" in cmd
        assert "-u" in cmd and "testuser" in cmd
        assert "testdb" in cmd


class TestMySQLValidation:
    """Test MySQL snapshot validation."""
    
    @pytest.mark.asyncio
    async def test_validate_mysql_dump_success(self):
        """Test successful MySQL dump validation."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        snapshot_path = Path("/tmp/test.sql")
        
        # Mock file content that looks like a MySQL dump
        mysql_dump_content = """
        -- MySQL dump 10.13  Distrib 8.0.33
        -- Host: localhost    Database: testdb
        -- Server version	8.0.33-0ubuntu0.22.04.2
        CREATE TABLE users (id INT PRIMARY KEY);
        CREATE TABLE orders (id INT PRIMARY KEY);
        """
        
        with patch('builtins.open', mock_open_read_data(mysql_dump_content)), \
             patch.object(snapshot_path, 'exists', return_value=True), \
             patch.object(snapshot_path, 'stat') as mock_stat, \
             patch.object(adapter, '_calculate_file_checksum', return_value="abc123"):
            
            mock_stat.return_value.st_size = 1024
            
            result = await adapter.validate_snapshot(snapshot_path)
            
            assert result.valid is True
            assert result.format_valid is True
            assert result.size_bytes == 1024
            assert result.table_count == 2
            assert result.database_version == "8.0.33"
    
    @pytest.mark.asyncio
    async def test_validate_invalid_dump(self):
        """Test validation of invalid dump file."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        snapshot_path = Path("/tmp/invalid.sql")
        
        # Mock file content that doesn't look like a MySQL dump
        invalid_content = "This is not a MySQL dump file"
        
        with patch('builtins.open', mock_open_read_data(invalid_content)), \
             patch.object(snapshot_path, 'exists', return_value=True), \
             patch.object(snapshot_path, 'stat') as mock_stat, \
             patch.object(adapter, '_calculate_file_checksum', return_value="def456"):
            
            mock_stat.return_value.st_size = 1024
            
            result = await adapter.validate_snapshot(snapshot_path)
            
            assert result.valid is False
            assert result.format_valid is False
            assert result.error_message == "File does not appear to be a MySQL dump"


class TestMySQLUtilities:
    """Test MySQL adapter utility methods."""
    
    @pytest.mark.asyncio
    async def test_get_supported_formats(self):
        """Test getting supported formats."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        formats = await adapter.get_supported_formats()
        
        assert formats == {"plain"}
    
    @pytest.mark.asyncio
    async def test_estimate_snapshot_size(self):
        """Test snapshot size estimation."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        # Mock database info
        mock_db_info = Mock()
        mock_db_info.size_bytes = 1000000
        
        with patch.object(adapter, 'get_database_info', return_value=mock_db_info):
            # Test without compression
            size = await adapter.estimate_snapshot_size()
            assert size == 1000000
            
            # Test with gzip compression
            options = SnapshotOptions(compression=CompressionType.GZIP)
            size = await adapter.estimate_snapshot_size(options)
            assert size == 200000  # 80% compression
            
            # Test schema only
            options = SnapshotOptions(schema_only=True)
            size = await adapter.estimate_snapshot_size(options)
            assert size == 10000  # 1% of original size
    
    @pytest.mark.asyncio
    async def test_list_schemas(self):
        """Test listing database schemas."""
        config = DatabaseConfig(driver="mysql")
        adapter = MySQLAdapter(config)
        
        # Mock pool and connection
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        
        adapter._pool = mock_pool
        mock_pool.closed = False
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        
        mock_cursor.fetchall.return_value = [
            ("information_schema",),
            ("mysql",),
            ("performance_schema",),
            ("sys",),
            ("testdb",),
            ("userdb",)
        ]
        
        schemas = await adapter.list_schemas()
        
        # System databases should be filtered out
        assert "testdb" in schemas
        assert "userdb" in schemas
        assert "information_schema" not in schemas
        assert "mysql" not in schemas
        assert "performance_schema" not in schemas
        assert "sys" not in schemas
    
    @pytest.mark.asyncio
    async def test_list_tables(self):
        """Test listing database tables."""
        config = DatabaseConfig(driver="mysql", database="testdb")
        adapter = MySQLAdapter(config)
        
        # Mock pool and connection
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        
        adapter._pool = mock_pool
        mock_pool.closed = False
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        
        mock_cursor.fetchall.return_value = [
            ("users",),
            ("orders",),
            ("products",)
        ]
        
        # Test without schema (should return qualified names)
        tables = await adapter.list_tables()
        
        assert len(tables) == 3
        assert "testdb.users" in tables
        assert "testdb.orders" in tables
        assert "testdb.products" in tables
        
        # Test with schema (should return unqualified names)
        tables = await adapter.list_tables("testdb")
        
        assert len(tables) == 3
        assert "users" in tables
        assert "orders" in tables
        assert "products" in tables


def mock_open_read_data(read_data):
    """Helper to create mock open that returns specific data."""
    from unittest.mock import mock_open
    return mock_open(read_data=read_data)