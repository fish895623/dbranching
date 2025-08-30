"""Tests for storage cleanup policy engine."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dbranching.config import StorageConfig, RetentionPolicyConfig, BranchRetentionConfig
from dbranching.storage.backend import StorageBackend
from dbranching.storage.cleanup import CleanupPolicyEngine
from dbranching.storage.models import CleanupPolicy, StorageEntry, StorageEntryStatus


@pytest.fixture
def temp_storage_config():
    """Create temporary storage configuration with cleanup policies."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config = StorageConfig(
            path=Path(temp_dir),
            max_size="1GB",
            monitoring_threshold=0.8,
            retention=RetentionPolicyConfig(
                max_age="30d",
                max_count=50
            ),
            patterns=[
                BranchRetentionConfig(
                    branches=["main", "master"],
                    max_age="90d",
                    max_count=100
                )
            ]
        )
        yield config


@pytest.fixture
def storage_backend(temp_storage_config):
    """Create storage backend for testing."""
    return StorageBackend(temp_storage_config, project_name="test_project")


@pytest.fixture
def cleanup_engine(storage_backend, temp_storage_config):
    """Create cleanup policy engine for testing."""
    return CleanupPolicyEngine(storage_backend, temp_storage_config)


class TestCleanupPolicyEngine:
    """Test cases for CleanupPolicyEngine."""
    
    def test_initialization(self, cleanup_engine):
        """Test cleanup engine initialization."""
        policies = cleanup_engine.get_all_policies()
        
        # Should have default policies created from config
        policy_names = [p.name for p in policies]
        assert "default_retention" in policy_names
        assert "storage_limit" in policy_names
    
    @pytest.mark.asyncio
    async def test_cleanup_by_age(self, cleanup_engine):
        """Test age-based cleanup."""
        # Create test snapshots
        old_snapshot = StorageEntry(
            snapshot_id="old_id",
            name="old_snapshot",
            branch="main",
            path=Path("/test/old"),
            size_bytes=1024000,
            compressed_size_bytes=512000,
            checksum="old_checksum",
            created_at=datetime.utcnow() - timedelta(days=50),
            database_type="postgresql",
            database_version="15.3",
            compression_type="gzip",
            compression_ratio=2.0
        )
        
        recent_snapshot = StorageEntry(
            snapshot_id="recent_id",
            name="recent_snapshot",
            branch="main",
            path=Path("/test/recent"),
            size_bytes=1024000,
            compressed_size_bytes=512000,
            checksum="recent_checksum",
            created_at=datetime.utcnow() - timedelta(days=5),
            database_type="postgresql",
            database_version="15.3",
            compression_type="gzip",
            compression_ratio=2.0
        )
        
        test_snapshots = [old_snapshot, recent_snapshot]
        
        with patch.object(cleanup_engine.storage_backend, 'list_snapshots') as mock_list:
            mock_list.return_value = test_snapshots
            
            with patch.object(cleanup_engine.storage_backend, 'delete_snapshot') as mock_delete:
                mock_delete.return_value = True
                
                # Test cleanup with 30 day limit
                result = await cleanup_engine.cleanup_by_age(
                    max_age_days=30,
                    dry_run=True
                )
                
                # Should examine both snapshots
                assert result.total_examined == 2
                
                # Old snapshot should be marked for deletion
                assert "old_id" in result.deleted_snapshots
                
                # Recent snapshot should be preserved
                assert "recent_id" not in result.deleted_snapshots
    
    def test_policy_branch_matching(self):
        """Test branch pattern matching in policies."""
        policy = CleanupPolicy(
            name="test_policy",
            branch_patterns=["main", "feature/*"],
            exclude_branches=["feature/experimental"],
            max_age_days=30
        )
        
        # Test matches
        assert policy.matches_branch("main") is True
        assert policy.matches_branch("feature/auth") is True
        
        # Test exclusions
        assert policy.matches_branch("feature/experimental") is False
        
        # Test non-matches
        assert policy.matches_branch("develop") is False