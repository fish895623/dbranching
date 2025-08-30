"""Tests for SQLite database adapter."""

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from dbranching.config import DatabaseConfig
from dbranching.database.models import (
    CompressionType,
    SnapshotFormat,
    SnapshotOptions,
    RestoreOptions,
)
from dbranching.database.sqlite import SQLiteAdapter
from dbranching.exceptions import (
    DatabaseAdapterError,
    DatabaseConnectionError,
    DatabaseTimeoutError,
    SnapshotError,
)


class TestSQLiteAdapterInit:
    """Test SQLite adapter initialization."""
    
    def test_valid_initialization(self):
        """Test valid adapter initialization."""
        config = DatabaseConfig(
            driver="sqlite",
            database="/tmp/test.db"
        )
        
        adapter = SQLiteAdapter(config)
        assert adapter.config == config
        assert adapter._connection is None
        assert str(adapter.db_path) == "/tmp/test.db"
    
    def test_invalid_driver_initialization(self):
        """Test initialization with invalid driver."""
        config = DatabaseConfig(
            driver="postgresql",  # Wrong driver
            database="test.db"
        )
        
        with pytest.raises(DatabaseAdapterError) as exc_info:
            SQLiteAdapter(config)
        
        assert "Invalid driver for SQLite adapter" in str(exc_info.value)
        assert "postgresql" in str(exc_info.value)
    
    def test_relative_path_resolution(self):
        """Test that database path is resolved to absolute path."""
        config = DatabaseConfig(
            driver="sqlite",
            database="test.db"
        )
        
        adapter = SQLiteAdapter(config)
        assert adapter.db_path.is_absolute()
        assert adapter.db_path.name == "test.db"
    
    def test_timeout_parsing(self):
        """Test timeout string parsing."""
        config = DatabaseConfig(
            driver="sqlite",
            database="test.db",
            connect_timeout="45s",
            query_timeout="2m"
        )
        
        adapter = SQLiteAdapter(config)
        assert adapter._connection_timeout == 45.0
        assert adapter._query_timeout == 120.0
    
    def test_timeout_parsing_edge_cases(self):
        """Test edge cases in timeout parsing."""
        # Test hours
        assert SQLiteAdapter._parse_timeout("1h") == 3600.0
        
        # Test numeric only
        assert SQLiteAdapter._parse_timeout("30") == 30.0
        
        # Test decimal
        assert SQLiteAdapter._parse_timeout("1.5m") == 90.0


