"""Integration tests for complete storage management system."""

import asyncio
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dbranching.config import StorageConfig, DatabaseConfig
from dbranching.snapshot.models import SnapshotMetadata, DatabaseMetadata, FileMetadata, CompressionType
from dbranching.snapshot.engine import SnapshotEngine
from dbranching.storage.integration import StorageManager
from dbranching.storage.models import StorageEntry, StorageEntryStatus


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
def database_config():
    """Create test database configuration."""
    return DatabaseConfig(
        driver="postgresql",
        host="localhost",
        port=5432,
        database="test_db",
        username="test_user"
    )


@pytest.fixture
def mock_snapshot_engine():
    """Create mock snapshot engine."""
    engine = AsyncMock(spec=SnapshotEngine)
    
    # Mock restore_snapshot method
    async def mock_restore(name, options=None, progress_callback=None):
        return AsyncMock(
            name=name,
            path=Path(f"/test/{name}"),
            status="completed"
        )
    
    engine.restore_snapshot.side_effect = mock_restore
    return engine


@pytest.fixture
def storage_manager(temp_storage_config, mock_snapshot_engine):
    """Create storage manager for testing."""
    return StorageManager(
        storage_config=temp_storage_config,
        project_name="test_project",
        snapshot_engine=mock_snapshot_engine
    )


@pytest.fixture
def sample_snapshot_metadata():
    """Create sample snapshot metadata."""
    return SnapshotMetadata(
        name="integration_test_snapshot",
        description="Integration test snapshot",
        tags=["integration", "test"],
        database=DatabaseMetadata(
            type="postgresql",
            version="15.3",
            size_bytes=2048000,
            table_count=10,
            schema_count=2,
            schema_checksum="integration123",
            encoding="UTF8",
            collation="en_US.UTF-8",
            timezone="UTC",
            extensions=["uuid-ossp", "pg_stat_statements"]
        ),
        compression=CompressionType.GZIP,
        compression_level=6,
        total_size_bytes=1024000,
        files=[
            FileMetadata(
                name="schema.sql.gz",
                size_bytes=100000,
                checksum="schema_checksum",
                compression=CompressionType.GZIP
            ),
            FileMetadata(
                name="data.sql.gz",
                size_bytes=924000,
                checksum="data_checksum",
                compression=CompressionType.GZIP
            )
        ],
        creation_duration_seconds=45.2,
        compression_ratio=2.0
    )


@pytest.fixture
def sample_source_path(temp_storage_config, sample_snapshot_metadata):
    """Create sample source snapshot directory."""
    source_dir = temp_storage_config.path / "temp_integration_snapshot"
    source_dir.mkdir(parents=True, exist_ok=True)
    
    # Create metadata file
    metadata_content = sample_snapshot_metadata.dict()
    metadata_file = source_dir / "metadata.json"
    metadata_file.write_text(json.dumps(metadata_content, indent=2, default=str))
    
    # Create sample snapshot files
    (source_dir / "schema.sql.gz").write_bytes(b"compressed schema data for integration test")
    (source_dir / "data.sql.gz").write_bytes(b"compressed data content for integration test")
    
    return source_dir


