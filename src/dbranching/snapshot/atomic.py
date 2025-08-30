"""Atomic operations manager for snapshot operations."""

import asyncio
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional
from contextlib import asynccontextmanager

from ..exceptions import SnapshotError, StorageError
from .models import AtomicOperationContext

logger = logging.getLogger(__name__)


class AtomicOperationManager:
    """Manager for atomic operations with guaranteed rollback capability."""
    
    def __init__(self, base_temp_dir: Optional[Path] = None):
        """
        Initialize atomic operation manager.
        
        Args:
            base_temp_dir: Base directory for temporary files, uses system temp if None
        """
        self.base_temp_dir = base_temp_dir or Path(tempfile.gettempdir())
        self._active_contexts: List[AtomicOperationContext] = []
        self._lock = asyncio.Lock()
    
    @asynccontextmanager
    async def atomic_operation(
        self,
        target_path: Path,
        backup_existing: bool = True,
        cleanup_on_success: bool = True
    ):
        """
        Create atomic operation context with automatic rollback on failure.
        
        Args:
            target_path: Final target path for the operation
            backup_existing: Whether to backup existing target before operation
            cleanup_on_success: Whether to cleanup temporary files on success
            
        Yields:
            AtomicOperationContext: Context for atomic operation
            
        Raises:
            SnapshotError: If operation setup fails
        """
        operation_id = str(uuid.uuid4())
        temp_dir = self.base_temp_dir / f"dbranching_atomic_{operation_id}"
        
        # Create context
        context = AtomicOperationContext(
            operation_id=operation_id,
            temp_dir=temp_dir,
            target_path=target_path.resolve(),
            cleanup_paths=[temp_dir],
            created_files=[],
            checkpoints=[]
        )
        
        try:
            # Setup temporary directory
            await self._setup_temp_directory(context)
            
            # Backup existing target if requested and exists
            if backup_existing and target_path.exists():
                await self._create_backup(context)
            
            # Track active context
            async with self._lock:
                self._active_contexts.append(context)
            
            # Add initial checkpoint
            await self._add_checkpoint(context, "operation_started")
            
            logger.debug(f"Started atomic operation {operation_id} for {target_path}")
            yield context
            
            # If we get here, operation was successful
            await self._commit_operation(context)
            await self._add_checkpoint(context, "operation_committed")
            
            if cleanup_on_success:
                await self._cleanup_operation(context)
            
            logger.info(f"Atomic operation {operation_id} completed successfully")
            
        except Exception as e:
            # Rollback on any failure
            logger.error(f"Atomic operation {operation_id} failed: {e}")
            await self._rollback_operation(context)
            raise SnapshotError(f"Atomic operation failed: {str(e)}")
            
        finally:
            # Remove from active contexts
            async with self._lock:
                if context in self._active_contexts:
                    self._active_contexts.remove(context)
    
    async def _setup_temp_directory(self, context: AtomicOperationContext) -> None:
        """Setup temporary directory for atomic operation."""
        try:
            context.temp_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created temporary directory: {context.temp_dir}")
        except Exception as e:
            raise StorageError(f"Failed to create temporary directory: {str(e)}")
    
    async def _create_backup(self, context: AtomicOperationContext) -> None:
        """Create backup of existing target."""
        if not context.target_path.exists():
            return
            
        backup_name = f"{context.target_path.name}.backup.{context.operation_id}"
        backup_path = context.target_path.parent / backup_name
        
        try:
            if context.target_path.is_dir():
                # Use thread pool for potentially slow filesystem operations
                await asyncio.get_event_loop().run_in_executor(
                    None, shutil.copytree, context.target_path, backup_path
                )
            else:
                await asyncio.get_event_loop().run_in_executor(
                    None, shutil.copy2, context.target_path, backup_path
                )
            
            context.backup_path = backup_path
            context.cleanup_paths.append(backup_path)
            logger.debug(f"Created backup: {backup_path}")
            
        except Exception as e:
            raise StorageError(f"Failed to create backup: {str(e)}")
    
    async def _add_checkpoint(self, context: AtomicOperationContext, checkpoint: str) -> None:
        """Add checkpoint to operation context."""
        context.checkpoints.append(f"{checkpoint}:{asyncio.get_event_loop().time()}")
        logger.debug(f"Checkpoint {checkpoint} added to operation {context.operation_id}")
    
    async def _commit_operation(self, context: AtomicOperationContext) -> None:
        """Commit atomic operation by moving temp files to target."""
        if not context.temp_dir.exists():
            return
            
        try:
            # Ensure target parent directory exists
            context.target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Remove existing target if it exists
            if context.target_path.exists():
                if context.target_path.is_dir():
                    await asyncio.get_event_loop().run_in_executor(
                        None, shutil.rmtree, context.target_path
                    )
                else:
                    context.target_path.unlink()
            
            # Move temp directory contents to target
            temp_contents = list(context.temp_dir.iterdir())
            
            if len(temp_contents) == 1 and temp_contents[0].is_dir():
                # If temp dir contains single directory, move it to target
                await asyncio.get_event_loop().run_in_executor(
                    None, shutil.move, temp_contents[0], context.target_path
                )
            else:
                # Move entire temp directory to target
                await asyncio.get_event_loop().run_in_executor(
                    None, shutil.move, context.temp_dir, context.target_path
                )
                # Update temp_dir path since it was moved
                context.temp_dir = context.target_path
                
            logger.debug(f"Committed operation {context.operation_id}")
            
        except Exception as e:
            raise StorageError(f"Failed to commit operation: {str(e)}")
    
    async def _rollback_operation(self, context: AtomicOperationContext) -> None:
        """Rollback atomic operation and restore backup if available."""
        logger.warning(f"Rolling back operation {context.operation_id}")
        
        try:
            # Restore backup if available
            if context.backup_path and context.backup_path.exists():
                # Remove current target if it exists
                if context.target_path.exists():
                    if context.target_path.is_dir():
                        await asyncio.get_event_loop().run_in_executor(
                            None, shutil.rmtree, context.target_path
                        )
                    else:
                        context.target_path.unlink()
                
                # Restore backup
                await asyncio.get_event_loop().run_in_executor(
                    None, shutil.move, context.backup_path, context.target_path
                )
                logger.info(f"Restored backup for operation {context.operation_id}")
            
            # Clean up temporary files
            await self._cleanup_operation(context, force=True)
            
        except Exception as e:
            logger.error(f"Failed to rollback operation {context.operation_id}: {e}")
            # Continue cleanup even if rollback fails
            
        await self._add_checkpoint(context, "operation_rolled_back")
    
    async def _cleanup_operation(self, context: AtomicOperationContext, force: bool = False) -> None:
        """Clean up temporary files and directories."""
        for path in context.cleanup_paths:
            try:
                if path.exists():
                    if path.is_dir():
                        await asyncio.get_event_loop().run_in_executor(
                            None, shutil.rmtree, path
                        )
                    else:
                        path.unlink()
                    logger.debug(f"Cleaned up: {path}")
            except Exception as e:
                if force:
                    logger.warning(f"Failed to cleanup {path}: {e}")
                else:
                    logger.error(f"Failed to cleanup {path}: {e}")
    
    async def get_temp_file_path(
        self,
        context: AtomicOperationContext,
        filename: str,
        create_parent: bool = True
    ) -> Path:
        """
        Get temporary file path within atomic operation context.
        
        Args:
            context: Atomic operation context
            filename: Name of the temporary file
            create_parent: Whether to create parent directory
            
        Returns:
            Path to temporary file
        """
        temp_file_path = context.temp_dir / filename
        
        if create_parent:
            temp_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Track created file
        context.created_files.append(temp_file_path)
        
        return temp_file_path
    
    async def get_temp_dir_path(
        self,
        context: AtomicOperationContext,
        dirname: str,
        create_dir: bool = True
    ) -> Path:
        """
        Get temporary directory path within atomic operation context.
        
        Args:
            context: Atomic operation context
            dirname: Name of the temporary directory
            create_dir: Whether to create the directory
            
        Returns:
            Path to temporary directory
        """
        temp_dir_path = context.temp_dir / dirname
        
        if create_dir:
            temp_dir_path.mkdir(parents=True, exist_ok=True)
        
        return temp_dir_path
    
    async def mark_file_created(self, context: AtomicOperationContext, path: Path) -> None:
        """Mark file as created during atomic operation for tracking."""
        context.created_files.append(path)
    
    async def add_cleanup_path(self, context: AtomicOperationContext, path: Path) -> None:
        """Add path to cleanup list."""
        if path not in context.cleanup_paths:
            context.cleanup_paths.append(path)
    
    async def emergency_cleanup_all(self) -> None:
        """Emergency cleanup of all active operations."""
        logger.warning("Performing emergency cleanup of all active operations")
        
        async with self._lock:
            contexts = self._active_contexts.copy()
            
        for context in contexts:
            try:
                await self._cleanup_operation(context, force=True)
            except Exception as e:
                logger.error(f"Emergency cleanup failed for {context.operation_id}: {e}")
        
        async with self._lock:
            self._active_contexts.clear()
    
    def get_active_operations(self) -> List[str]:
        """Get list of active operation IDs."""
        return [ctx.operation_id for ctx in self._active_contexts]