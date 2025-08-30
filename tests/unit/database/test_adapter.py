"""Tests for database adapter abstract base class."""

import pytest
from pathlib import Path
from typing import Optional

from dbranching.database.adapter import DatabaseAdapter
from dbranching.database.models import (
    DatabaseInfo,
    ProgressCallback,
    RestoreOptions,
    RestoreResult,
    SnapshotOptions,
    SnapshotResult,
    ValidationResult,
)


class MockDatabaseAdapter(DatabaseAdapter):
    """Mock implementation of DatabaseAdapter for testing."""
    
    def __init__(self, should_connect: bool = True):
        """Initialize mock adapter."""
        self.should_connect = should_connect
        self._connected = False
        self.connect_called = False
        self.disconnect_called = False
    
    async def connect(self) -> bool:
        """Mock connect method."""
        self.connect_called = True
        self._connected = self.should_connect
        return self.should_connect
    
    async def disconnect(self) -> None:
        """Mock disconnect method."""
        self.disconnect_called = True
        self._connected = False
    
    async def test_connection(self) -> bool:
        """Mock test connection method."""
        return self.should_connect
    
    async def create_snapshot(
        self,
        output_path: Path,
        options: Optional[SnapshotOptions] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> SnapshotResult:
        """Mock create snapshot method."""
        return SnapshotResult(
            success=True,
            snapshot_path=output_path,
            size_bytes=1024,
            duration_seconds=1.0,
            database_size_bytes=2048,
            tables_included=1,
            schemas_included=1
        )
    
    async def restore_snapshot(
        self,
        snapshot_path: Path,
        options: Optional[RestoreOptions] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> RestoreResult:
        """Mock restore snapshot method."""
        return RestoreResult(
            success=True,
            snapshot_path=snapshot_path,
            duration_seconds=1.0,
            tables_restored=1,
            schemas_restored=1
        )
    
    async def get_database_info(self) -> DatabaseInfo:
        """Mock get database info method."""
        return DatabaseInfo(
            name="test",
            version="1.0",
            size_bytes=1024,
            table_count=1,
            schema_count=1,
            connection_count=1,
            encoding="UTF8",
            collation="C",
            timezone="UTC"
        )
    
    async def validate_snapshot(self, snapshot_path: Path) -> ValidationResult:
        """Mock validate snapshot method."""
        return ValidationResult(
            valid=True,
            snapshot_path=snapshot_path,
            format_valid=True,
            size_bytes=1024,
            compatible=True
        )
    
    async def get_supported_formats(self) -> set[str]:
        """Mock get supported formats method."""
        return {"custom", "tar", "plain"}
    
    async def estimate_snapshot_size(self, options: Optional[SnapshotOptions] = None) -> int:
        """Mock estimate snapshot size method."""
        return 1024
    
    async def list_schemas(self) -> list[str]:
        """Mock list schemas method."""
        return ["public"]
    
    async def list_tables(self, schema: Optional[str] = None) -> list[str]:
        """Mock list tables method."""
        return ["users", "orders"]


class TestDatabaseAdapter:
    """Test DatabaseAdapter abstract base class."""
    
    @pytest.mark.asyncio
    async def test_async_context_manager_success(self):
        """Test async context manager with successful connection."""
        adapter = MockDatabaseAdapter(should_connect=True)
        
        async with adapter:
            assert adapter.connect_called is True
            assert adapter._connected is True
        
        assert adapter.disconnect_called is True
        assert adapter._connected is False
    
    @pytest.mark.asyncio
    async def test_async_context_manager_connection_failure(self):
        """Test async context manager with connection failure."""
        adapter = MockDatabaseAdapter(should_connect=False)
        
        async with adapter:
            assert adapter.connect_called is True
            assert adapter._connected is False
        
        assert adapter.disconnect_called is True
    
    @pytest.mark.asyncio
    async def test_basic_operations(self):
        """Test basic adapter operations."""
        adapter = MockDatabaseAdapter()
        
        # Test connection methods
        assert await adapter.test_connection() is True
        assert await adapter.connect() is True
        
        # Test database info
        info = await adapter.get_database_info()
        assert info.name == "test"
        assert info.version == "1.0"
        
        # Test schema and table listing
        schemas = await adapter.list_schemas()
        assert "public" in schemas
        
        tables = await adapter.list_tables()
        assert "users" in tables
        assert "orders" in tables
        
        # Test supported formats
        formats = await adapter.get_supported_formats()
        assert "custom" in formats
        
        # Test size estimation
        size = await adapter.estimate_snapshot_size()
        assert size == 1024
        
        # Cleanup
        await adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_snapshot_operations(self):
        """Test snapshot create and restore operations."""
        adapter = MockDatabaseAdapter()
        await adapter.connect()
        
        # Test snapshot creation
        snapshot_path = Path("/tmp/test.dump")
        options = SnapshotOptions(verbose=True)
        
        result = await adapter.create_snapshot(snapshot_path, options)
        assert result.success is True
        assert result.snapshot_path == snapshot_path
        
        # Test snapshot validation
        validation = await adapter.validate_snapshot(snapshot_path)
        assert validation.valid is True
        assert validation.snapshot_path == snapshot_path
        
        # Test snapshot restore
        restore_options = RestoreOptions(verbose=True)
        restore_result = await adapter.restore_snapshot(snapshot_path, restore_options)
        assert restore_result.success is True
        assert restore_result.snapshot_path == snapshot_path
        
        await adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_progress_callback(self):
        """Test operations with progress callback."""
        adapter = MockDatabaseAdapter()
        await adapter.connect()
        
        callback = ProgressCallback()
        snapshot_path = Path("/tmp/test.dump")
        
        # Test snapshot with progress callback
        result = await adapter.create_snapshot(
            snapshot_path, 
            progress_callback=callback
        )
        assert result.success is True
        
        # Test restore with progress callback
        restore_result = await adapter.restore_snapshot(
            snapshot_path,
            progress_callback=callback
        )
        assert restore_result.success is True
        
        await adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_schema_filtering(self):
        """Test schema filtering in operations."""
        adapter = MockDatabaseAdapter()
        await adapter.connect()
        
        # Test with schema filtering
        options = SnapshotOptions(
            include_schemas={"public"},
            exclude_schemas={"test"}
        )
        
        snapshot_path = Path("/tmp/filtered.dump")
        result = await adapter.create_snapshot(snapshot_path, options)
        assert result.success is True
        
        # Test restore with schema filtering
        restore_options = RestoreOptions(
            include_schemas={"public"},
            exclude_schemas={"temp"}
        )
        
        restore_result = await adapter.restore_snapshot(snapshot_path, restore_options)
        assert restore_result.success is True
        
        await adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_table_filtering(self):
        """Test table filtering in operations."""
        adapter = MockDatabaseAdapter()
        await adapter.connect()
        
        # Test with table filtering
        options = SnapshotOptions(
            include_tables={"users", "orders"},
            exclude_tables={"logs"}
        )
        
        snapshot_path = Path("/tmp/tables.dump")
        result = await adapter.create_snapshot(snapshot_path, options)
        assert result.success is True
        
        await adapter.disconnect()
    
    @pytest.mark.asyncio
    async def test_list_tables_with_schema(self):
        """Test listing tables with specific schema."""
        adapter = MockDatabaseAdapter()
        await adapter.connect()
        
        # Test listing tables in specific schema
        tables = await adapter.list_tables("public")
        assert isinstance(tables, list)
        assert len(tables) > 0
        
        await adapter.disconnect()


class TestAbstractMethods:
    """Test that DatabaseAdapter is properly abstract."""
    
    def test_cannot_instantiate_abstract_class(self):
        """Test that DatabaseAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError):
            DatabaseAdapter()
    
    def test_must_implement_all_methods(self):
        """Test that subclasses must implement all abstract methods."""
        
        class IncompleteAdapter(DatabaseAdapter):
            """Incomplete adapter missing some methods."""
            
            async def connect(self) -> bool:
                return True
        
        # Should raise TypeError when trying to instantiate
        with pytest.raises(TypeError):
            IncompleteAdapter()