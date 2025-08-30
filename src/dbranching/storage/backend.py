"""Storage backend for database snapshots with atomic operations and organization."""

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, AsyncContextManager
import tempfile
import shutil
import json

from ..config import StorageConfig
from ..exceptions import StorageError, ValidationError
from ..snapshot.models import SnapshotMetadata
from ..snapshot.atomic import AtomicOperationManager
from .models import (
    StorageEntry,
    StorageIndex,
    StorageStats,
    StorageEntryStatus,
    BranchAncestry,
    StorageConfiguration,
    StorageValidationResult,
)

logger = logging.getLogger(__name__)


class StorageBackend:
    """
    Storage backend providing atomic operations, path organization, and metadata tracking.
    
    Features:
    - Atomic write operations with rollback capability
    - Organized storage paths by project and branch
    - SQLite index for efficient queries
    - Branch ancestry tracking for fallback chains
    - Integrity verification and repair
    """
    
    def __init__(
        self,
        storage_config: StorageConfig,
        project_name: str = "default",
        atomic_manager: Optional[AtomicOperationManager] = None
    ):
        """
        Initialize storage backend.
        
        Args:
            storage_config: Storage configuration
            project_name: Project name for path organization
            atomic_manager: Optional atomic operation manager
        """
        self.storage_config = storage_config
        self.project_name = project_name
        self.atomic_manager = atomic_manager or AtomicOperationManager()
        
        # Setup storage paths
        self.base_path = storage_config.path
        self.project_path = self.base_path / project_name
        self.snapshots_path = self.project_path / "snapshots"
        self.metadata_path = self.project_path / "metadata"
        self.temp_path = self.project_path / "temp"
        self.index_path = self.metadata_path / "index.db"
        
        # Initialize storage index
        self._index: Optional[StorageIndex] = None
        self._index_lock = asyncio.Lock()
        
        # Create directory structure
        self._ensure_directory_structure()
        
        logger.info(f"Storage backend initialized for project '{project_name}' at {self.base_path}")
    
    def _ensure_directory_structure(self) -> None:
        """Ensure storage directory structure exists."""
        for path in [self.snapshots_path, self.metadata_path, self.temp_path]:
            path.mkdir(parents=True, exist_ok=True)
    
    async def get_snapshot_path(self, branch: str, snapshot_name: str) -> Path:
        """
        Get organized storage path for snapshot.
        
        Args:
            branch: Git branch name
            snapshot_name: Snapshot name
            
        Returns:
            Path to snapshot directory
        """
        # Sanitize branch name for filesystem
        safe_branch = self._sanitize_branch_name(branch)
        branch_path = self.snapshots_path / safe_branch
        return branch_path / snapshot_name
    
    def _sanitize_branch_name(self, branch: str) -> str:
        """Sanitize branch name for filesystem usage."""
        # Replace problematic characters
        safe_name = branch.replace("/", "_").replace("\\", "_")
        safe_name = safe_name.replace(":", "_").replace("*", "_")
        safe_name = safe_name.replace("?", "_").replace('"', "_")
        safe_name = safe_name.replace("<", "_").replace(">", "_")
        safe_name = safe_name.replace("|", "_")
        
        # Limit length
        if len(safe_name) > 100:
            safe_name = safe_name[:100]
        
        return safe_name
    
    async def store_snapshot(
        self,
        snapshot_metadata: SnapshotMetadata,
        source_path: Path,
        branch: str,
        parent_branch: Optional[str] = None,
        git_commit: Optional[str] = None,
        git_author: Optional[str] = None
    ) -> StorageEntry:
        """
        Store snapshot with atomic operations and metadata tracking.
        
        Args:
            snapshot_metadata: Snapshot metadata from engine
            source_path: Source snapshot directory
            branch: Git branch name
            parent_branch: Parent branch for ancestry
            git_commit: Git commit hash
            git_author: Git commit author
            
        Returns:
            StorageEntry for the stored snapshot
            
        Raises:
            StorageError: If storage operation fails
        """
        target_path = await self.get_snapshot_path(branch, snapshot_metadata.name)
        
        # Check if snapshot already exists
        if target_path.exists():
            raise StorageError(f"Snapshot already exists at {target_path}")
        
        snapshot_id = str(uuid.uuid4())
        
        try:
            # Use atomic operation for safe storage
            async with self.atomic_manager.atomic_operation(
                target_path=target_path,
                backup_existing=False,
                cleanup_on_success=True
            ) as atomic_ctx:
                
                # Copy snapshot directory to temporary location
                temp_snapshot_path = await self.atomic_manager.get_temp_dir_path(
                    atomic_ctx, snapshot_metadata.name
                )
                
                # Copy all files from source to temp
                await self._copy_directory_async(source_path, temp_snapshot_path)
                
                # Calculate storage metadata
                total_size = await self._calculate_directory_size(temp_snapshot_path)
                compressed_size = sum(f.size_bytes for f in snapshot_metadata.files)
                checksum = await self._calculate_directory_checksum(temp_snapshot_path)
                
                # Create storage entry
                storage_entry = StorageEntry(
                    snapshot_id=snapshot_id,
                    name=snapshot_metadata.name,
                    branch=branch,
                    parent_branch=parent_branch,
                    path=target_path,
                    size_bytes=total_size,
                    compressed_size_bytes=compressed_size,
                    checksum=checksum,
                    created_at=snapshot_metadata.created_at,
                    status=StorageEntryStatus.ACTIVE,
                    tags=snapshot_metadata.tags,
                    description=snapshot_metadata.description,
                    database_type=snapshot_metadata.database.type,
                    database_version=snapshot_metadata.database.version,
                    compression_type=snapshot_metadata.compression.value,
                    compression_ratio=snapshot_metadata.compression_ratio,
                    git_commit=git_commit,
                    git_author=git_author
                )
                
                # Add to storage index
                await self._add_to_index(storage_entry)
                
                # Update branch ancestry
                await self._update_branch_ancestry(branch, parent_branch, snapshot_id)
                
                logger.info(f"Stored snapshot {snapshot_metadata.name} at {target_path}")
                return storage_entry
                
        except Exception as e:
            logger.error(f"Failed to store snapshot {snapshot_metadata.name}: {e}")
            raise StorageError(f"Failed to store snapshot: {str(e)}")
    
    async def retrieve_snapshot(
        self,
        snapshot_id: str,
        update_access_time: bool = True
    ) -> Optional[StorageEntry]:
        """
        Retrieve snapshot entry by ID.
        
        Args:
            snapshot_id: Snapshot identifier
            update_access_time: Whether to update last access time
            
        Returns:
            StorageEntry if found, None otherwise
        """
        index = await self._get_index()
        entry = index.entries.get(snapshot_id)
        
        if entry and update_access_time:
            entry.last_accessed = datetime.utcnow()
            await self._update_index_entry(entry)
        
        return entry
    
    async def list_snapshots(
        self,
        branch: Optional[str] = None,
        tags: Optional[Set[str]] = None,
        status: Optional[StorageEntryStatus] = None,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[StorageEntry]:
        """
        List snapshots with filtering and pagination.
        
        Args:
            branch: Filter by branch name
            tags: Filter by tags (any match)
            status: Filter by status
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List of matching StorageEntry objects
        """
        index = await self._get_index()
        snapshots = list(index.entries.values())
        
        # Apply filters
        if branch:
            snapshots = [s for s in snapshots if s.branch == branch]
        
        if tags:
            snapshots = [s for s in snapshots if any(tag in s.tags for tag in tags)]
        
        if status:
            snapshots = [s for s in snapshots if s.status == status]
        
        # Sort by creation time (newest first)
        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        
        # Apply pagination
        if offset > 0:
            snapshots = snapshots[offset:]
        
        if limit:
            snapshots = snapshots[:limit]
        
        return snapshots
    
    async def delete_snapshot(self, snapshot_id: str, force: bool = False) -> bool:
        """
        Delete snapshot with atomic operations.
        
        Args:
            snapshot_id: Snapshot identifier
            force: Force deletion even if snapshot has dependencies
            
        Returns:
            True if deleted successfully
            
        Raises:
            StorageError: If deletion fails
            ValidationError: If snapshot has dependencies and force=False
        """
        index = await self._get_index()
        entry = index.entries.get(snapshot_id)
        
        if not entry:
            logger.warning(f"Snapshot {snapshot_id} not found in index")
            return False
        
        # Check for dependencies unless forcing
        if not force and entry.child_snapshots:
            raise ValidationError(
                f"Snapshot {snapshot_id} has child snapshots: {entry.child_snapshots}. "
                "Use force=True to delete anyway."
            )
        
        try:
            # Use atomic operation for safe deletion
            async with self.atomic_manager.atomic_operation(
                target_path=entry.path,
                backup_existing=True,
                cleanup_on_success=True
            ) as atomic_ctx:
                
                # Remove from filesystem
                if entry.path.exists():
                    await asyncio.get_event_loop().run_in_executor(
                        None, shutil.rmtree, entry.path
                    )
                
                # Remove from index
                await self._remove_from_index(snapshot_id)
                
                # Update branch ancestry
                await self._update_ancestry_after_deletion(entry)
                
                logger.info(f"Deleted snapshot {snapshot_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete snapshot {snapshot_id}: {e}")
            raise StorageError(f"Failed to delete snapshot: {str(e)}")
    
    async def get_storage_stats(self) -> StorageStats:
        """
        Get comprehensive storage statistics.
        
        Returns:
            StorageStats with usage and health information
        """
        index = await self._get_index()
        entries = list(index.entries.values())
        
        if not entries:
            return StorageStats(
                total_snapshots=0,
                total_size_bytes=0,
                total_compressed_bytes=0,
                average_compression_ratio=0.0,
                storage_efficiency=0.0,
                storage_usage_percentage=0.0
            )
        
        # Calculate basic statistics
        total_snapshots = len(entries)
        total_size = sum(e.size_bytes for e in entries)
        total_compressed = sum(e.compressed_size_bytes for e in entries)
        
        # Calculate compression statistics
        compression_ratios = [e.compression_ratio for e in entries if e.compression_ratio > 0]
        avg_compression = sum(compression_ratios) / len(compression_ratios) if compression_ratios else 1.0
        storage_efficiency = (1.0 - (total_compressed / total_size)) * 100 if total_size > 0 else 0.0
        
        # Calculate branch statistics
        branch_stats = {}
        for entry in entries:
            if entry.branch not in branch_stats:
                branch_stats[entry.branch] = {
                    "count": 0,
                    "size_bytes": 0,
                    "compressed_bytes": 0,
                    "avg_compression_ratio": 0.0
                }
            
            stats = branch_stats[entry.branch]
            stats["count"] += 1
            stats["size_bytes"] += entry.size_bytes
            stats["compressed_bytes"] += entry.compressed_size_bytes
        
        # Calculate average compression per branch
        for branch, stats in branch_stats.items():
            if stats["size_bytes"] > 0:
                stats["avg_compression_ratio"] = stats["size_bytes"] / stats["compressed_bytes"]
        
        # Calculate health metrics
        corrupted_count = len([e for e in entries if e.status == StorageEntryStatus.CORRUPTED])
        orphaned_count = len([e for e in entries if e.status == StorageEntryStatus.ORPHANED])
        
        # Calculate storage usage percentage
        storage_limit = self._parse_size_string(self.storage_config.max_size)
        usage_percentage = total_compressed / storage_limit if storage_limit > 0 else 0.0
        
        # Find temporal bounds
        sorted_entries = sorted(entries, key=lambda e: e.created_at)
        oldest = sorted_entries[0].created_at if sorted_entries else None
        newest = sorted_entries[-1].created_at if sorted_entries else None
        
        return StorageStats(
            total_snapshots=total_snapshots,
            total_size_bytes=total_size,
            total_compressed_bytes=total_compressed,
            branch_stats=branch_stats,
            average_compression_ratio=avg_compression,
            storage_efficiency=storage_efficiency,
            corrupted_snapshots=corrupted_count,
            orphaned_snapshots=orphaned_count,
            storage_limit_bytes=storage_limit,
            storage_usage_percentage=usage_percentage,
            storage_warning_threshold=self.storage_config.monitoring_threshold,
            oldest_snapshot=oldest,
            newest_snapshot=newest
        )
    
    async def validate_storage_integrity(self) -> StorageValidationResult:
        """
        Validate storage integrity and detect issues.
        
        Returns:
            StorageValidationResult with validation details
        """
        start_time = datetime.utcnow()
        index = await self._get_index()
        
        total_snapshots = len(index.entries)
        valid_snapshots = 0
        corrupted_snapshots = []
        orphaned_files = []
        missing_files = []
        index_inconsistencies = []
        repairable_issues = []
        manual_fixes_required = []
        
        # Validate each snapshot entry
        for snapshot_id, entry in index.entries.items():
            try:
                # Check if snapshot directory exists
                if not entry.path.exists():
                    missing_files.append(str(entry.path))
                    corrupted_snapshots.append(snapshot_id)
                    repairable_issues.append(f"Missing snapshot directory: {entry.path}")
                    continue
                
                # Check if metadata file exists
                metadata_file = entry.path / "metadata.json"
                if not metadata_file.exists():
                    missing_files.append(str(metadata_file))
                    corrupted_snapshots.append(snapshot_id)
                    repairable_issues.append(f"Missing metadata file: {metadata_file}")
                    continue
                
                # Verify checksum if possible
                actual_checksum = await self._calculate_directory_checksum(entry.path)
                if actual_checksum != entry.checksum:
                    corrupted_snapshots.append(snapshot_id)
                    manual_fixes_required.append(
                        f"Checksum mismatch for {snapshot_id}: "
                        f"expected {entry.checksum}, got {actual_checksum}"
                    )
                    continue
                
                valid_snapshots += 1
                
            except Exception as e:
                corrupted_snapshots.append(snapshot_id)
                manual_fixes_required.append(f"Validation error for {snapshot_id}: {str(e)}")
        
        # Check for orphaned files (files not in index)
        if self.snapshots_path.exists():
            for branch_dir in self.snapshots_path.iterdir():
                if not branch_dir.is_dir():
                    continue
                
                for snapshot_dir in branch_dir.iterdir():
                    if not snapshot_dir.is_dir():
                        continue
                    
                    # Check if this snapshot is in the index
                    snapshot_in_index = any(
                        entry.path == snapshot_dir 
                        for entry in index.entries.values()
                    )
                    
                    if not snapshot_in_index:
                        orphaned_files.append(str(snapshot_dir))
                        repairable_issues.append(f"Orphaned snapshot directory: {snapshot_dir}")
        
        # Validate index consistency
        index_valid = True
        
        # Check branch index consistency
        for branch, snapshot_ids in index.branch_index.items():
            for snapshot_id in snapshot_ids:
                if snapshot_id not in index.entries:
                    index_inconsistencies.append(f"Branch index references missing snapshot: {snapshot_id}")
                    index_valid = False
                elif index.entries[snapshot_id].branch != branch:
                    index_inconsistencies.append(
                        f"Branch index mismatch: {snapshot_id} indexed under {branch} "
                        f"but belongs to {index.entries[snapshot_id].branch}"
                    )
                    index_valid = False
        
        validation_time = (datetime.utcnow() - start_time).total_seconds()
        
        return StorageValidationResult(
            valid=valid_snapshots == total_snapshots and index_valid,
            total_snapshots=total_snapshots,
            valid_snapshots=valid_snapshots,
            corrupted_snapshots=corrupted_snapshots,
            orphaned_files=orphaned_files,
            missing_files=missing_files,
            index_valid=index_valid,
            index_inconsistencies=index_inconsistencies,
            repairable_issues=repairable_issues,
            manual_fixes_required=manual_fixes_required,
            validation_time_seconds=validation_time
        )
    
    async def repair_storage(
        self,
        auto_repair: bool = True,
        remove_orphaned: bool = False
    ) -> StorageValidationResult:
        """
        Repair storage issues automatically where possible.
        
        Args:
            auto_repair: Whether to automatically repair repairable issues
            remove_orphaned: Whether to remove orphaned files
            
        Returns:
            StorageValidationResult after repair
        """
        logger.info("Starting storage repair operation")
        
        # First validate to identify issues
        validation_result = await self.validate_storage_integrity()
        
        if not auto_repair:
            return validation_result
        
        repairs_made = 0
        
        try:
            # Remove orphaned files if requested
            if remove_orphaned and validation_result.orphaned_files:
                for orphaned_path_str in validation_result.orphaned_files:
                    orphaned_path = Path(orphaned_path_str)
                    if orphaned_path.exists():
                        try:
                            if orphaned_path.is_dir():
                                await asyncio.get_event_loop().run_in_executor(
                                    None, shutil.rmtree, orphaned_path
                                )
                            else:
                                orphaned_path.unlink()
                            repairs_made += 1
                            logger.info(f"Removed orphaned file: {orphaned_path}")
                        except Exception as e:
                            logger.error(f"Failed to remove orphaned file {orphaned_path}: {e}")
            
            # Remove corrupted entries from index
            index = await self._get_index()
            for snapshot_id in validation_result.corrupted_snapshots:
                if snapshot_id in index.entries:
                    index.remove_entry(snapshot_id)
                    repairs_made += 1
                    logger.info(f"Removed corrupted snapshot from index: {snapshot_id}")
            
            # Rebuild indexes if inconsistent
            if not validation_result.index_valid:
                await self._rebuild_indexes()
                repairs_made += 1
                logger.info("Rebuilt storage indexes")
            
            # Save repaired index
            if repairs_made > 0:
                await self._save_index()
                logger.info(f"Storage repair completed: {repairs_made} issues fixed")
            
        except Exception as e:
            logger.error(f"Storage repair failed: {e}")
            raise StorageError(f"Storage repair failed: {str(e)}")
        
        # Validate again to confirm repairs
        return await self.validate_storage_integrity()
    
    async def get_branch_ancestry(self, branch: str) -> Optional[BranchAncestry]:
        """
        Get branch ancestry information.
        
        Args:
            branch: Branch name
            
        Returns:
            BranchAncestry if found, None otherwise
        """
        index = await self._get_index()
        return index.ancestry.get(branch)
    
    async def get_fallback_chain(self, branch: str) -> List[str]:
        """
        Get fallback chain for branch (from branch to root).
        
        Args:
            branch: Branch name
            
        Returns:
            List of branch names in fallback order
        """
        index = await self._get_index()
        chain = []
        current_branch = branch
        
        # Build chain by following parent relationships
        visited = set()
        while current_branch and current_branch not in visited:
            chain.append(current_branch)
            visited.add(current_branch)
            
            ancestry = index.ancestry.get(current_branch)
            if ancestry and ancestry.parent_branch:
                current_branch = ancestry.parent_branch
            else:
                break
        
        return chain
    
    async def compact_storage(self) -> Dict[str, int]:
        """
        Compact storage by rebuilding indexes and cleaning up metadata.
        
        Returns:
            Dictionary with compaction statistics
        """
        logger.info("Starting storage compaction")
        
        start_time = datetime.utcnow()
        
        # Rebuild indexes from filesystem
        await self._rebuild_indexes()
        
        # Vacuum SQLite database if it exists
        vacuum_count = 0
        if self.index_path.exists():
            try:
                await self._vacuum_index_database()
                vacuum_count = 1
            except Exception as e:
                logger.warning(f"Failed to vacuum index database: {e}")
        
        # Clean up temporary files
        temp_cleaned = 0
        if self.temp_path.exists():
            temp_cleaned = await self._cleanup_temp_directory()
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        stats = {
            "indexes_rebuilt": 1,
            "database_vacuumed": vacuum_count,
            "temp_files_cleaned": temp_cleaned,
            "duration_seconds": duration
        }
        
        logger.info(f"Storage compaction completed: {stats}")
        return stats
    
    # Private methods
    
    async def _get_index(self) -> StorageIndex:
        """Get storage index, loading from disk if necessary."""
        if self._index is None:
            async with self._index_lock:
                if self._index is None:
                    await self._load_index()
        return self._index
    
    async def _load_index(self) -> None:
        """Load storage index from disk."""
        index_file = self.metadata_path / "index.json"
        
        if index_file.exists():
            try:
                content = await self._read_file_async(index_file)
                index_data = json.loads(content.decode())
                self._index = StorageIndex(**index_data)
                logger.debug(f"Loaded storage index with {len(self._index.entries)} entries")
            except Exception as e:
                logger.warning(f"Failed to load storage index: {e}")
                self._index = StorageIndex()
        else:
            self._index = StorageIndex()
            logger.debug("Created new storage index")
    
    async def _save_index(self) -> None:
        """Save storage index to disk."""
        if self._index is None:
            return
        
        index_file = self.metadata_path / "index.json"
        
        try:
            # Create atomic backup
            async with self.atomic_manager.atomic_operation(
                target_path=index_file,
                backup_existing=True,
                cleanup_on_success=True
            ) as atomic_ctx:
                
                temp_file = await self.atomic_manager.get_temp_file_path(
                    atomic_ctx, "index.json"
                )
                
                # Serialize index
                index_data = self._index.dict()
                content = json.dumps(index_data, indent=2, default=str)
                
                await self._write_file_async(temp_file, content.encode())
                
                logger.debug("Saved storage index")
                
        except Exception as e:
            logger.error(f"Failed to save storage index: {e}")
            raise StorageError(f"Failed to save storage index: {str(e)}")
    
    async def _add_to_index(self, entry: StorageEntry) -> None:
        """Add entry to storage index."""
        index = await self._get_index()
        index.add_entry(entry)
        await self._save_index()
    
    async def _remove_from_index(self, snapshot_id: str) -> Optional[StorageEntry]:
        """Remove entry from storage index."""
        index = await self._get_index()
        removed_entry = index.remove_entry(snapshot_id)
        if removed_entry:
            await self._save_index()
        return removed_entry
    
    async def _update_index_entry(self, entry: StorageEntry) -> None:
        """Update existing index entry."""
        index = await self._get_index()
        index.entries[entry.snapshot_id] = entry
        index.last_updated = datetime.utcnow()
        await self._save_index()
    
    async def _update_branch_ancestry(
        self,
        branch: str,
        parent_branch: Optional[str],
        snapshot_id: str
    ) -> None:
        """Update branch ancestry information."""
        index = await self._get_index()
        
        # Get or create branch ancestry
        ancestry = index.ancestry.get(branch)
        if ancestry is None:
            ancestry = BranchAncestry(
                branch_name=branch,
                parent_branch=parent_branch,
                created_at=datetime.utcnow()
            )
        
        # Update ancestry information
        ancestry.latest_snapshot = snapshot_id
        ancestry.last_updated = datetime.utcnow()
        ancestry.snapshot_count += 1
        
        if ancestry.oldest_snapshot is None:
            ancestry.oldest_snapshot = snapshot_id
        
        index.ancestry[branch] = ancestry
        await self._save_index()
    
    async def _update_ancestry_after_deletion(self, deleted_entry: StorageEntry) -> None:
        """Update ancestry information after snapshot deletion."""
        index = await self._get_index()
        ancestry = index.ancestry.get(deleted_entry.branch)
        
        if ancestry:
            ancestry.snapshot_count = max(0, ancestry.snapshot_count - 1)
            
            # If this was the latest snapshot, find new latest
            if ancestry.latest_snapshot == deleted_entry.snapshot_id:
                branch_snapshots = index.get_snapshots_by_branch(deleted_entry.branch)
                if branch_snapshots:
                    latest = max(branch_snapshots, key=lambda s: s.created_at)
                    ancestry.latest_snapshot = latest.snapshot_id
                else:
                    ancestry.latest_snapshot = None
            
            # If this was the oldest snapshot, find new oldest
            if ancestry.oldest_snapshot == deleted_entry.snapshot_id:
                branch_snapshots = index.get_snapshots_by_branch(deleted_entry.branch)
                if branch_snapshots:
                    oldest = min(branch_snapshots, key=lambda s: s.created_at)
                    ancestry.oldest_snapshot = oldest.snapshot_id
                else:
                    ancestry.oldest_snapshot = None
            
            ancestry.last_updated = datetime.utcnow()
            
            # Remove ancestry if no snapshots remain
            if ancestry.snapshot_count == 0:
                del index.ancestry[deleted_entry.branch]
            
            await self._save_index()
    
    async def _rebuild_indexes(self) -> None:
        """Rebuild all indexes from filesystem."""
        logger.info("Rebuilding storage indexes from filesystem")
        
        new_index = StorageIndex()
        
        # Scan filesystem for snapshots
        if self.snapshots_path.exists():
            for branch_dir in self.snapshots_path.iterdir():
                if not branch_dir.is_dir():
                    continue
                
                branch_name = branch_dir.name
                
                for snapshot_dir in branch_dir.iterdir():
                    if not snapshot_dir.is_dir():
                        continue
                    
                    try:
                        # Load snapshot metadata
                        metadata_file = snapshot_dir / "metadata.json"
                        if not metadata_file.exists():
                            logger.warning(f"Skipping snapshot without metadata: {snapshot_dir}")
                            continue
                        
                        content = await self._read_file_async(metadata_file)
                        metadata_dict = json.loads(content.decode())
                        
                        # Create storage entry from metadata
                        snapshot_id = str(uuid.uuid4())  # Generate new ID
                        
                        # Calculate current metrics
                        total_size = await self._calculate_directory_size(snapshot_dir)
                        checksum = await self._calculate_directory_checksum(snapshot_dir)
                        
                        entry = StorageEntry(
                            snapshot_id=snapshot_id,
                            name=metadata_dict.get("name", snapshot_dir.name),
                            branch=branch_name,
                            path=snapshot_dir,
                            size_bytes=total_size,
                            compressed_size_bytes=metadata_dict.get("total_size_bytes", total_size),
                            checksum=checksum,
                            created_at=datetime.fromisoformat(
                                metadata_dict.get("created_at", datetime.utcnow().isoformat())
                            ),
                            status=StorageEntryStatus.ACTIVE,
                            tags=metadata_dict.get("tags", []),
                            description=metadata_dict.get("description"),
                            database_type=metadata_dict.get("database", {}).get("type", "unknown"),
                            database_version=metadata_dict.get("database", {}).get("version", "unknown"),
                            compression_type=metadata_dict.get("compression", "gzip"),
                            compression_ratio=metadata_dict.get("compression_ratio", 1.0)
                        )
                        
                        new_index.add_entry(entry)
                        
                    except Exception as e:
                        logger.error(f"Failed to rebuild index entry for {snapshot_dir}: {e}")
        
        # Replace current index
        self._index = new_index
        await self._save_index()
        
        logger.info(f"Index rebuild completed: {len(new_index.entries)} entries")
    
    async def _cleanup_temp_directory(self) -> int:
        """Clean up temporary directory and return number of files cleaned."""
        cleaned_count = 0
        
        if not self.temp_path.exists():
            return cleaned_count
        
        try:
            for item in self.temp_path.iterdir():
                try:
                    if item.is_dir():
                        await asyncio.get_event_loop().run_in_executor(
                            None, shutil.rmtree, item
                        )
                    else:
                        item.unlink()
                    cleaned_count += 1
                except Exception as e:
                    logger.warning(f"Failed to clean up temp item {item}: {e}")
        
        except Exception as e:
            logger.error(f"Failed to clean up temp directory: {e}")
        
        return cleaned_count
    
    async def _vacuum_index_database(self) -> None:
        """Vacuum SQLite index database if it exists."""
        # This would vacuum the SQLite database
        # For now, this is a placeholder since we're using JSON
        pass
    
    async def _copy_directory_async(self, source: Path, destination: Path) -> None:
        """Copy directory asynchronously."""
        def _copy_sync():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        
        await asyncio.get_event_loop().run_in_executor(None, _copy_sync)
    
    async def _calculate_directory_size(self, directory: Path) -> int:
        """Calculate total size of directory."""
        def _calc_size_sync():
            total_size = 0
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    total_size += file_path.stat().st_size
            return total_size
        
        return await asyncio.get_event_loop().run_in_executor(None, _calc_size_sync)
    
    async def _calculate_directory_checksum(self, directory: Path) -> str:
        """Calculate SHA256 checksum of directory contents."""
        def _calc_checksum_sync():
            hash_sha256 = hashlib.sha256()
            
            # Sort files for deterministic hashing
            files = sorted(directory.rglob("*"))
            
            for file_path in files:
                if file_path.is_file():
                    # Include file path in hash for structure integrity
                    relative_path = file_path.relative_to(directory)
                    hash_sha256.update(str(relative_path).encode())
                    
                    # Include file content
                    with open(file_path, 'rb') as f:
                        while chunk := f.read(8192):
                            hash_sha256.update(chunk)
            
            return hash_sha256.hexdigest()
        
        return await asyncio.get_event_loop().run_in_executor(None, _calc_checksum_sync)
    
    def _parse_size_string(self, size_str: str) -> int:
        """Parse size string (e.g., '10GB') to bytes."""
        import re
        
        match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT]?B)$', size_str.upper())
        if not match:
            raise ValueError(f"Invalid size format: {size_str}")
        
        number, unit = match.groups()
        number = float(number)
        
        multipliers = {
            'B': 1,
            'KB': 1024,
            'MB': 1024 ** 2,
            'GB': 1024 ** 3,
            'TB': 1024 ** 4,
        }
        
        return int(number * multipliers[unit])
    
    async def _read_file_async(self, file_path: Path) -> bytes:
        """Read file asynchronously."""
        def _read_sync():
            with open(file_path, 'rb') as f:
                return f.read()
        
        return await asyncio.get_event_loop().run_in_executor(None, _read_sync)
    
    async def _write_file_async(self, file_path: Path, content: bytes) -> None:
        """Write file asynchronously."""
        def _write_sync():
            with open(file_path, 'wb') as f:
                f.write(content)
        
        await asyncio.get_event_loop().run_in_executor(None, _write_sync)