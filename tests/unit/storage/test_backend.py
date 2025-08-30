"""Tests for storage backend functionality."""

import asyncio
import json
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dbranching.config import StorageConfig
from dbranching.exceptions import StorageError, ValidationError
from dbranching.snapshot.models import SnapshotMetadata, DatabaseMetadata, FileMetadata, CompressionType, CompatibilityInfo
from dbranching.storage.backend import StorageBackend
from dbranching.storage.models import StorageEntry, StorageEntryStatus, BranchAncestry


@pytest.fixture
def temp_storage_config():
    """Create temporary storage configuration."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config = StorageConfig(
            path=Path(temp_dir),
            max_size="1GB",
            monitoring_threshold=0.8
        )
        yield config


@pytest.fixture
def storage_backend(temp_storage_config):
    """Create storage backend for testing."""
    return StorageBackend(temp_storage_config, project_name="test_project")


@pytest.fixture
def sample_snapshot_metadata():
    """Create sample snapshot metadata."""
    return SnapshotMetadata(
        name="test_snapshot",
        description="Test snapshot for storage",
        tags=["test", "storage"],
        database=DatabaseMetadata(
            type="postgresql",
            version="15.3",
            size_bytes=1024000,
            table_count=5,
            schema_count=1,
            schema_checksum="abc123",
            encoding="UTF8",
            collation="en_US.UTF-8",
            timezone="UTC",
            extensions=["uuid-ossp"]
        ),
        compatibility=CompatibilityInfo(
            min_database_version="15.0",
            requires_extensions=["uuid-ossp"],
            schema_changes=[],
            warnings=[]
        ),
        compression=CompressionType.GZIP,
        compression_level=6,
        total_size_bytes=512000,
        files=[
            FileMetadata(
                name="schema.sql.gz",
                size_bytes=50000,
                checksum="schema123",
                compression=CompressionType.GZIP
            ),
            FileMetadata(
                name="data.sql.gz", 
                size_bytes=462000,
                checksum="data456",
                compression=CompressionType.GZIP
            )
        ],
        creation_duration_seconds=30.5,
        compression_ratio=2.0
    )


@pytest.fixture
def sample_source_path(temp_storage_config):
    """Create sample source snapshot directory."""
    source_dir = temp_storage_config.path / "temp_snapshot"
    source_dir.mkdir(parents=True, exist_ok=True)
    
    # Create sample files
    metadata_file = source_dir / "metadata.json"
    metadata_content = {
        "name": "test_snapshot",
        "created_at": datetime.utcnow().isoformat(),
        "database": {"type": "postgresql", "version": "15.3"},
        "total_size_bytes": 512000
    }
    metadata_file.write_text(json.dumps(metadata_content, indent=2))
    
    # Create sample snapshot files
    (source_dir / "schema.sql.gz").write_bytes(b"compressed schema data")
    (source_dir / "data.sql.gz").write_bytes(b"compressed data content")
    
    return source_dir


class TestStorageBackend:
    """Test cases for StorageBackend."""
    
    @pytest.mark.asyncio
    async def test_initialization(self, temp_storage_config):
        """Test storage backend initialization."""
        backend = StorageBackend(temp_storage_config, project_name="test")
        
        # Check directory structure creation
        assert backend.project_path.exists()
        assert backend.snapshots_path.exists()
        assert backend.metadata_path.exists()
        assert backend.temp_path.exists()
        
        # Check configuration
        assert backend.project_name == "test"
        assert backend.storage_config == temp_storage_config
    
    @pytest.mark.asyncio
    async def test_get_snapshot_path(self, storage_backend):
        """Test snapshot path generation and sanitization."""
        # Test normal branch name
        path = await storage_backend.get_snapshot_path("main", "snapshot1")
        expected = storage_backend.snapshots_path / "main" / "snapshot1"
        assert path == expected
        
        # Test branch name with special characters
        path = await storage_backend.get_snapshot_path("feature/auth-system", "snapshot2")
        expected = storage_backend.snapshots_path / "feature_auth-system" / "snapshot2"
        assert path == expected
    
    @pytest.mark.asyncio
    async def test_store_snapshot(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test storing snapshot with metadata tracking."""
        # Store snapshot
        storage_entry = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main",
            parent_branch=None,
            git_commit="abc123",
            git_author="test@example.com"
        )
        
        # Verify storage entry
        assert storage_entry.name == "test_snapshot"
        assert storage_entry.branch == "main"
        assert storage_entry.git_commit == "abc123"
        assert storage_entry.git_author == "test@example.com"
        assert storage_entry.status == StorageEntryStatus.ACTIVE
        
        # Verify files were copied
        assert storage_entry.path.exists()
        assert (storage_entry.path / "metadata.json").exists()
        assert (storage_entry.path / "schema.sql.gz").exists()
        assert (storage_entry.path / "data.sql.gz").exists()
    
    @pytest.mark.asyncio
    async def test_retrieve_snapshot(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test retrieving stored snapshot."""
        # Store snapshot
        storage_entry = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Retrieve snapshot
        retrieved = await storage_backend.retrieve_snapshot(storage_entry.snapshot_id)
        
        assert retrieved is not None
        assert retrieved.snapshot_id == storage_entry.snapshot_id
        assert retrieved.name == storage_entry.name
        assert retrieved.last_accessed is not None
    
    @pytest.mark.asyncio
    async def test_list_snapshots(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test listing stored snapshots."""
        # Store multiple snapshots
        storage_entry1 = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Create another snapshot with different metadata
        sample_snapshot_metadata.name = "test_snapshot_2"
        storage_entry2 = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="feature"
        )
        
        # List all snapshots
        snapshots = await storage_backend.list_snapshots()
        assert len(snapshots) >= 2
        
        snapshot_ids = [s.snapshot_id for s in snapshots]
        assert storage_entry1.snapshot_id in snapshot_ids
        assert storage_entry2.snapshot_id in snapshot_ids
        
        # List by branch
        main_snapshots = await storage_backend.list_snapshots(branch="main")
        assert len(main_snapshots) >= 1
        assert all(s.branch == "main" for s in main_snapshots)
    
    @pytest.mark.asyncio
    async def test_delete_snapshot(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test deleting snapshot."""
        # Store snapshot
        storage_entry = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Verify it exists
        retrieved = await storage_backend.retrieve_snapshot(storage_entry.snapshot_id)
        assert retrieved is not None
        
        # Delete snapshot
        deleted = await storage_backend.delete_snapshot(storage_entry.snapshot_id)
        assert deleted is True
        
        # Verify it's gone
        retrieved = await storage_backend.retrieve_snapshot(storage_entry.snapshot_id)
        assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_branch_ancestry_tracking(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test branch ancestry tracking."""
        # Store main branch snapshot
        main_entry = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Store feature branch snapshot with main as parent
        sample_snapshot_metadata.name = "feature_snapshot"
        feature_entry = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="feature/auth",
            parent_branch="main"
        )
        
        # Verify ancestry is tracked
        ancestry = await storage_backend.get_branch_ancestry("feature/auth")
        assert ancestry is not None
        assert ancestry.branch == "feature/auth"
        assert ancestry.parent_branch == "main"
        assert main_entry.snapshot_id in ancestry.ancestor_snapshots
        assert feature_entry.snapshot_id in ancestry.snapshots
    
    @pytest.mark.asyncio
    async def test_storage_validation(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test storage integrity validation."""
        # Store snapshot
        storage_entry = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Validate storage
        is_valid = await storage_backend.validate_storage(storage_entry.snapshot_id)
        assert is_valid is True
        
        # Test validation with corrupted file
        corrupted_file = storage_entry.path / "schema.sql.gz"
        corrupted_file.write_bytes(b"corrupted data")
        
        is_valid = await storage_backend.validate_storage(storage_entry.snapshot_id)
        assert is_valid is False
    
    @pytest.mark.asyncio
    async def test_atomic_operations(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test atomic operation handling."""
        # Mock a failure during storage
        with patch.object(storage_backend, '_copy_snapshot_files') as mock_copy:
            mock_copy.side_effect = Exception("Copy failed")
            
            # Attempt to store snapshot
            with pytest.raises(StorageError):
                await storage_backend.store_snapshot(
                    snapshot_metadata=sample_snapshot_metadata,
                    source_path=sample_source_path,
                    branch="main"
                )
            
            # Verify no partial files remain
            snapshots = await storage_backend.list_snapshots()
            assert len(snapshots) == 0
    
    @pytest.mark.asyncio
    async def test_storage_stats(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test storage statistics."""
        # Store some snapshots
        await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        sample_snapshot_metadata.name = "test_snapshot_2"
        await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="feature"
        )
        
        # Get statistics
        stats = await storage_backend.get_storage_stats()
        
        assert stats.total_snapshots >= 2
        assert stats.total_size_bytes > 0
        assert stats.total_compressed_bytes > 0
        assert stats.average_compression_ratio > 0
        assert len(stats.branches) >= 2
        assert "main" in stats.branches
        assert "feature" in stats.branches


class TestBranchAncestryOperations:
    """Test branch ancestry tracking functionality."""
    
    @pytest.mark.asyncio
    async def test_complex_branch_ancestry(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test complex branch ancestry tracking."""
        # Create main branch snapshot
        main_meta = sample_snapshot_metadata.model_copy()
        main_meta.name = "main_snapshot"
        main_entry = await storage_backend.store_snapshot(
            snapshot_metadata=main_meta,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Create develop branch from main
        develop_meta = sample_snapshot_metadata.model_copy()
        develop_meta.name = "develop_snapshot"
        develop_entry = await storage_backend.store_snapshot(
            snapshot_metadata=develop_meta,
            source_path=sample_source_path,
            branch="develop",
            parent_branch="main"
        )
        
        # Create feature branch from develop
        feature_meta = sample_snapshot_metadata.model_copy()
        feature_meta.name = "feature_snapshot"
        feature_entry = await storage_backend.store_snapshot(
            snapshot_metadata=feature_meta,
            source_path=sample_source_path,
            branch="feature/auth",
            parent_branch="develop"
        )
        
        # Test ancestry chain
        feature_ancestry = await storage_backend.get_branch_ancestry("feature/auth")
        assert feature_ancestry.parent_branch == "develop"
        
        develop_ancestry = await storage_backend.get_branch_ancestry("develop")
        assert develop_ancestry.parent_branch == "main"
        
        # Test fallback chain
        fallback_chain = await storage_backend.get_fallback_chain("feature/auth")
        assert len(fallback_chain) >= 3
        
        # Verify order: feature -> develop -> main
        chain_branches = [entry.branch for entry in fallback_chain]
        assert "feature/auth" in chain_branches
        assert "develop" in chain_branches
        assert "main" in chain_branches


class TestStorageErrorHandling:
    """Test storage error handling and edge cases."""
    
    @pytest.mark.asyncio
    async def test_nonexistent_snapshot_retrieval(self, storage_backend):
        """Test retrieving non-existent snapshot."""
        result = await storage_backend.retrieve_snapshot("nonexistent_id")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_invalid_source_path(self, storage_backend, sample_snapshot_metadata):
        """Test storing with invalid source path."""
        invalid_path = Path("/nonexistent/path")
        
        with pytest.raises(StorageError):
            await storage_backend.store_snapshot(
                snapshot_metadata=sample_snapshot_metadata,
                source_path=invalid_path,
                branch="main"
            )
    
    @pytest.mark.asyncio
    async def test_duplicate_snapshot_handling(self, storage_backend, sample_snapshot_metadata, sample_source_path):
        """Test handling duplicate snapshot storage."""
        # Store initial snapshot
        entry1 = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Attempt to store same snapshot again
        entry2 = await storage_backend.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Should create different entries (different IDs)
        assert entry1.snapshot_id != entry2.snapshot_id
        assert entry1.name == entry2.name