class TestSQLiteAdapterConnection:
    """Test SQLite adapter connection methods."""
    
    @pytest.mark.asyncio
    async def test_successful_connection(self):
        """Test successful database connection."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            config = DatabaseConfig(driver="sqlite", database=db_path)
            adapter = SQLiteAdapter(config)
            
            with patch('dbranching.database.sqlite.aiosqlite.connect') as mock_connect:
                mock_conn = AsyncMock()
                mock_connect.return_value = mock_conn
                
                result = await adapter.connect()
                
                assert result is True
                assert adapter._connection == mock_conn
                
                # Verify SQLite pragmas were set
                expected_calls = [
                    (("PRAGMA journal_mode=WAL",), {}),
                    (("PRAGMA synchronous=NORMAL",), {}),
                    (("PRAGMA foreign_keys=ON",), {}),
                    (("PRAGMA temp_store=MEMORY",), {}),
                ]
                
                # Check that execute was called with these pragmas
                execute_calls = mock_conn.execute.call_args_list[:4]
                for (expected_args, expected_kwargs), actual_call in zip(expected_calls, execute_calls):
                    assert actual_call[0] == expected_args
                
                mock_conn.commit.assert_called_once()
                mock_conn.execute.assert_called_with("SELECT 1")
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_connection_timeout(self):
        """Test connection timeout handling."""
        config = DatabaseConfig(
            driver="sqlite",
            database="test.db",
            connect_timeout="1s"
        )
        adapter = SQLiteAdapter(config)
        
        with patch('dbranching.database.sqlite.aiosqlite.connect') as mock_connect:
            mock_connect.side_effect = asyncio.TimeoutError()
            
            with pytest.raises(DatabaseTimeoutError):
                await adapter.connect()
    
    @pytest.mark.asyncio
    async def test_connection_failure(self):
        """Test connection failure handling."""
        config = DatabaseConfig(
            driver="sqlite",
            database="/nonexistent/path/test.db"
        )
        adapter = SQLiteAdapter(config)
        
        with patch('dbranching.database.sqlite.aiosqlite.connect') as mock_connect:
            mock_connect.side_effect = Exception("Permission denied")
            
            with pytest.raises(DatabaseConnectionError) as exc_info:
                await adapter.connect()
            
            assert "Connection failed" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test database disconnection."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        # Mock connection
        mock_conn = AsyncMock()
        adapter._connection = mock_conn
        
        await adapter.disconnect()
        
        mock_conn.close.assert_called_once()
        assert adapter._connection is None
    
    @pytest.mark.asyncio
    async def test_test_connection_success_existing_file(self):
        """Test successful connection test for existing file."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Create a valid SQLite database
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()
            
            config = DatabaseConfig(driver="sqlite", database=db_path)
            adapter = SQLiteAdapter(config)
            
            with patch('dbranching.database.sqlite.aiosqlite.connect') as mock_connect:
                mock_conn = AsyncMock()
                mock_connect.return_value = mock_conn
                
                result = await adapter.test_connection()
                
                assert result is True
                mock_conn.execute.assert_called_once_with("SELECT 1")
                mock_conn.close.assert_called_once()
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_test_connection_nonexistent_file(self):
        """Test connection test for nonexistent file."""
        config = DatabaseConfig(driver="sqlite", database="/tmp/nonexistent.db")
        adapter = SQLiteAdapter(config)
        
        with patch.object(Path, 'exists', return_value=False), \
             patch('os.access', return_value=True):
            result = await adapter.test_connection()
            assert result is True  # SQLite can create the file
    
    @pytest.mark.asyncio
    async def test_test_connection_no_write_permission(self):
        """Test connection test with no write permission."""
        config = DatabaseConfig(driver="sqlite", database="/tmp/test.db")
        adapter = SQLiteAdapter(config)
        
        with patch.object(Path, 'exists', return_value=False), \
             patch('os.access', return_value=False):
            result = await adapter.test_connection()
            assert result is False
    
    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        """Test connection test failure."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        with patch('dbranching.database.sqlite.aiosqlite.connect') as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")
            
            result = await adapter.test_connection()
            
            assert result is False


class TestSQLiteDatabaseInfo:
    """Test database info retrieval."""
    
    @pytest.mark.asyncio
    async def test_get_database_info_success(self):
        """Test successful database info retrieval."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            config = DatabaseConfig(driver="sqlite", database=db_path)
            adapter = SQLiteAdapter(config)
            
            # Mock connection and cursors
            mock_conn = AsyncMock()
            adapter._connection = mock_conn
            
            # Mock cursor responses for different queries
            def mock_execute_factory(responses):
                """Factory to create mock execute with multiple responses."""
                response_iter = iter(responses)
                
                async def mock_execute(query):
                    mock_cursor = AsyncMock()
                    mock_cursor.fetchone.return_value = next(response_iter)
                    return mock_cursor
                
                return mock_execute
            
            responses = [
                ("3.39.4",),  # sqlite_version()
                (5,),  # Table count
                ([("seq", "main", "main", "/tmp/test.db", "")],),  # database_list
                ("wal",), ("2",), ("1",), ("4096",), ("-2000",),  # PRAGMA responses
            ]
            
            mock_conn.execute.side_effect = mock_execute_factory(responses)
            
            # Mock file stat
            with patch.object(Path, 'stat') as mock_stat:
                mock_stat.return_value.st_size = 8192
                with patch.object(adapter.db_path, 'exists', return_value=True):
                    
                    db_info = await adapter.get_database_info()
                    
                    assert db_info.name == db_path
                    assert db_info.version == "3.39.4"
                    assert db_info.size_bytes == 8192
                    assert db_info.table_count == 5
                    assert db_info.schema_count == 1
                    assert db_info.connection_count == 1
                    assert db_info.encoding == "UTF-8"
                    assert db_info.collation == "BINARY"
                    assert db_info.timezone == "UTC"
                    assert db_info.uptime_seconds is None
                    assert "main" in db_info.schemas
                    assert db_info.extensions == []
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_get_database_info_auto_connect(self):
        """Test that get_database_info connects automatically."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        assert adapter._connection is None
        
        with patch.object(adapter, 'connect') as mock_connect, \
             patch.object(adapter, '_connection', AsyncMock()):
            mock_connect.return_value = True
            
            # Mock all the database queries
            mock_cursor = AsyncMock()
            mock_cursor.fetchone.return_value = ("3.39.4",)
            adapter._connection.execute.return_value = mock_cursor
            
            with patch.object(Path, 'stat') as mock_stat, \
                 patch.object(adapter.db_path, 'exists', return_value=True):
                mock_stat.return_value.st_size = 1024
                
                await adapter.get_database_info()
                
                mock_connect.assert_called_once()


class TestSQLiteSnapshot:
    """Test SQLite snapshot operations."""
    
    @pytest.mark.asyncio
    async def test_create_file_copy_snapshot(self):
        """Test creating snapshot via file copy."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Create test database
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
            conn.commit()
            conn.close()
            
            config = DatabaseConfig(driver="sqlite", database=db_path)
            adapter = SQLiteAdapter(config)
            
            # Mock database info
            mock_db_info = Mock()
            mock_db_info.size_bytes = 8192
            mock_db_info.table_count = 1
            mock_db_info.schema_count = 1
            mock_db_info.version = "3.39.4"
            
            output_path = Path("/tmp/test_snapshot.db")
            
            with patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
                 patch.object(adapter, '_get_sqlite_version', return_value="3.39.4"), \
                 patch('sqlite3.connect') as mock_sqlite3_connect, \
                 patch.object(output_path.parent, 'mkdir'), \
                 patch.object(output_path, 'exists', return_value=True), \
                 patch.object(output_path, 'stat') as mock_stat:
                
                # Mock sqlite3 backup
                mock_source = Mock()
                mock_target = Mock()
                mock_sqlite3_connect.side_effect = [mock_source, mock_target]
                
                mock_stat.return_value.st_size = 8192
                
                options = SnapshotOptions(format=SnapshotFormat.CUSTOM)
                result = await adapter.create_snapshot(output_path, options)
                
                assert result.success is True
                assert result.snapshot_path == output_path
                assert result.size_bytes == 8192
                assert result.database_size_bytes == 8192
                assert result.tables_included == 1
                assert result.schemas_included == 1
                
                # Verify backup was called
                mock_source.backup.assert_called_once_with(mock_target)
                mock_source.close.assert_called_once()
                mock_target.close.assert_called_once()
        finally:
            Path(db_path).unlink(missing_ok=True)
            Path("/tmp/test_snapshot.db").unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_create_sql_dump_snapshot(self):
        """Test creating snapshot as SQL dump."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        # Mock connection and database info
        mock_conn = AsyncMock()
        adapter._connection = mock_conn
        
        mock_db_info = Mock()
        mock_db_info.size_bytes = 4096
        mock_db_info.table_count = 2
        mock_db_info.schema_count = 1
        mock_db_info.version = "3.39.4"
        
        # Mock cursor responses for table schemas
        schema_cursor = AsyncMock()
        schema_cursor.fetchall.return_value = [
            ("CREATE TABLE users (id INTEGER, name TEXT)",),
            ("CREATE TABLE orders (id INTEGER, user_id INTEGER)",)
        ]
        
        # Mock cursor responses for table names
        tables_cursor = AsyncMock()
        tables_cursor.fetchall.return_value = [
            ("users",),
            ("orders",)
        ]
        
        # Mock cursor responses for table data
        users_data_cursor = AsyncMock()
        users_data_cursor.fetchall.return_value = [
            (1, "Alice"),
            (2, "Bob")
        ]
        
        orders_data_cursor = AsyncMock()
        orders_data_cursor.fetchall.return_value = [
            (1, 1),
            (2, 2)
        ]
        
        # Mock column info cursors
        users_columns_cursor = AsyncMock()
        users_columns_cursor.fetchall.return_value = [
            (0, "id", "INTEGER", 0, None, 0),
            (1, "name", "TEXT", 0, None, 0)
        ]
        
        orders_columns_cursor = AsyncMock()
        orders_columns_cursor.fetchall.return_value = [
            (0, "id", "INTEGER", 0, None, 0),
            (1, "user_id", "INTEGER", 0, None, 0)
        ]
        
        # Set up execute calls to return appropriate cursors
        def execute_side_effect(query):
            if "SELECT sql FROM sqlite_master" in query:
                return schema_cursor
            elif "SELECT name FROM sqlite_master" in query:
                return tables_cursor
            elif "SELECT * FROM users" in query:
                return users_data_cursor
            elif "SELECT * FROM orders" in query:
                return orders_data_cursor
            elif "PRAGMA table_info(users)" in query:
                return users_columns_cursor
            elif "PRAGMA table_info(orders)" in query:
                return orders_columns_cursor
            else:
                mock_cursor = AsyncMock()
                return mock_cursor
        
        mock_conn.execute.side_effect = execute_side_effect
        
        output_path = Path("/tmp/test_snapshot.sql")
        
        with patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
             patch.object(adapter, '_get_sqlite_version', return_value="3.39.4"), \
             patch('builtins.open', mock_open()) as mock_file, \
             patch.object(output_path.parent, 'mkdir'), \
             patch.object(output_path, 'exists', return_value=True), \
             patch.object(output_path, 'stat') as mock_stat:
            
            mock_stat.return_value.st_size = 2048
            
            options = SnapshotOptions(format=SnapshotFormat.PLAIN)
            result = await adapter.create_snapshot(output_path, options)
            
            assert result.success is True
            assert result.snapshot_path == output_path
            assert result.size_bytes == 2048
            
            # Verify file was written
            mock_file.assert_called_once_with(output_path, 'w', encoding='utf-8')
    
    @pytest.mark.asyncio
    async def test_create_compressed_snapshot(self):
        """Test creating compressed snapshot."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        mock_db_info = Mock()
        mock_db_info.size_bytes = 4096
        mock_db_info.table_count = 1
        mock_db_info.schema_count = 1
        mock_db_info.version = "3.39.4"
        
        output_path = Path("/tmp/test_snapshot.db")
        compressed_path = Path("/tmp/test_snapshot.db.gz")
        
        with patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
             patch.object(adapter, '_create_file_copy') as mock_create, \
             patch.object(adapter, '_compress_file', return_value=compressed_path), \
             patch.object(adapter, '_get_sqlite_version', return_value="3.39.4"), \
             patch.object(output_path.parent, 'mkdir'), \
             patch.object(compressed_path, 'exists', return_value=True), \
             patch.object(compressed_path, 'stat') as mock_stat, \
             patch.object(output_path, 'unlink') as mock_unlink:
            
            mock_stat.return_value.st_size = 1024  # Compressed size
            
            options = SnapshotOptions(compression=CompressionType.GZIP)
            result = await adapter.create_snapshot(output_path, options)
            
            assert result.success is True
            assert result.snapshot_path == compressed_path
            assert result.size_bytes == 1024
            assert result.compressed_size_bytes == 1024
            assert result.compression_ratio == 4.0  # 4096 / 1024
            
            # Verify original file was removed after compression
            mock_unlink.assert_called_once()


