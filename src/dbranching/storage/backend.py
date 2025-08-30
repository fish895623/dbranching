"""Storage backend for database snapshots with atomic operations and organization."""

import asyncio
import hashlib
import logging
import sqlite3
import uuid
import os
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
    Storage backend for database snapshots providing atomic operations,
    metadata tracking, and efficient organization.
    
    Features:
    - Atomic storage operations with rollback
    - Branch ancestry tracking for fallback chains
    - Metadata indexing with SQLite/JSON
    - Storage validation and integrity checks
    - Efficient snapshot organization by project/branch
    """
    
    def __init__(self, storage_config: StorageConfig, project_name: str):
        """
        Initialize storage backend.
        
        Args:
            storage_config: Storage configuration
            project_name: Project name for organization
        """
        self.storage_config = storage_config
        self.project_name = project_name
        
        # Setup paths
        self.project_path = storage_config.path / project_name
        self.snapshots_path = self.project_path / "snapshots"
        self.metadata_path = self.project_path / "metadata"
        self.temp_path = self.project_path / "temp"
        
        # Initialize atomic operation manager
        self.atomic_manager = AtomicOperationManager(base_temp_dir=self.temp_path)
        
        # Create directory structure
        for path in [self.project_path, self.snapshots_path, self.metadata_path, self.temp_path]:
            path.mkdir(parents=True, exist_ok=True)
        
        # Initialize metadata index
        self.index_db_path = self.metadata_path / "storage_index.db"
        self._index_initialized = False
        
        logger.info(f"Storage backend initialized for project '{project_name}'")
    
    async def _ensure_index_initialized(self) -> None:
        """Ensure SQLite index is initialized (call before first use)."""
        if not self._index_initialized:
            await self._initialize_index()
            self._index_initialized = True
    
    async def _initialize_index(self) -> None:
        """Initialize SQLite index for metadata."""
        def _create_tables():
            with sqlite3.connect(self.index_db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS snapshots (
                        snapshot_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        branch TEXT NOT NULL,
                        parent_branch TEXT,
                        path TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        compressed_size_bytes INTEGER NOT NULL,
                        checksum TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        last_accessed TEXT,
                        database_type TEXT NOT NULL,
                        database_version TEXT NOT NULL,
                        compression_type TEXT NOT NULL,
                        compression_ratio REAL NOT NULL,
                        git_commit TEXT,
                        git_author TEXT,
                        status TEXT NOT NULL DEFAULT 'active',
                        tags TEXT,
                        description TEXT
                    )
                """)
                
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS branch_ancestry (
                        branch TEXT PRIMARY KEY,
                        parent_branch TEXT,
                        ancestor_snapshots TEXT,
                        snapshots TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                
                conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_branch ON snapshots(branch)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_created_at ON snapshots(created_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_checksum ON snapshots(checksum)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_status ON snapshots(status)")
        
        await asyncio.get_event_loop().run_in_executor(None, _create_tables)
    
    async def get_snapshot_path(self, branch: str, snapshot_name: str) -> Path:
        """
        Get path for snapshot storage with branch organization.
        
        Args:
            branch: Git branch name  
            snapshot_name: Snapshot name
            
        Returns:
            Path for snapshot storage
        """
        # Sanitize branch name for filesystem
        safe_branch = branch.replace("/", "_").replace("\\", "_")
        return self.snapshots_path / safe_branch / snapshot_name
    
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
        await self._ensure_index_initialized()
        
        target_path = await self.get_snapshot_path(branch, snapshot_metadata.name)
        
        # Check if snapshot already exists
        if target_path.exists():
            raise StorageError(f"Snapshot already exists at {target_path}")
        
        # Validate source path
        if not source_path.exists() or not source_path.is_dir():
            raise StorageError(f"Invalid source path: {source_path}")
        
        try:
            # Use atomic operation for safe storage
            async with self.atomic_manager.atomic_operation(
                target_path=target_path,
                backup_existing=False,
                cleanup_on_success=True
            ) as context:
                
                # Copy snapshot files to temporary location
                temp_snapshot_path = context.temp_dir / "snapshot"
                await self._copy_snapshot_files(source_path, temp_snapshot_path)
                
                # Calculate checksum for integrity
                checksum = await self._calculate_directory_checksum(temp_snapshot_path)
                
                # Create storage entry
                storage_entry = StorageEntry(
                    snapshot_id=str(uuid.uuid4()),
                    name=snapshot_metadata.name,
                    branch=branch,
                    parent_branch=parent_branch,
                    path=target_path,
                    size_bytes=snapshot_metadata.total_size_bytes,
                    compressed_size_bytes=snapshot_metadata.total_size_bytes,  # Will be updated after copy
                    checksum=checksum,
                    created_at=datetime.utcnow(),
                    database_type=snapshot_metadata.database.type,
                    database_version=snapshot_metadata.database.version,
                    compression_type=snapshot_metadata.compression.value,
                    compression_ratio=snapshot_metadata.compression_ratio,
                    git_commit=git_commit,
                    git_author=git_author,
                    tags=snapshot_metadata.tags,
                    description=snapshot_metadata.description
                )
                
                # Update compressed size based on actual files
                actual_size = await self._calculate_directory_size(temp_snapshot_path)
                storage_entry.compressed_size_bytes = actual_size
                
                # Store metadata
                await self._store_snapshot_metadata(storage_entry, snapshot_metadata, temp_snapshot_path)
                
                # Move from temp to final location (atomic commit)
                await self._atomic_move(temp_snapshot_path, target_path)
                
                # Update index
                await self._update_index(storage_entry)
                
                # Update branch ancestry
                await self._update_branch_ancestry(branch, parent_branch, storage_entry.snapshot_id)
                
                logger.info(f"Stored snapshot {storage_entry.snapshot_id} at {target_path}")
                return storage_entry
                
        except Exception as e:
            logger.error(f"Failed to store snapshot: {e}")
            raise StorageError(f"Storage operation failed: {str(e)}")
    
    async def retrieve_snapshot(
        self,
        snapshot_id: str,
        update_access_time: bool = True
    ) -> Optional[StorageEntry]:
        """
        Retrieve snapshot by ID.
        
        Args:
            snapshot_id: Snapshot identifier
            update_access_time: Whether to update last accessed time
            
        Returns:
            StorageEntry if found, None otherwise
        """
        await self._ensure_index_initialized()
        
        try:
            def _query_snapshot():
                with sqlite3.connect(self.index_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM snapshots WHERE snapshot_id = ?",
                        (snapshot_id,)
                    )
                    return cursor.fetchone()
            
            row = await asyncio.get_event_loop().run_in_executor(None, _query_snapshot)
            
            if not row:
                return None
            
            # Create storage entry from row
            storage_entry = StorageEntry(
                snapshot_id=row["snapshot_id"],
                name=row["name"],
                branch=row["branch"],
                parent_branch=row["parent_branch"],
                path=Path(row["path"]),
                size_bytes=row["size_bytes"],
                compressed_size_bytes=row["compressed_size_bytes"],
                checksum=row["checksum"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_accessed=datetime.fromisoformat(row["last_accessed"]) if row["last_accessed"] else None,
                database_type=row["database_type"],
                database_version=row["database_version"],
                compression_type=row["compression_type"],
                compression_ratio=row["compression_ratio"],
                git_commit=row["git_commit"],
                git_author=row["git_author"],
                status=StorageEntryStatus(row["status"]),
                tags=json.loads(row["tags"]) if row["tags"] else [],
                description=row["description"]
            )
            
            # Update access time if requested
            if update_access_time:
                await self._update_access_time(snapshot_id)
            
            return storage_entry
            
        except Exception as e:
            logger.error(f"Failed to retrieve snapshot {snapshot_id}: {e}")
            return None
    
    async def list_snapshots(
        self,
        branch: Optional[str] = None,
        status: Optional[StorageEntryStatus] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[StorageEntry]:
        """
        List snapshots with optional filtering.
        
        Args:
            branch: Filter by branch name
            status: Filter by status
            tags: Filter by tags (all must be present)
            limit: Maximum number of results
            
        Returns:
            List of StorageEntry objects
        """
        await self._ensure_index_initialized()
        
        try:
            def _query_snapshots():
                with sqlite3.connect(self.index_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    
                    query = "SELECT * FROM snapshots WHERE 1=1"
                    params = []
                    
                    if branch:
                        query += " AND branch = ?"
                        params.append(branch)
                    
                    if status:
                        query += " AND status = ?"
                        params.append(status.value)
                    
                    query += " ORDER BY created_at DESC"
                    
                    if limit:
                        query += " LIMIT ?"
                        params.append(limit)
                    
                    cursor = conn.execute(query, params)
                    return cursor.fetchall()
            
            rows = await asyncio.get_event_loop().run_in_executor(None, _query_snapshots)
            
            snapshots = []
            for row in rows:
                try:
                    storage_entry = StorageEntry(
                        snapshot_id=row["snapshot_id"],
                        name=row["name"],
                        branch=row["branch"],
                        parent_branch=row["parent_branch"],
                        path=Path(row["path"]),
                        size_bytes=row["size_bytes"],
                        compressed_size_bytes=row["compressed_size_bytes"],
                        checksum=row["checksum"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        last_accessed=datetime.fromisoformat(row["last_accessed"]) if row["last_accessed"] else None,
                        database_type=row["database_type"],
                        database_version=row["database_version"],
                        compression_type=row["compression_type"],
                        compression_ratio=row["compression_ratio"],
                        git_commit=row["git_commit"],
                        git_author=row["git_author"],
                        status=StorageEntryStatus(row["status"]),
                        tags=json.loads(row["tags"]) if row["tags"] else [],
                        description=row["description"]
                    )
                    
                    # Apply tag filtering if specified
                    if tags:
                        if all(tag in storage_entry.tags for tag in tags):
                            snapshots.append(storage_entry)
                    else:
                        snapshots.append(storage_entry)
                        
                except Exception as e:
                    logger.warning(f"Failed to parse snapshot entry: {e}")
                    continue
            
            return snapshots
            
        except Exception as e:
            logger.error(f"Failed to list snapshots: {e}")
            raise StorageError(f"Failed to list snapshots: {str(e)}")
    
    async def delete_snapshot(self, snapshot_id: str) -> bool:
        """
        Delete snapshot and update metadata.
        
        Args:
            snapshot_id: Snapshot identifier
            
        Returns:
            True if deleted, False if not found
            
        Raises:
            StorageError: If deletion fails
        """
        await self._ensure_index_initialized()
        
        try:
            # Get snapshot entry
            storage_entry = await self.retrieve_snapshot(snapshot_id, update_access_time=False)
            if not storage_entry:
                return False
            
            # Use atomic operation for safe deletion
            async with self.atomic_manager.atomic_operation(
                target_path=storage_entry.path,
                backup_existing=True,
                cleanup_on_success=False  # Keep backup until we're sure
            ) as context:
                
                # Remove from index first
                await self._remove_from_index(snapshot_id)
                
                # Remove snapshot directory
                if storage_entry.path.exists():
                    await self._remove_directory_async(storage_entry.path)
                
                # Update branch ancestry
                await self._remove_from_branch_ancestry(branch=storage_entry.branch, snapshot_id=snapshot_id)
                
                logger.info(f"Deleted snapshot {snapshot_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete snapshot {snapshot_id}: {e}")
            raise StorageError(f"Deletion failed: {str(e)}")
    
    async def get_branch_ancestry(self, branch: str) -> Optional[BranchAncestry]:
        """
        Get branch ancestry information.
        
        Args:
            branch: Branch name
            
        Returns:
            BranchAncestry if found, None otherwise
        """
        await self._ensure_index_initialized()
        
        try:
            def _query_ancestry():
                with sqlite3.connect(self.index_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT * FROM branch_ancestry WHERE branch = ?",
                        (branch,)
                    )
                    return cursor.fetchone()
            
            row = await asyncio.get_event_loop().run_in_executor(None, _query_ancestry)
            
            if not row:
                return None
            
            return BranchAncestry(
                branch=row["branch"],
                parent_branch=row["parent_branch"],
                ancestor_snapshots=json.loads(row["ancestor_snapshots"]) if row["ancestor_snapshots"] else [],
                snapshots=json.loads(row["snapshots"]) if row["snapshots"] else [],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            )
            
        except Exception as e:
            logger.error(f"Failed to get branch ancestry for {branch}: {e}")
            return None
    
    async def get_fallback_chain(self, branch: str) -> List[StorageEntry]:
        """
        Get fallback chain for branch (including ancestors).
        
        Args:
            branch: Branch name
            
        Returns:
            List of snapshots in fallback order
        """
        try:
            fallback_chain = []
            current_branch = branch
            visited_branches = set()
            
            while current_branch and current_branch not in visited_branches:
                visited_branches.add(current_branch)
                
                # Get snapshots for current branch
                branch_snapshots = await self.list_snapshots(
                    branch=current_branch,
                    status=StorageEntryStatus.ACTIVE
                )
                
                # Add latest snapshot from this branch
                if branch_snapshots:
                    latest_snapshot = sorted(branch_snapshots, key=lambda s: s.created_at, reverse=True)[0]
                    fallback_chain.append(latest_snapshot)
                
                # Get parent branch
                ancestry = await self.get_branch_ancestry(current_branch)
                current_branch = ancestry.parent_branch if ancestry else None
            
            return fallback_chain
            
        except Exception as e:
            logger.error(f"Failed to get fallback chain for {branch}: {e}")
            raise StorageError(f"Failed to get fallback chain: {str(e)}")
    
    async def validate_storage(self, snapshot_id: str) -> bool:
        """
        Validate storage integrity for snapshot.
        
        Args:
            snapshot_id: Snapshot identifier
            
        Returns:
            True if valid, False otherwise
        """
        try:
            storage_entry = await self.retrieve_snapshot(snapshot_id, update_access_time=False)
            if not storage_entry:
                return False
            
            # Check if path exists
            if not storage_entry.path.exists():
                return False
            
            # Verify checksum
            current_checksum = await self._calculate_directory_checksum(storage_entry.path)
            if current_checksum != storage_entry.checksum:
                logger.warning(f"Checksum mismatch for {snapshot_id}")
                return False
            
            # Verify metadata file exists and is valid
            metadata_file = storage_entry.path / "metadata.json"
            if not metadata_file.exists():
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to validate storage for {snapshot_id}: {e}")
            return False
    
    async def get_storage_stats(self) -> StorageStats:
        """
        Get comprehensive storage statistics.
        
        Returns:
            StorageStats with current statistics
        """
        await self._ensure_index_initialized()
        
        try:
            def _get_stats():
                with sqlite3.connect(self.index_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    
                    # Get basic counts and sizes
                    cursor = conn.execute("""
                        SELECT 
                            COUNT(*) as total_snapshots,
                            SUM(size_bytes) as total_size,
                            SUM(compressed_size_bytes) as total_compressed,
                            AVG(compression_ratio) as avg_compression_ratio,
                            COUNT(DISTINCT branch) as unique_branches
                        FROM snapshots 
                        WHERE status = 'active'
                    """)
                    basic_stats = cursor.fetchone()
                    
                    # Get branches
                    cursor = conn.execute("SELECT DISTINCT branch FROM snapshots WHERE status = 'active'")
                    branches = [row["branch"] for row in cursor.fetchall()]
                    
                    return basic_stats, branches
            
            basic_stats, branches = await asyncio.get_event_loop().run_in_executor(None, _get_stats)
            
            # Calculate additional statistics
            total_disk_usage = await self._calculate_disk_usage()
            free_space = await self._get_free_space()
            
            return StorageStats(
                total_snapshots=basic_stats["total_snapshots"] or 0,
                total_size_bytes=basic_stats["total_size"] or 0,
                total_compressed_bytes=basic_stats["total_compressed"] or 0,
                compression_savings_bytes=(basic_stats["total_size"] or 0) - (basic_stats["total_compressed"] or 0),
                average_compression_ratio=basic_stats["avg_compression_ratio"] or 1.0,
                storage_usage_bytes=total_disk_usage,
                free_space_bytes=free_space,
                branches=branches,
                oldest_snapshot=await self._get_oldest_snapshot_date(),
                newest_snapshot=await self._get_newest_snapshot_date()
            )
            
        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            raise StorageError(f"Failed to get storage stats: {str(e)}")
    
    # Private helper methods
    
    async def _copy_snapshot_files(self, source: Path, destination: Path) -> None:
        """Copy snapshot files from source to destination."""
        def _copy_sync():
            destination.mkdir(parents=True, exist_ok=True)
            for item in source.iterdir():
                if item.is_file():
                    shutil.copy2(item, destination / item.name)
                elif item.is_dir():
                    shutil.copytree(item, destination / item.name)
        
        await asyncio.get_event_loop().run_in_executor(None, _copy_sync)
    
    async def _store_snapshot_metadata(
        self,
        storage_entry: StorageEntry,
        snapshot_metadata: SnapshotMetadata,
        snapshot_path: Path
    ) -> None:
        """Store snapshot metadata in snapshot directory."""
        metadata_file = snapshot_path / "metadata.json"
        
        # Combine storage entry and snapshot metadata
        combined_metadata = {
            "storage_entry": storage_entry.dict(),
            "snapshot_metadata": snapshot_metadata.dict()
        }
        
        def _write_metadata():
            with open(metadata_file, 'w') as f:
                json.dump(combined_metadata, f, indent=2, default=str)
        
        await asyncio.get_event_loop().run_in_executor(None, _write_metadata)
    
    async def _atomic_move(self, source: Path, destination: Path) -> None:
        """Atomically move directory from source to destination."""
        def _move_sync():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        
        await asyncio.get_event_loop().run_in_executor(None, _move_sync)
    
    async def _update_index(self, storage_entry: StorageEntry) -> None:
        """Update SQLite index with storage entry."""
        def _update_sync():
            with sqlite3.connect(self.index_db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO snapshots (
                        snapshot_id, name, branch, parent_branch, path,
                        size_bytes, compressed_size_bytes, checksum,
                        created_at, last_accessed, database_type, database_version,
                        compression_type, compression_ratio, git_commit, git_author,
                        status, tags, description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    storage_entry.snapshot_id,
                    storage_entry.name,
                    storage_entry.branch,
                    storage_entry.parent_branch,
                    str(storage_entry.path),
                    storage_entry.size_bytes,
                    storage_entry.compressed_size_bytes,
                    storage_entry.checksum,
                    storage_entry.created_at.isoformat(),
                    storage_entry.last_accessed.isoformat() if storage_entry.last_accessed else None,
                    storage_entry.database_type,
                    storage_entry.database_version,
                    storage_entry.compression_type,
                    storage_entry.compression_ratio,
                    storage_entry.git_commit,
                    storage_entry.git_author,
                    storage_entry.status.value,
                    json.dumps(storage_entry.tags) if storage_entry.tags else None,
                    storage_entry.description
                ))
        
        await asyncio.get_event_loop().run_in_executor(None, _update_sync)
    
    async def _update_branch_ancestry(
        self,
        branch: str,
        parent_branch: Optional[str],
        snapshot_id: str
    ) -> None:
        """Update branch ancestry tracking."""
        try:
            def _update_ancestry():
                with sqlite3.connect(self.index_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    
                    # Get existing ancestry
                    cursor = conn.execute(
                        "SELECT * FROM branch_ancestry WHERE branch = ?",
                        (branch,)
                    )
                    existing = cursor.fetchone()
                    
                    if existing:
                        # Update existing ancestry
                        snapshots = json.loads(existing["snapshots"]) if existing["snapshots"] else []
                        if snapshot_id not in snapshots:
                            snapshots.append(snapshot_id)
                        
                        ancestor_snapshots = json.loads(existing["ancestor_snapshots"]) if existing["ancestor_snapshots"] else []
                        
                        # Update parent branch if provided
                        if parent_branch:
                            # Get parent's snapshots to add to ancestors
                            parent_cursor = conn.execute(
                                "SELECT snapshots FROM branch_ancestry WHERE branch = ?",
                                (parent_branch,)
                            )
                            parent_row = parent_cursor.fetchone()
                            if parent_row and parent_row["snapshots"]:
                                parent_snapshots = json.loads(parent_row["snapshots"])
                                for parent_snapshot in parent_snapshots:
                                    if parent_snapshot not in ancestor_snapshots:
                                        ancestor_snapshots.append(parent_snapshot)
                        
                        conn.execute("""
                            UPDATE branch_ancestry 
                            SET parent_branch = ?, ancestor_snapshots = ?, snapshots = ?, updated_at = ?
                            WHERE branch = ?
                        """, (
                            parent_branch,
                            json.dumps(ancestor_snapshots),
                            json.dumps(snapshots),
                            datetime.utcnow().isoformat(),
                            branch
                        ))
                    else:
                        # Create new ancestry
                        ancestor_snapshots = []
                        if parent_branch:
                            # Get parent's snapshots
                            parent_cursor = conn.execute(
                                "SELECT snapshots FROM branch_ancestry WHERE branch = ?",
                                (parent_branch,)
                            )
                            parent_row = parent_cursor.fetchone()
                            if parent_row and parent_row["snapshots"]:
                                ancestor_snapshots = json.loads(parent_row["snapshots"])
                        
                        conn.execute("""
                            INSERT INTO branch_ancestry (
                                branch, parent_branch, ancestor_snapshots, snapshots, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            branch,
                            parent_branch,
                            json.dumps(ancestor_snapshots),
                            json.dumps([snapshot_id]),
                            datetime.utcnow().isoformat(),
                            datetime.utcnow().isoformat()
                        ))
            
            await asyncio.get_event_loop().run_in_executor(None, _update_ancestry)
            
        except Exception as e:
            logger.error(f"Failed to update branch ancestry: {e}")
            # Don't raise exception for ancestry tracking failures
    
    async def _remove_from_index(self, snapshot_id: str) -> None:
        """Remove snapshot from index."""
        def _remove_sync():
            with sqlite3.connect(self.index_db_path) as conn:
                conn.execute("DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
        
        await asyncio.get_event_loop().run_in_executor(None, _remove_sync)
    
    async def _remove_from_branch_ancestry(self, branch: str, snapshot_id: str) -> None:
        """Remove snapshot from branch ancestry."""
        def _remove_sync():
            with sqlite3.connect(self.index_db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT snapshots FROM branch_ancestry WHERE branch = ?",
                    (branch,)
                )
                row = cursor.fetchone()
                
                if row and row["snapshots"]:
                    snapshots = json.loads(row["snapshots"])
                    if snapshot_id in snapshots:
                        snapshots.remove(snapshot_id)
                        
                        conn.execute("""
                            UPDATE branch_ancestry 
                            SET snapshots = ?, updated_at = ?
                            WHERE branch = ?
                        """, (
                            json.dumps(snapshots),
                            datetime.utcnow().isoformat(),
                            branch
                        ))
        
        await asyncio.get_event_loop().run_in_executor(None, _remove_sync)
    
    async def _update_access_time(self, snapshot_id: str) -> None:
        """Update last accessed time for snapshot."""
        def _update_sync():
            with sqlite3.connect(self.index_db_path) as conn:
                conn.execute(
                    "UPDATE snapshots SET last_accessed = ? WHERE snapshot_id = ?",
                    (datetime.utcnow().isoformat(), snapshot_id)
                )
        
        await asyncio.get_event_loop().run_in_executor(None, _update_sync)
    
    async def _remove_directory_async(self, path: Path) -> None:
        """Remove directory asynchronously."""
        def _remove_sync():
            if path.exists():
                shutil.rmtree(path)
        
        await asyncio.get_event_loop().run_in_executor(None, _remove_sync)
    
    async def _calculate_directory_checksum(self, directory: Path) -> str:
        """Calculate checksum for directory contents."""
        def _calc_checksum_sync():
            hash_sha256 = hashlib.sha256()
            
            # Sort files for consistent checksum
            files = sorted(directory.rglob("*"))
            for file_path in files:
                if file_path.is_file():
                    # Include relative path in hash for structure verification
                    rel_path = file_path.relative_to(directory)
                    hash_sha256.update(str(rel_path).encode())
                    
                    # Include file content
                    with open(file_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            hash_sha256.update(chunk)
            
            return hash_sha256.hexdigest()
        
        return await asyncio.get_event_loop().run_in_executor(None, _calc_checksum_sync)
    
    async def _calculate_directory_size(self, directory: Path) -> int:
        """Calculate total size of directory."""
        def _calc_size_sync():
            total_size = 0
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    total_size += file_path.stat().st_size
            return total_size
        
        return await asyncio.get_event_loop().run_in_executor(None, _calc_size_sync)
    
    async def _calculate_disk_usage(self) -> int:
        """Calculate total disk usage of storage."""
        def _calc_usage_sync():
            total_usage = 0
            for file_path in self.project_path.rglob("*"):
                if file_path.is_file():
                    total_usage += file_path.stat().st_size
            return total_usage
        
        return await asyncio.get_event_loop().run_in_executor(None, _calc_usage_sync)
    
    async def _get_free_space(self) -> int:
        """Get available free space."""
        def _get_space_sync():
            statvfs = os.statvfs(self.storage_config.path)
            return statvfs.f_bavail * statvfs.f_frsize
        
        try:
            return await asyncio.get_event_loop().run_in_executor(None, _get_space_sync)
        except:
            # Fallback if statvfs not available
            return 1024 * 1024 * 1024  # 1GB fallback
    
    async def _get_oldest_snapshot_date(self) -> Optional[datetime]:
        """Get creation date of oldest snapshot."""
        try:
            def _get_oldest():
                with sqlite3.connect(self.index_db_path) as conn:
                    cursor = conn.execute(
                        "SELECT MIN(created_at) as oldest FROM snapshots WHERE status = 'active'"
                    )
                    row = cursor.fetchone()
                    return row[0] if row and row[0] else None
            
            oldest_str = await asyncio.get_event_loop().run_in_executor(None, _get_oldest)
            return datetime.fromisoformat(oldest_str) if oldest_str else None
            
        except Exception:
            return None
    
    async def _get_newest_snapshot_date(self) -> Optional[datetime]:
        """Get creation date of newest snapshot."""
        try:
            def _get_newest():
                with sqlite3.connect(self.index_db_path) as conn:
                    cursor = conn.execute(
                        "SELECT MAX(created_at) as newest FROM snapshots WHERE status = 'active'"
                    )
                    row = cursor.fetchone()
                    return row[0] if row and row[0] else None
            
            newest_str = await asyncio.get_event_loop().run_in_executor(None, _get_newest)
            return datetime.fromisoformat(newest_str) if newest_str else None
            
        except Exception:
            return None