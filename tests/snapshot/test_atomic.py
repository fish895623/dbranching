"""Tests for atomic operations manager."""

import asyncio
import tempfile
from pathlib import Path
import pytest

from src.dbranching.snapshot.atomic import AtomicOperationManager
from src.dbranching.exceptions import SnapshotError, StorageError


class TestAtomicOperationManager:
    """Test cases for the AtomicOperationManager class."""
    
    @pytest.fixture
    def manager(self):
        """Create test atomic operation manager."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_temp_dir = Path(temp_dir)
            yield AtomicOperationManager(base_temp_dir)
    
    @pytest.fixture
    def test_target_path(self):
        """Create test target path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "target_file.txt"
            yield target_path
    
    async def test_atomic_operation_success(self, manager, test_target_path):
        """Test successful atomic operation."""
        test_content = "Hello, atomic world!"
        
        async with manager.atomic_operation(test_target_path) as ctx:
            # Create file in temporary directory
            temp_file = await manager.get_temp_file_path(ctx, "test.txt")
            temp_file.write_text(test_content)
            
            # Verify file exists in temp directory
            assert temp_file.exists()
            assert temp_file.read_text() == test_content
            
            # Target should not exist yet
            assert not test_target_path.exists()
        
        # After successful completion, file should be moved to target
        assert test_target_path.exists()
        # Note: In this simplified test, we check if temp directory operations work
        # Full integration would test the actual move operation
    
    async def test_atomic_operation_rollback_on_exception(self, manager, test_target_path):
        """Test rollback on exception during atomic operation."""
        test_content = "This should be rolled back"
        
        # Create existing target file to backup
        test_target_path.write_text("Original content")
        original_content = test_target_path.read_text()
        
        with pytest.raises(SnapshotError):
            async with manager.atomic_operation(test_target_path) as ctx:
                # Create file in temporary directory
                temp_file = await manager.get_temp_file_path(ctx, "test.txt")
                temp_file.write_text(test_content)
                
                # Simulate operation failure
                raise SnapshotError("Simulated operation failure")
        
        # After rollback, original content should be preserved
        assert test_target_path.exists()
        assert test_target_path.read_text() == original_content
    
    async def test_atomic_operation_backup_existing_file(self, manager, test_target_path):
        """Test backup of existing file before atomic operation."""
        original_content = "Original file content"
        test_target_path.write_text(original_content)
        
        async with manager.atomic_operation(test_target_path, backup_existing=True) as ctx:
            # Verify backup was created
            assert ctx.backup_path is not None
            assert ctx.backup_path.exists()
            assert ctx.backup_path.read_text() == original_content
            
            # Create new content in temp directory
            temp_file = await manager.get_temp_file_path(ctx, "new_content.txt")
            temp_file.write_text("New content")
    
    async def test_atomic_operation_no_backup(self, manager, test_target_path):
        """Test atomic operation without backup."""
        async with manager.atomic_operation(test_target_path, backup_existing=False) as ctx:
            # No backup should be created
            assert ctx.backup_path is None
            
            temp_file = await manager.get_temp_file_path(ctx, "test.txt")
            temp_file.write_text("Test content")
    
    async def test_get_temp_file_path(self, manager, test_target_path):
        """Test getting temporary file path."""
        async with manager.atomic_operation(test_target_path) as ctx:
            temp_file = await manager.get_temp_file_path(ctx, "test_file.txt")
            
            # Verify path is within temp directory
            assert temp_file.parent == ctx.temp_dir
            assert temp_file.name == "test_file.txt"
            assert temp_file in ctx.created_files
            
            # Parent directory should be created
            assert temp_file.parent.exists()
    
    async def test_get_temp_dir_path(self, manager, test_target_path):
        """Test getting temporary directory path."""
        async with manager.atomic_operation(test_target_path) as ctx:
            temp_dir = await manager.get_temp_dir_path(ctx, "subdir")
            
            # Verify path is within temp directory
            assert temp_dir.parent == ctx.temp_dir
            assert temp_dir.name == "subdir"
            
            # Directory should be created
            assert temp_dir.exists()
            assert temp_dir.is_dir()
    
    async def test_mark_file_created(self, manager, test_target_path):
        """Test marking file as created."""
        async with manager.atomic_operation(test_target_path) as ctx:
            test_file = ctx.temp_dir / "test.txt"
            test_file.write_text("Test")
            
            await manager.mark_file_created(ctx, test_file)
            
            assert test_file in ctx.created_files
    
    async def test_add_cleanup_path(self, manager, test_target_path):
        """Test adding cleanup path."""
        async with manager.atomic_operation(test_target_path) as ctx:
            cleanup_path = Path("/tmp/some_cleanup_path")
            
            await manager.add_cleanup_path(ctx, cleanup_path)
            
            assert cleanup_path in ctx.cleanup_paths
    
    async def test_multiple_concurrent_operations(self, manager):
        """Test multiple concurrent atomic operations."""
        num_operations = 5
        target_paths = []
        
        # Create multiple target paths
        with tempfile.TemporaryDirectory() as temp_dir:
            for i in range(num_operations):
                target_paths.append(Path(temp_dir) / f"target_{i}.txt")
            
            async def run_operation(target_path, content):
                async with manager.atomic_operation(target_path) as ctx:
                    temp_file = await manager.get_temp_file_path(ctx, "test.txt")
                    temp_file.write_text(content)
                    await asyncio.sleep(0.1)  # Simulate work
            
            # Run operations concurrently
            tasks = [
                run_operation(target_paths[i], f"Content {i}")
                for i in range(num_operations)
            ]
            
            await asyncio.gather(*tasks)
            
            # Verify all operations completed successfully
            assert len(manager.get_active_operations()) == 0
    
    async def test_emergency_cleanup_all(self, manager):
        """Test emergency cleanup of all active operations."""
        target_paths = []
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Start multiple operations but don't complete them
            for i in range(3):
                target_paths.append(Path(temp_dir) / f"target_{i}.txt")
            
            contexts = []
            
            # Start operations (but don't use context manager to completion)
            for target_path in target_paths:
                ctx_manager = manager.atomic_operation(target_path)
                ctx = await ctx_manager.__aenter__()
                contexts.append((ctx_manager, ctx))
                
                # Create some temp files
                temp_file = await manager.get_temp_file_path(ctx, "test.txt")
                temp_file.write_text("Test content")
            
            # Verify we have active operations
            assert len(manager.get_active_operations()) == 3
            
            # Emergency cleanup
            await manager.emergency_cleanup_all()
            
            # Verify all operations were cleaned up
            assert len(manager.get_active_operations()) == 0
            
            # Clean up context managers
            for ctx_manager, ctx in contexts:
                try:
                    await ctx_manager.__aexit__(None, None, None)
                except Exception:
                    pass  # Expected since we already cleaned up
    
    async def test_cleanup_on_success_disabled(self, manager, test_target_path):
        """Test atomic operation with cleanup disabled on success."""
        async with manager.atomic_operation(
            test_target_path, 
            cleanup_on_success=False
        ) as ctx:
            temp_file = await manager.get_temp_file_path(ctx, "test.txt")
            temp_file.write_text("Test content")
            
            temp_dir = ctx.temp_dir
            
            # Temp directory should exist during operation
            assert temp_dir.exists()
        
        # With cleanup disabled, temp directory might still exist
        # (In practice, this depends on the implementation details)
    
    async def test_operation_checkpoints(self, manager, test_target_path):
        """Test operation checkpoint functionality."""
        async with manager.atomic_operation(test_target_path) as ctx:
            # Initial checkpoint should exist
            assert len(ctx.checkpoints) > 0
            assert "operation_started" in ctx.checkpoints[0]
            
            # Add custom checkpoint
            await manager._add_checkpoint(ctx, "custom_checkpoint")
            
            assert len(ctx.checkpoints) >= 2
            assert any("custom_checkpoint" in cp for cp in ctx.checkpoints)
    
    async def test_context_properties(self, manager, test_target_path):
        """Test atomic operation context properties."""
        async with manager.atomic_operation(test_target_path) as ctx:
            # Verify context properties
            assert ctx.operation_id is not None
            assert len(ctx.operation_id) > 0
            assert ctx.temp_dir is not None
            assert ctx.target_path == test_target_path.resolve()
            assert isinstance(ctx.cleanup_paths, list)
            assert isinstance(ctx.created_files, list)
            assert isinstance(ctx.checkpoints, list)
            
            # Temp directory should exist and be writable
            assert ctx.temp_dir.exists()
            assert ctx.temp_dir.is_dir()
            
            # Should be able to create files in temp directory
            test_file = ctx.temp_dir / "test.txt"
            test_file.write_text("test")
            assert test_file.exists()
    
    async def test_storage_error_handling(self, manager):
        """Test handling of storage errors during atomic operations."""
        # Try to create operation with invalid target path
        invalid_target = Path("/invalid/nonexistent/path/target.txt")
        
        with pytest.raises(SnapshotError):
            async with manager.atomic_operation(invalid_target) as ctx:
                # This should fail when trying to setup the operation
                pass