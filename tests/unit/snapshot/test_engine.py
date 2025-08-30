"""Tests for the core snapshot engine."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.dbranching.config import DatabaseConfig
from src.dbranching.snapshot.engine import SnapshotEngine
from src.dbranching.snapshot.models import (
    SnapshotCreateOptions,
    SnapshotRestoreOptions,
    CompressionType,
    SnapshotStatus
)
from src.dbranching.exceptions import SnapshotError, ValidationError


class TestSnapshotEngine:
    """Test cases for the SnapshotEngine class."""
    
    @pytest.fixture
    def db_config(self):
        """Create test database configuration."""
        return DatabaseConfig(
            driver="postgresql",
            host="localhost",
            port=5432,
            database="test_db",
            username="test_user",
            password="test_pass"
        )
    
    @pytest.fixture
    async def engine(self, db_config):
        """Create test snapshot engine."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "snapshots"
            temp_path = Path(temp_dir) / "temp"
            
            engine = SnapshotEngine(
                database_config=db_config,
                storage_base_path=storage_path,
                temp_dir=temp_path
            )
            
            yield engine
    
    @pytest.fixture
    def create_options(self):
        """Create test snapshot creation options."""
        return SnapshotCreateOptions(
            name="test_snapshot",
            description="Test snapshot for unit testing",
            tags=["test", "unit"],
            compression=CompressionType.GZIP,
            compression_level=6,
            verify_integrity=True,
            atomic=True
        )
    
    @pytest.fixture
    def restore_options(self):
        """Create test snapshot restore options."""
        return SnapshotRestoreOptions(
            clean_before_restore=False,
            verify_integrity=True,
            atomic=True,
            backup_before_restore=False
        )
    
    async def test_engine_initialization(self, db_config):
        """Test snapshot engine initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "snapshots"
            
            engine = SnapshotEngine(
                database_config=db_config,
                storage_base_path=storage_path
            )
            
            assert engine.database_config == db_config
            assert engine.storage_base_path == storage_path
            assert storage_path.exists()
            assert engine.adapter is not None
            assert engine.atomic_manager is not None
            assert engine.compression_engine is not None
            assert engine.metadata_manager is not None
    
    async def test_unsupported_database_driver(self):
        """Test initialization with unsupported database driver."""
        # We need to create config with a valid driver first, then mock it
        config = DatabaseConfig(driver="postgresql")
        config.driver = "unsupported"  # Bypass pydantic validation
        
        with pytest.raises(Exception):
            SnapshotEngine(config)
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_create_snapshot_success(self, mock_adapter_factory, engine, create_options):
        """Test successful snapshot creation."""
        # Mock database adapter
        mock_adapter = AsyncMock()
        mock_adapter.connect.return_value = None
        mock_adapter.disconnect.return_value = None
        mock_adapter.get_database_info.return_value = MagicMock(
            version="15.3",
            size_bytes=1000000,
            table_count=10,
            schema_count=2,
            encoding="UTF8",
            collation="en_US.UTF-8",
            timezone="UTC",
            extensions=["uuid-ossp"]
        )
        mock_adapter.create_snapshot.return_value = MagicMock(
            success=True,
            error_message=None
        )
        
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Mock progress callback
        progress_reports = []
        def progress_callback(report):
            progress_reports.append(report)
        
        # Create snapshot
        result = await engine.create_snapshot(create_options, progress_callback)
        
        # Verify result
        assert result.name == "test_snapshot"
        assert result.status == SnapshotStatus.COMPLETED
        assert result.description == "Test snapshot for unit testing"
        assert "test" in result.tags
        assert "unit" in result.tags
        
        # Verify progress was reported
        assert len(progress_reports) > 0
        
        # Verify adapter methods were called
        mock_adapter.connect.assert_called_once()
        mock_adapter.get_database_info.assert_called_once()
        mock_adapter.disconnect.assert_called_once()
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_create_snapshot_validation_error(self, mock_adapter_factory, engine):
        """Test snapshot creation with invalid options."""
        mock_adapter = AsyncMock()
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Invalid options (both schema_only and data_only)
        invalid_options = SnapshotCreateOptions(
            name="invalid_snapshot",
            schema_only=True,
            data_only=True
        )
        
        with pytest.raises(ValidationError):
            await engine.create_snapshot(invalid_options)
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_create_snapshot_existing_snapshot_error(self, mock_adapter_factory, engine):
        """Test snapshot creation when snapshot already exists."""
        mock_adapter = AsyncMock()
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Create directory to simulate existing snapshot
        existing_snapshot_path = engine.storage_base_path / "existing_snapshot"
        existing_snapshot_path.mkdir(parents=True)
        
        options = SnapshotCreateOptions(
            name="existing_snapshot",
            atomic=False  # Non-atomic should fail if exists
        )
        
        with pytest.raises(ValidationError):
            await engine.create_snapshot(options)
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_restore_snapshot_success(self, mock_adapter_factory, engine, restore_options):
        """Test successful snapshot restoration."""
        # Mock database adapter
        mock_adapter = AsyncMock()
        mock_adapter.connect.return_value = None
        mock_adapter.disconnect.return_value = None
        mock_adapter.restore_snapshot.return_value = MagicMock(
            success=True,
            error_message=None
        )
        
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Create mock snapshot directory with metadata
        snapshot_path = engine.storage_base_path / "test_restore"
        snapshot_path.mkdir(parents=True)
        
        # Mock metadata loading
        with patch.object(engine.metadata_manager, 'load_metadata') as mock_load:
            mock_metadata = MagicMock()
            mock_metadata.created_at = "2023-01-01T00:00:00Z"
            mock_metadata.total_size_bytes = 1000000
            mock_metadata.database.type = "postgresql"
            mock_metadata.database.version = "15.3"
            mock_metadata.compression_ratio = 3.0
            mock_metadata.database.table_count = 10
            mock_metadata.database.schema_count = 2
            mock_metadata.tags = ["test"]
            mock_metadata.description = "Test snapshot"
            mock_metadata.files = [MagicMock(name="data.sql.gz")]
            
            mock_load.return_value = mock_metadata
            
            # Mock validation
            with patch.object(engine, 'validate_snapshot') as mock_validate:
                mock_validate.return_value = MagicMock(valid=True)
                
                # Restore snapshot
                result = await engine.restore_snapshot("test_restore", restore_options)
                
                # Verify result
                assert result.name == "test_restore"
                assert result.status == SnapshotStatus.COMPLETED
                
                # Verify adapter methods were called
                mock_adapter.connect.assert_called_once()
                mock_adapter.restore_snapshot.assert_called_once()
                mock_adapter.disconnect.assert_called_once()
    
    async def test_restore_snapshot_not_found(self, engine, restore_options):
        """Test restoring non-existent snapshot."""
        with pytest.raises(SnapshotError, match="Snapshot not found"):
            await engine.restore_snapshot("nonexistent", restore_options)
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_validate_snapshot_success(self, mock_adapter_factory, engine):
        """Test successful snapshot validation."""
        mock_adapter = AsyncMock()
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Create mock snapshot directory
        snapshot_path = engine.storage_base_path / "test_validate"
        snapshot_path.mkdir(parents=True)
        
        # We'll mock the metadata loading instead of creating file content
        
        # Create actual test file
        test_file = snapshot_path / "test_file.txt"
        test_file.write_text("x" * 100)
        
        # Mock metadata manager
        with patch.object(engine.metadata_manager, 'load_metadata') as mock_load:
            mock_metadata = MagicMock()
            mock_metadata.files = [MagicMock(
                name="test_file.txt",
                size_bytes=100,
                checksum="abc123"
            )]
            mock_load.return_value = mock_metadata
            
            with patch.object(engine.metadata_manager, 'validate_metadata') as mock_validate_meta:
                mock_validate_meta.return_value = []  # No warnings
                
                with patch.object(engine.metadata_manager, '_calculate_file_checksum') as mock_checksum:
                    mock_checksum.return_value = "abc123"  # Matching checksum
                    
                    # Validate snapshot
                    result = await engine.validate_snapshot("test_validate")
                    
                    # Verify result
                    assert result.valid
                    assert result.total_files == 1
                    assert result.valid_files == 1
                    assert len(result.corrupted_files) == 0
                    assert len(result.missing_files) == 0
    
    async def test_validate_snapshot_not_found(self, engine):
        """Test validation of non-existent snapshot."""
        result = await engine.validate_snapshot("nonexistent")
        
        assert not result.valid
        assert "not found" in result.error_message
        assert result.total_files == 0
        assert result.valid_files == 0
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_get_snapshot_info_success(self, mock_adapter_factory, engine):
        """Test getting snapshot information."""
        mock_adapter = AsyncMock()
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Create mock snapshot directory
        snapshot_path = engine.storage_base_path / "test_info"
        snapshot_path.mkdir(parents=True)
        
        # Mock metadata loading
        with patch.object(engine.metadata_manager, 'load_metadata') as mock_load:
            mock_metadata = MagicMock()
            mock_metadata.created_at = "2023-01-01T00:00:00Z"
            mock_metadata.total_size_bytes = 1000000
            mock_metadata.database.type = "postgresql"
            mock_metadata.database.version = "15.3"
            mock_metadata.compression_ratio = 3.0
            mock_metadata.database.table_count = 10
            mock_metadata.database.schema_count = 2
            mock_metadata.tags = ["test"]
            mock_metadata.description = "Test snapshot"
            
            mock_load.return_value = mock_metadata
            
            # Get snapshot info
            result = await engine.get_snapshot_info("test_info")
            
            # Verify result
            assert result.name == "test_info"
            assert result.status == SnapshotStatus.COMPLETED
            assert result.size_bytes == 1000000
            assert result.database_type == "postgresql"
            assert result.database_version == "15.3"
            assert result.compression_ratio == 3.0
            assert result.table_count == 10
            assert result.schema_count == 2
            assert "test" in result.tags
    
    async def test_get_snapshot_info_not_found(self, engine):
        """Test getting info for non-existent snapshot."""
        with pytest.raises(SnapshotError, match="Snapshot not found"):
            await engine.get_snapshot_info("nonexistent")
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_list_snapshots(self, mock_adapter_factory, engine):
        """Test listing all snapshots."""
        mock_adapter = AsyncMock()
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Create multiple mock snapshots
        snapshot_names = ["snapshot1", "snapshot2", "snapshot3"]
        
        for name in snapshot_names:
            snapshot_path = engine.storage_base_path / name
            snapshot_path.mkdir(parents=True)
        
        # Mock metadata loading for each snapshot
        with patch.object(engine, 'get_snapshot_info') as mock_get_info:
            mock_infos = []
            for i, name in enumerate(snapshot_names):
                mock_info = MagicMock()
                mock_info.name = name
                mock_info.created_at = f"2023-01-0{i+1}T00:00:00Z"
                mock_infos.append(mock_info)
            
            mock_get_info.side_effect = mock_infos
            
            # List snapshots
            result = await engine.list_snapshots()
            
            # Verify result
            assert len(result) == 3
            assert all(info.name in snapshot_names for info in result)
    
    async def test_list_snapshots_empty(self, engine):
        """Test listing snapshots when none exist."""
        result = await engine.list_snapshots()
        assert len(result) == 0
    
    def test_convert_to_snapshot_options(self, engine, create_options):
        """Test conversion of engine options to adapter options."""
        adapter_options = engine._convert_to_snapshot_options(create_options)
        
        assert adapter_options.compression_level == create_options.compression_level
        assert adapter_options.parallel_jobs == create_options.parallel_jobs
        assert adapter_options.include_schemas == create_options.include_schemas
        assert adapter_options.exclude_schemas == create_options.exclude_schemas
        assert adapter_options.data_only == create_options.data_only
        assert adapter_options.schema_only == create_options.schema_only
        assert adapter_options.include_large_objects == create_options.include_large_objects
    
    def test_convert_to_restore_options(self, engine, restore_options):
        """Test conversion of engine options to adapter options."""
        adapter_options = engine._convert_to_restore_options(restore_options)
        
        assert adapter_options.parallel_jobs == restore_options.parallel_jobs
        assert adapter_options.clean == restore_options.clean_before_restore
        assert adapter_options.create == restore_options.create_database
        assert adapter_options.if_exists == restore_options.if_exists
        assert adapter_options.disable_triggers == restore_options.disable_triggers
        assert adapter_options.single_transaction == restore_options.single_transaction
        assert adapter_options.no_owner == restore_options.no_owner
        assert adapter_options.no_privileges == restore_options.no_privileges
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_atomic_operation_rollback_on_failure(self, mock_adapter_factory, engine, create_options):
        """Test that atomic operations rollback on failure."""
        # Mock database adapter that fails
        mock_adapter = AsyncMock()
        mock_adapter.connect.return_value = None
        mock_adapter.disconnect.return_value = None
        mock_adapter.get_database_info.side_effect = Exception("Database error")
        
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Attempt to create snapshot (should fail and rollback)
        with pytest.raises(SnapshotError):
            await engine.create_snapshot(create_options)
        
        # Verify snapshot directory was not created (rollback successful)
        snapshot_path = engine.storage_base_path / create_options.name
        assert not snapshot_path.exists()
    
    @patch('src.dbranching.snapshot.engine.SnapshotEngine._create_database_adapter')
    async def test_compression_integration(self, mock_adapter_factory, engine):
        """Test compression integration in snapshot creation."""
        mock_adapter = AsyncMock()
        mock_adapter_factory.return_value = mock_adapter
        engine.adapter = mock_adapter
        
        # Test different compression types
        for compression_type in [CompressionType.NONE, CompressionType.GZIP]:
            options = SnapshotCreateOptions(
                name=f"test_{compression_type.value}",
                compression=compression_type
            )
            
            # Mock the compression engine to verify it's called correctly
            with patch.object(engine.compression_engine, 'compress_file') as mock_compress:
                mock_compress.return_value = MagicMock()
                
                # The create_snapshot method would normally call compression
                # We're testing the compression type is passed correctly
                compression_options = engine._convert_to_snapshot_options(options)
                
                # Verify compression type mapping is correct
                if compression_type == CompressionType.GZIP:
                    assert compression_options.compression.value == "gzip"
                else:
                    assert compression_options.compression.value == "none"