class TestSQLiteRestore:
    """Test SQLite restore operations."""
    
    @pytest.mark.asyncio
    async def test_restore_from_file_copy(self):
        """Test restoring from SQLite file copy."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            snapshot_path = Path(f.name)
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            target_path = f.name
        
        try:
            # Create test snapshot database
            conn = sqlite3.connect(str(snapshot_path))
            conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO users VALUES (1, 'Alice')")
            conn.commit()
            conn.close()
            
            config = DatabaseConfig(driver="sqlite", database=target_path)
            adapter = SQLiteAdapter(config)
            
            # Mock validation result
            mock_validation = Mock()
            mock_validation.valid = True
            
            # Mock database info
            mock_db_info = Mock()
            mock_db_info.table_count = 1
            mock_db_info.schema_count = 1
            mock_db_info.version = "3.39.4"
            
            with patch.object(adapter, 'validate_snapshot', return_value=mock_validation), \
                 patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
                 patch.object(adapter, '_get_sqlite_version', return_value="3.39.4"), \
                 patch.object(adapter, '_is_compressed_file', return_value=False), \
                 patch.object(adapter, '_is_sql_dump', return_value=False), \
                 patch('shutil.copy2') as mock_copy:
                
                options = RestoreOptions()
                result = await adapter.restore_snapshot(snapshot_path, options)
                
                assert result.success is True
                assert result.snapshot_path == snapshot_path
                assert result.tables_restored == 1
                assert result.schemas_restored == 1
                
                mock_copy.assert_called_once_with(str(snapshot_path), target_path)
        finally:
            snapshot_path.unlink(missing_ok=True)
            Path(target_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_restore_from_sql_dump(self):
        """Test restoring from SQL dump."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        snapshot_path = Path("/tmp/test_snapshot.sql")
        
        # Mock validation result
        mock_validation = Mock()
        mock_validation.valid = True
        
        # Mock database info
        mock_db_info = Mock()
        mock_db_info.table_count = 1
        mock_db_info.schema_count = 1
        mock_db_info.version = "3.39.4"
        
        # Mock connection
        mock_conn = AsyncMock()
        adapter._connection = mock_conn
        
        sql_content = """
        CREATE TABLE users (id INTEGER, name TEXT);
        INSERT INTO users VALUES (1, 'Alice');
        INSERT INTO users VALUES (2, 'Bob');
        """
        
        with patch.object(adapter, 'validate_snapshot', return_value=mock_validation), \
             patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
             patch.object(adapter, '_get_sqlite_version', return_value="3.39.4"), \
             patch.object(adapter, '_is_compressed_file', return_value=False), \
             patch.object(adapter, '_is_sql_dump', return_value=True), \
             patch('builtins.open', mock_open(read_data=sql_content)), \
             patch.object(snapshot_path, 'exists', return_value=True):
            
            options = RestoreOptions()
            result = await adapter.restore_snapshot(snapshot_path, options)
            
            assert result.success is True
            assert result.snapshot_path == snapshot_path
            assert result.tables_restored == 1
            assert result.schemas_restored == 1
            
            # Verify SQL statements were executed
            expected_statements = [
                "CREATE TABLE users (id INTEGER, name TEXT)",
                "INSERT INTO users VALUES (1, 'Alice')",
                "INSERT INTO users VALUES (2, 'Bob')"
            ]
            
            # Check that execute was called with each statement
            execute_calls = [call[0][0] for call in mock_conn.execute.call_args_list]
            for stmt in expected_statements:
                assert stmt in execute_calls
            
            mock_conn.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_restore_with_clean_option(self):
        """Test restore with clean option."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            target_path = f.name
        
        try:
            config = DatabaseConfig(driver="sqlite", database=target_path)
            adapter = SQLiteAdapter(config)
            
            snapshot_path = Path("/tmp/test_snapshot.db")
            
            mock_validation = Mock()
            mock_validation.valid = True
            
            mock_db_info = Mock()
            mock_db_info.table_count = 1
            mock_db_info.schema_count = 1
            mock_db_info.version = "3.39.4"
            
            with patch.object(adapter, 'validate_snapshot', return_value=mock_validation), \
                 patch.object(adapter, 'get_database_info', return_value=mock_db_info), \
                 patch.object(adapter, '_get_sqlite_version', return_value="3.39.4"), \
                 patch.object(adapter, '_is_compressed_file', return_value=False), \
                 patch.object(adapter, '_is_sql_dump', return_value=False), \
                 patch.object(snapshot_path, 'exists', return_value=True), \
                 patch.object(adapter.db_path, 'exists', return_value=True), \
                 patch('shutil.move') as mock_move, \
                 patch('shutil.copy2') as mock_copy:
                
                options = RestoreOptions(clean=True)
                await adapter.restore_snapshot(snapshot_path, options)
                
                # Verify existing database was backed up
                expected_backup = adapter.db_path.with_suffix('.backup')
                mock_move.assert_called_once_with(str(adapter.db_path), str(expected_backup))
        finally:
            Path(target_path).unlink(missing_ok=True)


class TestSQLiteValidation:
    """Test SQLite snapshot validation."""
    
    @pytest.mark.asyncio
    async def test_validate_sqlite_file_success(self):
        """Test successful SQLite file validation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            test_db_path = f.name
        
        try:
            # Create valid SQLite database
            conn = sqlite3.connect(test_db_path)
            conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
            conn.execute("CREATE TABLE orders (id INTEGER, user_id INTEGER)")
            conn.close()
            
            config = DatabaseConfig(driver="sqlite", database="test.db")
            adapter = SQLiteAdapter(config)
            
            snapshot_path = Path(test_db_path)
            
            with patch.object(adapter, '_calculate_file_checksum', return_value="abc123"):
                result = await adapter.validate_snapshot(snapshot_path)
                
                assert result.valid is True
                assert result.format_valid is True
                assert result.table_count == 2
                assert result.schema_count == 1
                assert result.checksum == "abc123"
        finally:
            Path(test_db_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_validate_sql_dump_success(self):
        """Test successful SQL dump validation."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        snapshot_path = Path("/tmp/test.sql")
        
        sql_content = """
        -- SQLite database dump
        CREATE TABLE users (id INTEGER, name TEXT);
        CREATE TABLE orders (id INTEGER, user_id INTEGER);
        INSERT INTO users VALUES (1, 'Alice');
        """
        
        with patch('builtins.open', mock_open(read_data=sql_content)), \
             patch.object(snapshot_path, 'exists', return_value=True), \
             patch.object(snapshot_path, 'stat') as mock_stat, \
             patch.object(adapter, '_calculate_file_checksum', return_value="def456"), \
             patch.object(adapter, '_is_compressed_file', return_value=False), \
             patch.object(adapter, '_is_sql_dump', return_value=True):
            
            mock_stat.return_value.st_size = 1024
            
            result = await adapter.validate_snapshot(snapshot_path)
            
            assert result.valid is True
            assert result.format_valid is True
            assert result.table_count == 2
            assert result.schema_count == 1
            assert result.checksum == "def456"
    
    @pytest.mark.asyncio
    async def test_validate_invalid_sqlite_file(self):
        """Test validation of invalid SQLite file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"This is not a SQLite file")
            test_file_path = f.name
        
        try:
            config = DatabaseConfig(driver="sqlite", database="test.db")
            adapter = SQLiteAdapter(config)
            
            snapshot_path = Path(test_file_path)
            
            with patch.object(adapter, '_calculate_file_checksum', return_value="invalid123"):
                result = await adapter.validate_snapshot(snapshot_path)
                
                assert result.valid is False
                assert result.format_valid is False
                assert "File is not a valid SQLite database" in result.error_message
        finally:
            Path(test_file_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_validate_compressed_file(self):
        """Test validation of compressed SQLite file."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        compressed_path = Path("/tmp/test.db.gz")
        decompressed_path = Path("/tmp/test.db")
        
        with patch.object(adapter, '_is_compressed_file', return_value=True), \
             patch.object(adapter, '_decompress_file', return_value=decompressed_path), \
             patch.object(adapter, '_validate_sqlite_file') as mock_validate, \
             patch.object(compressed_path, 'exists', return_value=True), \
             patch.object(decompressed_path, 'unlink') as mock_unlink:
            
            mock_validate.return_value = Mock(valid=True, format_valid=True)
            
            await adapter.validate_snapshot(compressed_path)
            
            # Verify decompression was called and temp file was cleaned up
            adapter._decompress_file.assert_called_once_with(compressed_path)
            mock_unlink.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_validate_nonexistent_file(self):
        """Test validation of nonexistent file."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        snapshot_path = Path("/tmp/nonexistent.db")
        
        with patch.object(snapshot_path, 'exists', return_value=False):
            result = await adapter.validate_snapshot(snapshot_path)
            
            assert result.valid is False
            assert result.format_valid is False
            assert result.error_message == "Snapshot file not found"


class TestSQLiteUtilities:
    """Test SQLite adapter utility methods."""
    
    @pytest.mark.asyncio
    async def test_get_supported_formats(self):
        """Test getting supported formats."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        formats = await adapter.get_supported_formats()
        
        assert "custom" in formats  # SQLite database file
        assert "plain" in formats   # SQL dump
    
    @pytest.mark.asyncio
    async def test_estimate_snapshot_size(self):
        """Test snapshot size estimation."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        # Mock database info
        mock_db_info = Mock()
        mock_db_info.size_bytes = 1000000
        
        with patch.object(adapter, 'get_database_info', return_value=mock_db_info):
            # Test without options
            size = await adapter.estimate_snapshot_size()
            assert size == 1000000
            
            # Test SQL dump format (larger)
            options = SnapshotOptions(format=SnapshotFormat.PLAIN)
            size = await adapter.estimate_snapshot_size(options)
            assert size == 2500000  # 2.5x larger for SQL text
            
            # Test with gzip compression on SQL dump
            options = SnapshotOptions(
                format=SnapshotFormat.PLAIN,
                compression=CompressionType.GZIP
            )
            size = await adapter.estimate_snapshot_size(options)
            assert size == 500000  # 80% compression on SQL text
            
            # Test schema only
            options = SnapshotOptions(schema_only=True)
            size = await adapter.estimate_snapshot_size(options)
            assert size == 10000  # 1% of original size
    
    @pytest.mark.asyncio
    async def test_list_schemas(self):
        """Test listing database schemas."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        # Mock connection
        mock_conn = AsyncMock()
        adapter._connection = mock_conn
        
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            (0, "main", "/tmp/test.db", ""),
            (1, "temp", "", ""),
            (2, "attached_db", "/tmp/other.db", "")
        ]
        mock_conn.execute.return_value = mock_cursor
        
        schemas = await adapter.list_schemas()
        
        assert len(schemas) == 3
        assert "main" in schemas
        assert "temp" in schemas
        assert "attached_db" in schemas
    
    @pytest.mark.asyncio
    async def test_list_tables(self):
        """Test listing database tables."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        # Mock connection
        mock_conn = AsyncMock()
        adapter._connection = mock_conn
        
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [
            ("users",),
            ("orders",),
            ("products",)
        ]
        mock_conn.execute.return_value = mock_cursor
        
        # Test without schema (should return unqualified names)
        tables = await adapter.list_tables()
        
        assert len(tables) == 3
        assert "users" in tables
        assert "orders" in tables
        assert "products" in tables
        
        # Test with schema (should return qualified names)
        tables = await adapter.list_tables("attached_db")
        
        assert len(tables) == 3
        assert "attached_db.users" in tables
        assert "attached_db.orders" in tables
        assert "attached_db.products" in tables
    
    def test_is_compressed_file(self):
        """Test compressed file detection."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        assert adapter._is_compressed_file(Path("/tmp/test.gz")) is True
        assert adapter._is_compressed_file(Path("/tmp/test.bz2")) is True
        assert adapter._is_compressed_file(Path("/tmp/test.xz")) is True
        assert adapter._is_compressed_file(Path("/tmp/test.zst")) is True
        assert adapter._is_compressed_file(Path("/tmp/test.db")) is False
        assert adapter._is_compressed_file(Path("/tmp/test.sql")) is False
    
    def test_is_sql_dump(self):
        """Test SQL dump detection."""
        config = DatabaseConfig(driver="sqlite", database="test.db")
        adapter = SQLiteAdapter(config)
        
        # Test with CREATE TABLE
        with patch('builtins.open', mock_open(read_data="CREATE TABLE users (id INTEGER);")):
            assert adapter._is_sql_dump(Path("/tmp/test.sql")) is True
        
        # Test with INSERT INTO
        with patch('builtins.open', mock_open(read_data="INSERT INTO users VALUES (1, 'Alice');")):
            assert adapter._is_sql_dump(Path("/tmp/test.sql")) is True
        
        # Test with non-SQL content
        with patch('builtins.open', mock_open(read_data="This is not SQL")):
            assert adapter._is_sql_dump(Path("/tmp/test.txt")) is False
        
        # Test with file read error
        with patch('builtins.open', side_effect=IOError("Cannot read file")):
            assert adapter._is_sql_dump(Path("/tmp/test.sql")) is False


def mock_open(read_data=''):
    """Helper to create mock open."""
    from unittest.mock import mock_open as _mock_open
    return _mock_open(read_data=read_data)