class TestStorageManagerIntegration:
    """Integration test cases for StorageManager."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_snapshot_storage(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test complete snapshot storage workflow."""
        # Store snapshot
        storage_entry = await storage_manager.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main",
            parent_branch=None,
            git_commit="abc123",
            git_author="test@example.com",
            auto_cleanup=False  # Disable for this test
        )
        
        # Verify storage entry
        assert storage_entry.name == sample_snapshot_metadata.name
        assert storage_entry.branch == "main"
        assert storage_entry.git_commit == "abc123"
        assert storage_entry.status == StorageEntryStatus.ACTIVE
        
        # Verify files were stored
        assert storage_entry.path.exists()
        assert (storage_entry.path / "metadata.json").exists()
        assert (storage_entry.path / "schema.sql.gz").exists()
        assert (storage_entry.path / "data.sql.gz").exists()
        
        # Verify can be retrieved
        retrieved = await storage_manager.backend.retrieve_snapshot(storage_entry.snapshot_id)
        assert retrieved is not None
        assert retrieved.name == storage_entry.name
    
    @pytest.mark.asyncio
    async def test_snapshot_restoration_integration(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test snapshot restoration through storage manager."""
        # Store snapshot first
        storage_entry = await storage_manager.store_snapshot(
            snapshot_metadata=sample_snapshot_metadata,
            source_path=sample_source_path,
            branch="main"
        )
        
        # Restore snapshot
        snapshot_info = await storage_manager.restore_snapshot(storage_entry.snapshot_id)
        
        # Verify restoration
        assert snapshot_info is not None
        assert snapshot_info.name == storage_entry.name
        
        # Verify last accessed time was updated
        updated_entry = await storage_manager.backend.retrieve_snapshot(storage_entry.snapshot_id)
        assert updated_entry.last_accessed is not None
        assert updated_entry.last_accessed > storage_entry.created_at
    
    @pytest.mark.asyncio
    async def test_restore_deduplicated_snapshot(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test restoration of deduplicated snapshot."""
        # Store original snapshot
        original_entry = await storage_manager.store_snapshot(
            sample_snapshot_metadata, sample_source_path, "main"
        )
        
        # Store duplicate snapshot
        duplicate_metadata = sample_snapshot_metadata.copy()
        duplicate_metadata.name = "duplicate_snapshot"
        duplicate_entry = await storage_manager.store_snapshot(
            duplicate_metadata, sample_source_path, "feature"
        )
        
        # Simulate deduplication by creating marker
        dedup_marker = duplicate_entry.path / ".deduplicated"
        dedup_info = {
            "original_snapshot_id": original_entry.snapshot_id,
            "original_path": str(original_entry.path),
            "linked_at": datetime.utcnow().isoformat(),
            "space_saved": duplicate_entry.compressed_size_bytes
        }
        dedup_marker.write_text(json.dumps(dedup_info, indent=2))
        
        # Restore deduplicated snapshot
        snapshot_info = await storage_manager.restore_snapshot(duplicate_entry.snapshot_id)
        
        # Should successfully restore using original snapshot
        assert snapshot_info is not None
    
    @pytest.mark.asyncio
    async def test_storage_health_report_generation(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test comprehensive storage health report generation."""
        # Store some snapshots for analysis
        await storage_manager.store_snapshot(
            sample_snapshot_metadata, sample_source_path, "main"
        )
        
        # Generate health report
        health_report = await storage_manager.get_storage_health_report()
        
        # Verify report structure
        assert "health_score" in health_report
        assert "health_status" in health_report
        assert "storage_stats" in health_report
        assert "validation_result" in health_report
        assert "efficiency_analysis" in health_report
        assert "cleanup_preview" in health_report
        assert "recommendations" in health_report
        assert "generated_at" in health_report
        
        # Verify health score is calculated
        assert 0 <= health_report["health_score"] <= 100
        
        # Verify health status is valid
        assert health_report["health_status"] in ["excellent", "good", "fair", "poor", "critical"]
    
    @pytest.mark.asyncio
    async def test_comprehensive_storage_optimization(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test comprehensive storage optimization workflow."""
        # Store multiple snapshots with potential for optimization
        for i in range(3):
            metadata = sample_snapshot_metadata.copy()
            metadata.name = f"optimization_test_{i}"
            await storage_manager.store_snapshot(
                metadata, sample_source_path, f"branch_{i}"
            )
        
        # Run comprehensive optimization
        optimization_results = await storage_manager.optimize_storage(
            enable_deduplication=True,
            enable_compression_optimization=True,
            enable_layout_optimization=True,
            dry_run=True  # Don't actually modify
        )
        
        # Verify optimization results structure
        assert "started_at" in optimization_results
        assert "completed_at" in optimization_results
        assert "deduplication_result" in optimization_results
        assert "compression_optimization" in optimization_results
        assert "layout_optimization" in optimization_results
        assert "total_bytes_saved" in optimization_results
        
        # Verify timing
        start_time = datetime.fromisoformat(optimization_results["started_at"])
        end_time = datetime.fromisoformat(optimization_results["completed_at"])
        assert end_time > start_time
    
    @pytest.mark.asyncio
    async def test_storage_cleanup_integration(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test storage cleanup integration."""
        # Store snapshots with different ages
        base_time = datetime.utcnow()
        
        for i in range(3):
            metadata = sample_snapshot_metadata.copy()
            metadata.name = f"cleanup_test_{i}"
            metadata.created_at = base_time - timedelta(days=i * 10)
            
            entry = await storage_manager.store_snapshot(
                metadata, sample_source_path, "main", auto_cleanup=False
            )
            
            # Manually update creation time in storage entry
            entry.created_at = metadata.created_at
            await storage_manager.backend._update_index_entry(entry)
        
        # Run cleanup
        cleanup_results = await storage_manager.cleanup_storage(dry_run=True)
        
        # Should execute cleanup policies
        assert len(cleanup_results) > 0
        
        # Verify cleanup results structure
        for result in cleanup_results:
            assert hasattr(result, 'policy_name')
            assert hasattr(result, 'total_examined')
            assert hasattr(result, 'total_deleted')
            assert hasattr(result, 'total_preserved')
    
    @pytest.mark.asyncio
    async def test_branch_statistics_integration(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test branch statistics calculation."""
        # Store snapshots across multiple branches
        branches = ["main", "feature/auth", "feature/payment"]
        
        for branch in branches:
            for i in range(2):
                metadata = sample_snapshot_metadata.copy()
                metadata.name = f"{branch.replace('/', '_')}_snapshot_{i}"
                await storage_manager.store_snapshot(
                    metadata, sample_source_path, branch
                )
        
        # Get statistics for specific branch
        main_stats = await storage_manager.get_branch_statistics("main")
        
        # Verify statistics structure
        assert main_stats["branch"] == "main"
        assert main_stats["snapshot_count"] == 2
        assert main_stats["total_size_bytes"] > 0
        assert main_stats["average_compression_ratio"] > 0
        assert main_stats["oldest_snapshot"] is not None
        assert main_stats["newest_snapshot"] is not None
        
        # Verify temporal information
        oldest = main_stats["oldest_snapshot"]
        newest = main_stats["newest_snapshot"]
        assert "id" in oldest
        assert "created_at" in oldest
        assert "id" in newest
        assert "created_at" in newest
    
    @pytest.mark.asyncio
    async def test_metadata_export_import_integration(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test metadata export and import functionality."""
        # Store some snapshots
        stored_entries = []
        for i in range(2):
            metadata = sample_snapshot_metadata.copy()
            metadata.name = f"export_test_{i}"
            entry = await storage_manager.store_snapshot(
                metadata, sample_source_path, f"branch_{i}"
            )
            stored_entries.append(entry)
        
        # Export metadata
        export_path = storage_manager.backend.temp_path / "export_test.json"
        export_stats = await storage_manager.export_storage_metadata(export_path)
        
        # Verify export
        assert export_path.exists()
        assert export_stats["snapshots_exported"] == 2
        assert export_stats["export_size_bytes"] > 0
        
        # Verify export content
        export_content = json.loads(export_path.read_text())
        assert export_content["export_version"] == "1.0"
        assert export_content["project_name"] == "test_project"
        assert len(export_content["snapshots"]) == 2
        
        # Clear storage
        for entry in stored_entries:
            await storage_manager.backend.delete_snapshot(entry.snapshot_id, force=True)
        
        # Import metadata
        import_stats = await storage_manager.import_storage_metadata(
            export_path, merge_mode="skip_existing"
        )
        
        # Verify import
        assert import_stats["snapshots_imported"] == 2
        assert import_stats["snapshots_skipped"] == 0
        
        # Verify snapshots are accessible after import
        imported_snapshots = await storage_manager.backend.list_snapshots()
        assert len(imported_snapshots) == 2
    
    @pytest.mark.asyncio
    async def test_storage_migration_integration(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test storage migration functionality."""
        # Store snapshot
        await storage_manager.store_snapshot(
            sample_snapshot_metadata, sample_source_path, "main"
        )
        
        # Run migration
        migration_result = await storage_manager.migrate_storage(
            target_version="1.0",
            backup_before_migration=True
        )
        
        # Verify migration results
        assert migration_result["target_version"] == "1.0"
        assert migration_result["snapshots_migrated"] == 1
        assert migration_result["backup_created"] is True
        assert "backup_path" in migration_result
        
        # Verify backup was created
        backup_path = Path(migration_result["backup_path"])
        assert backup_path.exists()
        
        # Verify snapshots are still accessible after migration
        snapshots = await storage_manager.backend.list_snapshots()
        assert len(snapshots) == 1
    
    @pytest.mark.asyncio
    async def test_automated_workflow_integration(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test complete automated workflow with storage, cleanup, and optimization."""
        # Store multiple snapshots over time
        base_time = datetime.utcnow()
        stored_entries = []
        
        for i in range(5):
            metadata = sample_snapshot_metadata.copy()
            metadata.name = f"workflow_test_{i}"
            metadata.created_at = base_time - timedelta(days=i * 5)
            
            entry = await storage_manager.store_snapshot(
                metadata, sample_source_path, "main", auto_cleanup=False
            )
            
            # Update creation time in storage
            entry.created_at = metadata.created_at
            await storage_manager.backend._update_index_entry(entry)
            stored_entries.append(entry)
        
        # Get initial storage stats
        initial_stats = await storage_manager.backend.get_storage_stats()
        
        # Run cleanup
        cleanup_results = await storage_manager.cleanup_storage(dry_run=False)
        
        # Run optimization
        optimization_results = await storage_manager.optimize_storage(dry_run=False)
        
        # Get final storage stats
        final_stats = await storage_manager.backend.get_storage_stats()
        
        # Verify workflow executed successfully
        assert len(cleanup_results) > 0
        assert optimization_results["total_bytes_saved"] >= 0
        
        # Storage should be healthier after optimization
        initial_health = initial_stats.get_storage_health_score()
        final_health = final_stats.get_storage_health_score()
        assert final_health >= initial_health  # Should not get worse
    
    @pytest.mark.asyncio
    async def test_concurrent_storage_operations(self, storage_manager, sample_snapshot_metadata):
        """Test concurrent storage operations."""
        # Create multiple source directories
        source_paths = []
        for i in range(3):
            source_dir = storage_manager.backend.temp_path / f"concurrent_source_{i}"
            source_dir.mkdir(parents=True, exist_ok=True)
            
            # Create metadata and files
            metadata_content = sample_snapshot_metadata.dict()
            metadata_content["name"] = f"concurrent_test_{i}"
            (source_dir / "metadata.json").write_text(json.dumps(metadata_content, indent=2, default=str))
            (source_dir / "data.sql.gz").write_bytes(f"data content {i}".encode())
            
            source_paths.append(source_dir)
        
        # Store snapshots concurrently
        tasks = []
        for i, source_path in enumerate(source_paths):
            metadata = sample_snapshot_metadata.copy()
            metadata.name = f"concurrent_test_{i}"
            
            task = storage_manager.store_snapshot(
                metadata, source_path, f"branch_{i}", auto_cleanup=False
            )
            tasks.append(task)
        
        # Wait for all operations
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify all succeeded
        successful_results = [r for r in results if not isinstance(r, Exception)]
        assert len(successful_results) == 3
        
        # Verify all snapshots are accessible
        final_snapshots = await storage_manager.backend.list_snapshots()
        assert len(final_snapshots) == 3
    
    @pytest.mark.asyncio
    async def test_list_snapshots_with_metadata_integration(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test listing snapshots with combined metadata."""
        # Store snapshots
        await storage_manager.store_snapshot(
            sample_snapshot_metadata, sample_source_path, "main"
        )
        
        # List with metadata
        snapshots_with_metadata = await storage_manager.list_snapshots_with_metadata(
            include_storage_stats=True
        )
        
        # Verify structure
        assert "snapshots" in snapshots_with_metadata
        assert "storage_stats" in snapshots_with_metadata
        assert "total_count" in snapshots_with_metadata
        
        snapshots = snapshots_with_metadata["snapshots"]
        assert len(snapshots) == 1
        
        snapshot_data = snapshots[0]
        assert "storage_entry" in snapshot_data
        assert "snapshot_metadata" in snapshot_data
        assert "is_deduplicated" in snapshot_data
        
        # Verify metadata was loaded
        assert snapshot_data["snapshot_metadata"] is not None
        assert snapshot_data["snapshot_metadata"]["name"] == sample_snapshot_metadata.name


class TestErrorHandlingIntegration:
    """Test error handling across storage management components."""
    
    @pytest.mark.asyncio
    async def test_storage_failure_during_optimization(self, storage_manager):
        """Test error handling when storage operations fail during optimization."""
        # Mock storage backend to fail
        with patch.object(storage_manager.backend, 'list_snapshots') as mock_list:
            mock_list.side_effect = Exception("Storage backend failure")
            
            # Optimization should handle error gracefully
            with pytest.raises(Exception):  # Should propagate storage errors
                await storage_manager.optimize_storage()
    
    @pytest.mark.asyncio
    async def test_cleanup_failure_during_storage(self, storage_manager, sample_snapshot_metadata, sample_source_path):
        """Test error handling when cleanup fails during storage."""
        # Mock cleanup to fail
        with patch.object(storage_manager.cleanup_engine, 'execute_automatic_cleanup') as mock_cleanup:
            mock_cleanup.side_effect = Exception("Cleanup failure")
            
            # Storage should succeed even if cleanup fails
            storage_entry = await storage_manager.store_snapshot(
                sample_snapshot_metadata, sample_source_path, "main", auto_cleanup=True
            )
            
            # Snapshot should be stored successfully
            assert storage_entry.name == sample_snapshot_metadata.name
            
            # Verify snapshot is accessible
            retrieved = await storage_manager.backend.retrieve_snapshot(storage_entry.snapshot_id)
            assert retrieved is not None
    
    @pytest.mark.asyncio
    async def test_restoration_without_snapshot_engine(self, temp_storage_config):
        """Test restoration failure when snapshot engine is not configured."""
        # Create storage manager without snapshot engine
        manager = StorageManager(temp_storage_config, project_name="test")
        assert manager.snapshot_engine is None
        
        # Attempt restoration should fail
        with pytest.raises(StorageError, match="Snapshot engine not configured"):
            await manager.restore_snapshot("some_id")


class TestPerformanceIntegration:
    """Test performance aspects of storage integration."""
    
    @pytest.mark.asyncio
    async def test_large_scale_storage_operations(self, storage_manager, sample_snapshot_metadata):
        """Test storage operations with larger numbers of snapshots."""
        # Create many snapshots (simulated)
        snapshots = []
        for i in range(50):
            snapshot = StorageEntry(
                snapshot_id=f"perf_test_{i}",
                name=f"performance_test_{i}",
                branch=f"branch_{i % 5}",  # 5 branches
                path=Path(f"/test/perf_{i}"),
                size_bytes=1024000,
                compressed_size_bytes=512000,
                checksum=f"checksum_{i % 10}",  # Some duplicates
                created_at=datetime.utcnow() - timedelta(days=i),
                database_type="postgresql",
                database_version="15.3",
                compression_type="gzip",
                compression_ratio=2.0,
                tags=["performance"] if i % 10 == 0 else []
            )
            snapshots.append(snapshot)
        
        # Mock storage backend to return large number of snapshots
        with patch.object(storage_manager.backend, 'list_snapshots') as mock_list:
            mock_list.return_value = snapshots
            
            # Test operations with many snapshots
            stats = await storage_manager.backend.get_storage_stats()
            assert stats.total_snapshots == 50
            
            # Test branch statistics
            branch_stats = await storage_manager.get_branch_statistics("branch_0")
            assert branch_stats["snapshot_count"] == 10  # Every 5th snapshot
    
    @pytest.mark.asyncio
    async def test_background_operations_startup(self, storage_manager):
        """Test starting background operations."""
        # Test starting background cleanup
        await storage_manager.cleanup_engine.schedule_background_cleanup(interval_hours=24)
        
        # Test starting background optimization
        await storage_manager.optimizer.run_background_optimization(
            interval_hours=6,
            enable_deduplication=True,
            enable_compression_optimization=True,
            enable_layout_optimization=False
        )
        
        # Should complete without errors
        # Note: In a full integration test, we'd verify the background tasks
        # are actually scheduled and running properly