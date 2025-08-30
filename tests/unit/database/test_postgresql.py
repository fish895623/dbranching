"""Tests for PostgreSQL database adapter."""

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
from dbranching.database.postgresql import PostgreSQLAdapter
from dbranching.exceptions import (
    DatabaseAdapterError,
    DatabaseConnectionError,
    DatabaseTimeoutError,
    SnapshotError,
)


class TestPostgreSQLAdapterInit:
    """Test PostgreSQL adapter initialization."""
    
    def test_valid_initialization(self):
        """Test valid adapter initialization."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            port=5432,
            database="test",
            username="user",
            password="pass"
        )
        
        adapter = PostgreSQLAdapter(config)
        assert adapter.config == config
        assert adapter._connection is None
        assert adapter._connection_retries == 3
    
    def test_invalid_driver_initialization(self):
        """Test initialization with invalid driver."""
        config = DatabaseConfig(
            driver="mysql",  # Wrong driver
            host="localhost",
            database="test"
        )
        
        with pytest.raises(DatabaseAdapterError) as exc_info:
            PostgreSQLAdapter(config)
        
        assert "Invalid driver for PostgreSQL adapter" in str(exc_info.value)
        assert "mysql" in str(exc_info.value)
    
    def test_timeout_parsing(self):
        """Test timeout string parsing."""
        config = DatabaseConfig(
            driver="postgresql",
            connect_timeout="45s",
            query_timeout="2m"
        )
        
        adapter = PostgreSQLAdapter(config)
        assert adapter._connection_timeout == 45.0
        assert adapter._query_timeout == 120.0
    
    def test_timeout_parsing_edge_cases(self):
        """Test edge cases in timeout parsing."""
        # Test hours
        assert PostgreSQLAdapter._parse_timeout("1h") == 3600.0
        
        # Test numeric only
        assert PostgreSQLAdapter._parse_timeout("30") == 30.0
        
        # Test decimal
        assert PostgreSQLAdapter._parse_timeout("1.5m") == 90.0


class TestConnectionString:
    """Test connection string building."""
    
    def test_basic_connection_string(self):
        """Test basic connection string without password."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            port=5432,
            database="testdb",
            username="testuser"
        )
        
        adapter = PostgreSQLAdapter(config)
        conn_str = adapter._get_connection_string(include_password=False)
        
        assert "host=localhost" in conn_str
        assert "port=5432" in conn_str
        assert "dbname=testdb" in conn_str
        assert "user=testuser" in conn_str
        assert "password" not in conn_str
    
    def test_connection_string_with_password(self):
        """Test connection string with password."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            database="testdb",
            username="testuser",
            password="secret123"
        )
        
        adapter = PostgreSQLAdapter(config)
        conn_str = adapter._get_connection_string(include_password=True)
        
        assert "password=secret123" in conn_str
    
    def test_connection_string_ssl_mode(self):
        """Test connection string with custom SSL mode."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            database="testdb",
            ssl_mode="require"
        )
        
        adapter = PostgreSQLAdapter(config)
        conn_str = adapter._get_connection_string()
        
        assert "sslmode=require" in conn_str
    
    def test_connection_string_ssl_prefer_default(self):
        """Test that prefer SSL mode doesn't add sslmode parameter."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            database="testdb",
            ssl_mode="prefer"  # Default
        )
        
        adapter = PostgreSQLAdapter(config)
        conn_str = adapter._get_connection_string()
        
        assert "sslmode" not in conn_str


class TestEnvironmentVariables:
    """Test environment variable handling."""
    
    def test_pg_dump_env_without_password(self):
        """Test environment variables without password."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            database="test"
        )
        
        adapter = PostgreSQLAdapter(config)
        env = adapter._get_pg_dump_env()
        
        assert "PGPASSWORD" not in env
    
    def test_pg_dump_env_with_password(self):
        """Test environment variables with password."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            database="test",
            password="secret123"
        )
        
        adapter = PostgreSQLAdapter(config)
        env = adapter._get_pg_dump_env()
        
        assert env["PGPASSWORD"] == "secret123"


class TestConnection:
    """Test database connection methods."""
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncpg.connect')
    async def test_successful_connection(self, mock_connect):
        """Test successful database connection."""
        # Setup mocks
        mock_connection = AsyncMock()
        mock_connection.is_closed.return_value = False
        mock_connection.fetchval.return_value = 1
        mock_connect.return_value = mock_connection
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        # Test connection
        result = await adapter.connect()
        
        assert result is True
        assert adapter._connection == mock_connection
        mock_connect.assert_called_once()
        mock_connection.fetchval.assert_called_once_with("SELECT 1")
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncpg.connect')
    async def test_connection_timeout(self, mock_connect):
        """Test connection timeout."""
        mock_connect.side_effect = asyncio.TimeoutError()
        
        config = DatabaseConfig(
            driver="postgresql",
            connect_timeout="1s"
        )
        adapter = PostgreSQLAdapter(config)
        adapter._connection_retries = 1  # Reduce retries for testing
        
        with pytest.raises(DatabaseTimeoutError):
            await adapter.connect()
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncpg.connect')
    async def test_connection_failure_with_retries(self, mock_connect):
        """Test connection failure with retry logic."""
        mock_connect.side_effect = Exception("Connection failed")
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        adapter._connection_retries = 2  # Reduce retries for testing
        
        with pytest.raises(DatabaseConnectionError) as exc_info:
            await adapter.connect()
        
        assert "Connection failed" in str(exc_info.value)
        assert mock_connect.call_count == 2  # Should retry
    
    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        """Test disconnect when not connected."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        # Should not raise any exception
        await adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_disconnect_with_connection(self):
        """Test disconnect with active connection."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        # Mock connection
        mock_connection = Mock()
        mock_connection.is_closed.return_value = False
        mock_connection.close = AsyncMock()
        adapter._connection = mock_connection
        
        await adapter.disconnect()
        
        mock_connection.close.assert_called_once()
        assert adapter._connection is None
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncpg.connect')
    async def test_test_connection_success(self, mock_connect):
        """Test successful connection test."""
        mock_connection = AsyncMock()
        mock_connection.fetchval.return_value = 1
        mock_connect.return_value = mock_connection
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        result = await adapter.test_connection()
        
        assert result is True
        mock_connect.assert_called_once()
        mock_connection.fetchval.assert_called_once_with("SELECT 1")
        mock_connection.close.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncpg.connect')
    async def test_test_connection_failure(self, mock_connect):
        """Test connection test failure."""
        mock_connect.side_effect = Exception("Connection failed")
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        result = await adapter.test_connection()
        
        assert result is False


class TestPgDumpCommandBuilding:
    """Test pg_dump command building."""
    
    @pytest.mark.asyncio
    async def test_basic_pg_dump_command(self):
        """Test basic pg_dump command building."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            port=5432,
            database="testdb",
            username="testuser"
        )
        
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        options = SnapshotOptions()
        
        cmd = await adapter._build_pg_dump_command(output_path, options)
        
        assert cmd[0] == "pg_dump"
        assert "-h" in cmd and "localhost" in cmd
        assert "-p" in cmd and "5432" in cmd
        assert "-d" in cmd and "testdb" in cmd
        assert "-U" in cmd and "testuser" in cmd
        assert "-F" in cmd and "c" in cmd  # Custom format
        assert "-f" in cmd and str(output_path) in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_format_options(self):
        """Test different format options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        # Test custom format
        options = SnapshotOptions(format=SnapshotFormat.CUSTOM)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "-F" in cmd and "c" in cmd
        
        # Test tar format
        options = SnapshotOptions(format=SnapshotFormat.TAR)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "-F" in cmd and "t" in cmd
        
        # Test plain format
        options = SnapshotOptions(format=SnapshotFormat.PLAIN)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "-F" in cmd and "p" in cmd
        
        # Test directory format
        options = SnapshotOptions(format=SnapshotFormat.DIRECTORY)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "-F" in cmd and "d" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_compression_options(self):
        """Test compression options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        # Test compression with custom format
        options = SnapshotOptions(
            format=SnapshotFormat.CUSTOM,
            compression=CompressionType.GZIP,
            compression_level=9
        )
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "-Z" in cmd and "9" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_parallel_jobs(self):
        """Test parallel jobs option."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        # Test parallel jobs with custom format
        options = SnapshotOptions(
            format=SnapshotFormat.CUSTOM,
            parallel_jobs=4
        )
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "-j" in cmd and "4" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_schema_filtering(self):
        """Test schema filtering options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        # Test include schemas
        options = SnapshotOptions(
            include_schemas={"public", "app"}
        )
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert cmd.count("-n") == 2
        assert "public" in cmd and "app" in cmd
        
        # Test exclude schemas
        options = SnapshotOptions(
            exclude_schemas={"temp", "test"}
        )
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert cmd.count("-N") == 2
        assert "temp" in cmd and "test" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_table_filtering(self):
        """Test table filtering options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        # Test include tables
        options = SnapshotOptions(
            include_tables={"users", "orders"}
        )
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert cmd.count("-t") == 2
        assert "users" in cmd and "orders" in cmd
        
        # Test exclude tables
        options = SnapshotOptions(
            exclude_tables={"logs", "temp_data"}
        )
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert cmd.count("-T") == 2
        assert "logs" in cmd and "temp_data" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_data_schema_options(self):
        """Test data-only and schema-only options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        # Test data-only
        options = SnapshotOptions(data_only=True)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "--data-only" in cmd
        
        # Test schema-only
        options = SnapshotOptions(schema_only=True)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "--schema-only" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_blob_options(self):
        """Test large object options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        # Test include blobs
        options = SnapshotOptions(include_large_objects=True)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "--blobs" in cmd
        
        # Test exclude blobs
        options = SnapshotOptions(include_large_objects=False)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "--no-blobs" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_dump_verbose_option(self):
        """Test verbose option."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        output_path = Path("/tmp/test.dump")
        
        options = SnapshotOptions(verbose=True)
        cmd = await adapter._build_pg_dump_command(output_path, options)
        assert "--verbose" in cmd


class TestPgRestoreCommandBuilding:
    """Test pg_restore command building."""
    
    @pytest.mark.asyncio
    async def test_basic_pg_restore_command(self):
        """Test basic pg_restore command building."""
        config = DatabaseConfig(
            driver="postgresql",
            host="localhost",
            port=5432,
            database="testdb",
            username="testuser"
        )
        
        adapter = PostgreSQLAdapter(config)
        snapshot_path = Path("/tmp/test.dump")
        options = RestoreOptions()
        
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        
        assert cmd[0] == "pg_restore"
        assert "-h" in cmd and "localhost" in cmd
        assert "-p" in cmd and "5432" in cmd
        assert "-d" in cmd and "testdb" in cmd
        assert "-U" in cmd and "testuser" in cmd
        assert str(snapshot_path) in cmd
    
    @pytest.mark.asyncio
    async def test_pg_restore_parallel_jobs(self):
        """Test parallel jobs option."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        snapshot_path = Path("/tmp/test.dump")
        
        options = RestoreOptions(parallel_jobs=4)
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        assert "-j" in cmd and "4" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_restore_clean_option(self):
        """Test clean option."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        snapshot_path = Path("/tmp/test.dump")
        
        options = RestoreOptions(clean=True)
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        assert "--clean" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_restore_create_option(self):
        """Test create option."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        snapshot_path = Path("/tmp/test.dump")
        
        options = RestoreOptions(create=True)
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        assert "--create" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_restore_transaction_options(self):
        """Test transaction-related options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        snapshot_path = Path("/tmp/test.dump")
        
        # Test single transaction
        options = RestoreOptions(single_transaction=True)
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        assert "--single-transaction" in cmd
        
        # Test disable triggers
        options = RestoreOptions(disable_triggers=True)
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        assert "--disable-triggers" in cmd
    
    @pytest.mark.asyncio
    async def test_pg_restore_ownership_options(self):
        """Test ownership and privilege options."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        snapshot_path = Path("/tmp/test.dump")
        
        # Test no owner
        options = RestoreOptions(no_owner=True)
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        assert "--no-owner" in cmd
        
        # Test no privileges
        options = RestoreOptions(no_privileges=True)
        cmd = await adapter._build_pg_restore_command(snapshot_path, options)
        assert "--no-privileges" in cmd


class TestVersionMethods:
    """Test version retrieval methods."""
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncio.create_subprocess_exec')
    async def test_get_pg_dump_version(self, mock_subprocess):
        """Test getting pg_dump version."""
        # Mock subprocess
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"pg_dump (PostgreSQL) 13.8\n", b"")
        mock_subprocess.return_value = mock_process
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        version = await adapter._get_pg_dump_version()
        assert version == "pg_dump (PostgreSQL) 13.8"
        
        mock_subprocess.assert_called_once_with(
            "pg_dump", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncio.create_subprocess_exec')
    async def test_get_pg_restore_version(self, mock_subprocess):
        """Test getting pg_restore version."""
        # Mock subprocess
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"pg_restore (PostgreSQL) 13.8\n", b"")
        mock_subprocess.return_value = mock_process
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        version = await adapter._get_pg_restore_version()
        assert version == "pg_restore (PostgreSQL) 13.8"
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.asyncio.create_subprocess_exec')
    async def test_version_methods_exception_handling(self, mock_subprocess):
        """Test version methods with exceptions."""
        mock_subprocess.side_effect = Exception("Command not found")
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        version = await adapter._get_pg_dump_version()
        assert version == "unknown"
        
        version = await adapter._get_pg_restore_version()
        assert version == "unknown"


class TestUtilityMethods:
    """Test utility methods."""
    
    @pytest.mark.asyncio
    async def test_calculate_file_checksum(self, tmp_path):
        """Test file checksum calculation."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        checksum = await adapter._calculate_file_checksum(test_file)
        
        # Verify checksum is a valid SHA256 hex string
        assert isinstance(checksum, str)
        assert len(checksum) == 64  # SHA256 hex string length
        assert all(c in "0123456789abcdef" for c in checksum.lower())
    
    @pytest.mark.asyncio
    async def test_get_supported_formats(self):
        """Test getting supported formats."""
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        formats = await adapter.get_supported_formats()
        
        assert isinstance(formats, set)
        assert "custom" in formats
        assert "tar" in formats
        assert "plain" in formats
        assert "directory" in formats
    
    @pytest.mark.asyncio
    @patch('dbranching.database.postgresql.PostgreSQLAdapter.get_database_info')
    async def test_estimate_snapshot_size(self, mock_get_db_info):
        """Test snapshot size estimation."""
        # Mock database info
        mock_db_info = Mock()
        mock_db_info.size_bytes = 1000000  # 1MB
        mock_get_db_info.return_value = mock_db_info
        
        config = DatabaseConfig(driver="postgresql")
        adapter = PostgreSQLAdapter(config)
        
        # Test without options
        size = await adapter.estimate_snapshot_size()
        assert size == 1000000
        
        # Test with GZIP compression
        options = SnapshotOptions(compression=CompressionType.GZIP)
        size = await adapter.estimate_snapshot_size(options)
        assert size == int(1000000 * 0.3)  # ~70% compression
        
        # Test with schema-only (no compression)
        options = SnapshotOptions(schema_only=True, compression=CompressionType.NONE)
        size = await adapter.estimate_snapshot_size(options)
        assert size == int(1000000 * 0.01)  # Much smaller
        
        # Test with schema-only and GZIP compression
        options = SnapshotOptions(schema_only=True, compression=CompressionType.GZIP)
        size = await adapter.estimate_snapshot_size(options)
        expected = int(int(1000000 * 0.01) * 0.3)  # First schema reduction, then compression
        assert size == expected