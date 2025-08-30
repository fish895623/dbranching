"""Integration interface between storage management and snapshot engine."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..config import StorageConfig
from ..snapshot.models import SnapshotMetadata, SnapshotInfo
from ..snapshot.engine import SnapshotEngine
from ..exceptions import StorageError, SnapshotError

from .backend import StorageBackend
from .cleanup import CleanupPolicyEngine
from .optimizer import StorageOptimizer
from .models import StorageEntry, CleanupResult, DeduplicationResult

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Storage manager that integrates storage backend with snapshot engine.
    
    Provides high-level storage operations including:
    - Snapshot storage with automatic organization
    - Cleanup policy management and execution
    - Storage optimization and deduplication
    - Integration with snapshot engine workflows
    """
    
    def __init__(
        self,
        storage_config: StorageConfig,
        project_name: str = "default",
        snapshot_engine: Optional[SnapshotEngine] = None
    ):
        """
        Initialize storage manager.
        
        Args:
            storage_config: Storage configuration
            project_name: Project name for storage organization
            snapshot_engine: Optional snapshot engine for integration
        """
        self.storage_config = storage_config
        self.project_name = project_name
        self.snapshot_engine = snapshot_engine
        
        # Initialize storage components
        self.backend = StorageBackend(storage_config, project_name)
        self.cleanup_engine = CleanupPolicyEngine(self.backend, storage_config)
        self.optimizer = StorageOptimizer(self.backend)
        
        logger.info(f"Storage manager initialized for project '{project_name}'")
    
    async def store_snapshot(
        self,
        snapshot_metadata: SnapshotMetadata,
        source_path: Path,
        branch: str,
        parent_branch: Optional[str] = None,
        git_commit: Optional[str] = None,
        git_author: Optional[str] = None,
        auto_cleanup: bool = True
    ) -> StorageEntry:
        """
        Store snapshot with automatic organization and optional cleanup.
        
        Args:
            snapshot_metadata: Snapshot metadata from engine
            source_path: Source snapshot directory
            branch: Git branch name
            parent_branch: Parent branch for ancestry
            git_commit: Git commit hash
            git_author: Git commit author
            auto_cleanup: Whether to run automatic cleanup after storage
            
        Returns:
            StorageEntry for the stored snapshot
            
        Raises:
            StorageError: If storage operation fails
        """
        try:
            # Store snapshot using backend
            storage_entry = await self.backend.store_snapshot(
                snapshot_metadata=snapshot_metadata,
                source_path=source_path,
                branch=branch,
                parent_branch=parent_branch,
                git_commit=git_commit,
                git_author=git_author
            )
            
            # Run automatic cleanup if requested
            if auto_cleanup:
                try:
                    cleanup_results = await self.cleanup_engine.execute_automatic_cleanup()
                    if cleanup_results:
                        total_cleaned = sum(r.total_deleted for r in cleanup_results)
                        logger.info(f"Automatic cleanup removed {total_cleaned} snapshots")
                except Exception as e:
                    # Don't fail storage if cleanup fails
                    logger.warning(f"Automatic cleanup failed: {e}")
            
            logger.info(f"Successfully stored snapshot {snapshot_metadata.name}")
            return storage_entry
            
        except Exception as e:
            logger.error(f"Failed to store snapshot {snapshot_metadata.name}: {e}")
            raise StorageError(f"Failed to store snapshot: {str(e)}")
    
    async def restore_snapshot(
        self,
        snapshot_id: str,
        target_database: Optional[str] = None
    ) -> SnapshotInfo:
        """
        Restore snapshot using integrated snapshot engine.
        
        Args:
            snapshot_id: Storage entry ID to restore
            target_database: Target database name (optional)
            
        Returns:
            SnapshotInfo with restoration details
            
        Raises:
            StorageError: If snapshot not found or restoration fails
        """
        if not self.snapshot_engine:
            raise StorageError("Snapshot engine not configured for restoration")
        
        try:
            # Retrieve storage entry
            storage_entry = await self.backend.retrieve_snapshot(snapshot_id)
            if not storage_entry:
                raise StorageError(f"Snapshot not found: {snapshot_id}")
            
            # Check if snapshot is deduplicated
            dedup_marker = storage_entry.path / ".deduplicated"
            if dedup_marker.exists():
                # Resolve original snapshot
                original_entry = await self._resolve_deduplicated_snapshot(storage_entry)
                if original_entry:
                    storage_entry = original_entry
            
            # Restore using snapshot engine
            snapshot_info = await self.snapshot_engine.restore_snapshot(
                name=storage_entry.name
            )
            
            # Update last accessed time
            storage_entry.last_accessed = datetime.utcnow()
            await self.backend._update_index_entry(storage_entry)
            
            logger.info(f"Successfully restored snapshot {snapshot_id}")
            return snapshot_info
            
        except Exception as e:
            logger.error(f"Failed to restore snapshot {snapshot_id}: {e}")
            if isinstance(e, StorageError):
                raise
            else:
                raise StorageError(f"Failed to restore snapshot: {str(e)}")
    
    async def list_snapshots_with_metadata(
        self,
        branch: Optional[str] = None,
        include_storage_stats: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List snapshots with combined storage and snapshot metadata.
        
        Args:
            branch: Filter by branch name
            include_storage_stats: Whether to include storage statistics
            
        Returns:
            List of dictionaries with combined metadata
        """
        try:
            # Get storage entries
            storage_entries = await self.backend.list_snapshots(branch=branch)
            
            # Get storage stats if requested
            storage_stats = None
            if include_storage_stats:
                storage_stats = await self.backend.get_storage_stats()
            
            # Combine with snapshot metadata
            combined_entries = []
            for entry in storage_entries:
                combined_data = {
                    "storage_entry": entry.dict(),
                    "snapshot_metadata": None,
                    "is_deduplicated": False,
                    "original_snapshot_id": None
                }
                
                # Check if deduplicated
                dedup_marker = entry.path / ".deduplicated"
                if dedup_marker.exists():
                    try:
                        content = await self._read_file_async(dedup_marker)
                        dedup_info = json.loads(content.decode())
                        combined_data["is_deduplicated"] = True
                        combined_data["original_snapshot_id"] = dedup_info.get("original_snapshot_id")
                    except Exception as e:
                        logger.warning(f"Failed to read deduplication info for {entry.snapshot_id}: {e}")
                
                # Load snapshot metadata if available
                try:
                    metadata_file = entry.path / "metadata.json"
                    if metadata_file.exists():
                        content = await self._read_file_async(metadata_file)
                        metadata_dict = json.loads(content.decode())
                        combined_data["snapshot_metadata"] = metadata_dict
                except Exception as e:
                    logger.debug(f"Failed to load snapshot metadata for {entry.snapshot_id}: {e}")
                
                combined_entries.append(combined_data)
            
            # Add storage stats if requested
            if include_storage_stats:
                return {
                    "snapshots": combined_entries,
                    "storage_stats": storage_stats.dict(),
                    "total_count": len(combined_entries)
                }
            
            return combined_entries
            
        except Exception as e:
            logger.error(f"Failed to list snapshots with metadata: {e}")
            raise StorageError(f"Failed to list snapshots: {str(e)}")
    
    async def cleanup_storage(
        self,
        policy_names: Optional[List[str]] = None,
        dry_run: bool = False
    ) -> List[CleanupResult]:
        """
        Execute storage cleanup with specified policies.
        
        Args:
            policy_names: List of policy names to execute (None = all)
            dry_run: Only simulate cleanup
            
        Returns:
            List of CleanupResult objects
        """
        try:
            results = await self.cleanup_engine.execute_cleanup(
                policies=policy_names,
                dry_run=dry_run,
                preserve_ancestry=True
            )
            
            logger.info(f"Storage cleanup completed: {len(results)} policies executed")
            return results
            
        except Exception as e:
            logger.error(f"Storage cleanup failed: {e}")
            raise StorageError(f"Storage cleanup failed: {str(e)}")
    
    async def optimize_storage(
        self,
        enable_deduplication: bool = True,
        enable_compression_optimization: bool = True,
        enable_layout_optimization: bool = False,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Run comprehensive storage optimization.
        
        Args:
            enable_deduplication: Whether to run deduplication
            enable_compression_optimization: Whether to optimize compression
            enable_layout_optimization: Whether to optimize layout
            dry_run: Only simulate optimization
            
        Returns:
            Dictionary with optimization results
        """
        try:
            results = {
                "started_at": datetime.utcnow().isoformat(),
                "deduplication_result": None,
                "compression_optimization": None,
                "layout_optimization": None,
                "total_bytes_saved": 0
            }
            
            # Run deduplication
            if enable_deduplication:
                dedup_result = await self.optimizer.deduplicate_storage(dry_run=dry_run)
                results["deduplication_result"] = dedup_result.dict()
                results["total_bytes_saved"] += dedup_result.bytes_saved
            
            # Run compression optimization
            if enable_compression_optimization:
                compression_stats = await self.optimizer.optimize_compression()
                results["compression_optimization"] = compression_stats
                results["total_bytes_saved"] += compression_stats.get("bytes_saved", 0)
            
            # Run layout optimization
            if enable_layout_optimization:
                layout_stats = await self.optimizer.optimize_storage_layout()
                results["layout_optimization"] = layout_stats
            
            results["completed_at"] = datetime.utcnow().isoformat()
            
            total_mb_saved = results["total_bytes_saved"] / (1024 * 1024)
            logger.info(f"Storage optimization completed: {total_mb_saved:.1f} MB saved")
            
            return results
            
        except Exception as e:
            logger.error(f"Storage optimization failed: {e}")
            raise StorageError(f"Storage optimization failed: {str(e)}")
    
    async def get_storage_health_report(self) -> Dict[str, Any]:
        """
        Get comprehensive storage health report.
        
        Returns:
            Dictionary with health information and recommendations
        """
        try:
            # Get basic storage statistics
            storage_stats = await self.backend.get_storage_stats()
            
            # Validate storage integrity
            validation_result = await self.backend.validate_storage_integrity()
            
            # Analyze efficiency
            efficiency_analysis = await self.optimizer.analyze_storage_efficiency()
            
            # Get cleanup preview
            cleanup_preview = await self.cleanup_engine.get_cleanup_preview()
            
            # Calculate health metrics
            health_score = storage_stats.get_storage_health_score()
            
            # Determine health status
            if health_score >= 90:
                health_status = "excellent"
            elif health_score >= 75:
                health_status = "good"
            elif health_score >= 50:
                health_status = "fair"
            elif health_score >= 25:
                health_status = "poor"
            else:
                health_status = "critical"
            
            # Generate recommendations
            recommendations = []
            
            if not validation_result.valid:
                recommendations.append({
                    "type": "critical",
                    "message": "Storage integrity issues detected",
                    "action": "Run storage repair immediately"
                })
            
            if storage_stats.storage_usage_percentage > 0.9:
                recommendations.append({
                    "type": "urgent",
                    "message": "Storage is nearly full",
                    "action": "Run cleanup policies to free space"
                })
            
            potential_cleanup = sum(r.total_deleted for r in cleanup_preview if r.total_deleted > 0)
            if potential_cleanup > 0:
                recommendations.append({
                    "type": "optimization",
                    "message": f"Cleanup could remove {potential_cleanup} snapshots",
                    "action": "Run cleanup policies"
                })
            
            if efficiency_analysis.get("duplicate_analysis", {}).get("potential_savings_mb", 0) > 100:
                recommendations.append({
                    "type": "optimization", 
                    "message": "Significant deduplication savings available",
                    "action": "Run storage deduplication"
                })
            
            return {
                "health_score": health_score,
                "health_status": health_status,
                "storage_stats": storage_stats.dict(),
                "validation_result": validation_result.dict(),
                "efficiency_analysis": efficiency_analysis,
                "cleanup_preview": [r.dict() for r in cleanup_preview],
                "recommendations": recommendations,
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to generate storage health report: {e}")
            raise StorageError(f"Failed to generate health report: {str(e)}")
    
    async def migrate_storage(
        self,
        target_version: str = "1.0",
        backup_before_migration: bool = True
    ) -> Dict[str, Any]:
        """
        Migrate storage to new version format.
        
        Args:
            target_version: Target storage version
            backup_before_migration: Whether to backup before migration
            
        Returns:
            Dictionary with migration results
        """
        logger.info(f"Starting storage migration to version {target_version}")
        
        try:
            migration_stats = {
                "started_at": datetime.utcnow().isoformat(),
                "source_version": "current",
                "target_version": target_version,
                "snapshots_migrated": 0,
                "backup_created": False,
                "errors": []
            }
            
            # Create backup if requested
            if backup_before_migration:
                backup_path = self.backend.base_path.parent / f"storage_backup_{int(datetime.utcnow().timestamp())}"
                try:
                    import shutil
                    await asyncio.get_event_loop().run_in_executor(
                        None, shutil.copytree, self.backend.base_path, backup_path
                    )
                    migration_stats["backup_created"] = True
                    migration_stats["backup_path"] = str(backup_path)
                    logger.info(f"Created storage backup at {backup_path}")
                except Exception as e:
                    migration_stats["errors"].append(f"Backup creation failed: {str(e)}")
                    logger.error(f"Failed to create backup: {e}")
                    raise StorageError("Migration aborted due to backup failure")
            
            # For version 1.0, migration is mainly rebuilding indexes
            if target_version == "1.0":
                await self.backend._rebuild_indexes()
                
                # Count migrated snapshots
                snapshots = await self.backend.list_snapshots()
                migration_stats["snapshots_migrated"] = len(snapshots)
            
            migration_stats["completed_at"] = datetime.utcnow().isoformat()
            
            logger.info(f"Storage migration completed: {migration_stats['snapshots_migrated']} snapshots migrated")
            return migration_stats
            
        except Exception as e:
            logger.error(f"Storage migration failed: {e}")
            raise StorageError(f"Storage migration failed: {str(e)}")
    
    async def export_storage_metadata(self, output_path: Path) -> Dict[str, Any]:
        """
        Export storage metadata for backup or analysis.
        
        Args:
            output_path: Path to export metadata
            
        Returns:
            Dictionary with export statistics
        """
        try:
            # Get all storage data
            snapshots = await self.backend.list_snapshots()
            storage_stats = await self.backend.get_storage_stats()
            
            # Build export data
            export_data = {
                "export_version": "1.0",
                "exported_at": datetime.utcnow().isoformat(),
                "project_name": self.project_name,
                "storage_config": self.storage_config.dict(),
                "storage_stats": storage_stats.dict(),
                "snapshots": [entry.dict() for entry in snapshots],
                "total_snapshots": len(snapshots)
            }
            
            # Write export file
            content = json.dumps(export_data, indent=2, default=str)
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await self._write_file_async(output_path, content.encode())
            
            export_stats = {
                "snapshots_exported": len(snapshots),
                "export_size_bytes": len(content),
                "export_path": str(output_path)
            }
            
            logger.info(f"Storage metadata exported: {export_stats}")
            return export_stats
            
        except Exception as e:
            logger.error(f"Storage metadata export failed: {e}")
            raise StorageError(f"Storage metadata export failed: {str(e)}")
    
    async def import_storage_metadata(
        self,
        import_path: Path,
        merge_mode: str = "skip_existing"
    ) -> Dict[str, Any]:
        """
        Import storage metadata from backup.
        
        Args:
            import_path: Path to import metadata from
            merge_mode: How to handle existing snapshots ('skip_existing', 'overwrite', 'merge')
            
        Returns:
            Dictionary with import statistics
        """
        try:
            if not import_path.exists():
                raise StorageError(f"Import file not found: {import_path}")
            
            # Read import data
            content = await self._read_file_async(import_path)
            import_data = json.loads(content.decode())
            
            import_stats = {
                "snapshots_imported": 0,
                "snapshots_skipped": 0,
                "snapshots_updated": 0,
                "errors": []
            }
            
            # Import snapshots
            imported_snapshots = import_data.get("snapshots", [])
            
            for snapshot_data in imported_snapshots:
                try:
                    # Create storage entry from imported data
                    storage_entry = StorageEntry(**snapshot_data)
                    
                    # Check if snapshot already exists
                    existing = await self.backend.retrieve_snapshot(
                        storage_entry.snapshot_id, update_access_time=False
                    )
                    
                    if existing:
                        if merge_mode == "skip_existing":
                            import_stats["snapshots_skipped"] += 1
                            continue
                        elif merge_mode == "overwrite":
                            # Update existing entry
                            await self.backend._update_index_entry(storage_entry)
                            import_stats["snapshots_updated"] += 1
                        elif merge_mode == "merge":
                            # Merge with existing entry (keep newer timestamps)
                            if storage_entry.created_at > existing.created_at:
                                await self.backend._update_index_entry(storage_entry)
                                import_stats["snapshots_updated"] += 1
                            else:
                                import_stats["snapshots_skipped"] += 1
                    else:
                        # Add new entry
                        await self.backend._add_to_index(storage_entry)
                        import_stats["snapshots_imported"] += 1
                
                except Exception as e:
                    error_msg = f"Failed to import snapshot {snapshot_data.get('snapshot_id', 'unknown')}: {str(e)}"
                    import_stats["errors"].append(error_msg)
                    logger.error(error_msg)
            
            logger.info(f"Storage metadata import completed: {import_stats}")
            return import_stats
            
        except Exception as e:
            logger.error(f"Storage metadata import failed: {e}")
            raise StorageError(f"Storage metadata import failed: {str(e)}")
    
    async def get_branch_statistics(self, branch: str) -> Dict[str, Any]:
        """
        Get detailed statistics for a specific branch.
        
        Args:
            branch: Branch name
            
        Returns:
            Dictionary with branch statistics
        """
        try:
            # Get branch snapshots
            snapshots = await self.backend.list_snapshots(branch=branch)
            
            if not snapshots:
                return {
                    "branch": branch,
                    "snapshot_count": 0,
                    "total_size_bytes": 0,
                    "average_compression_ratio": 0.0,
                    "oldest_snapshot": None,
                    "newest_snapshot": None,
                    "ancestry_info": None
                }
            
            # Calculate statistics
            total_size = sum(s.size_bytes for s in snapshots)
            total_compressed = sum(s.compressed_size_bytes for s in snapshots)
            avg_compression = sum(s.compression_ratio for s in snapshots) / len(snapshots)
            
            # Find temporal bounds
            sorted_snapshots = sorted(snapshots, key=lambda s: s.created_at)
            oldest = sorted_snapshots[0]
            newest = sorted_snapshots[-1]
            
            # Get ancestry information
            ancestry = await self.backend.get_branch_ancestry(branch)
            fallback_chain = await self.backend.get_fallback_chain(branch)
            
            return {
                "branch": branch,
                "snapshot_count": len(snapshots),
                "total_size_bytes": total_size,
                "total_compressed_bytes": total_compressed,
                "average_compression_ratio": avg_compression,
                "storage_efficiency": (1.0 - (total_compressed / total_size)) * 100 if total_size > 0 else 0.0,
                "oldest_snapshot": {
                    "id": oldest.snapshot_id,
                    "name": oldest.name,
                    "created_at": oldest.created_at.isoformat()
                },
                "newest_snapshot": {
                    "id": newest.snapshot_id,
                    "name": newest.name,
                    "created_at": newest.created_at.isoformat()
                },
                "ancestry_info": ancestry.dict() if ancestry else None,
                "fallback_chain": fallback_chain
            }
            
        except Exception as e:
            logger.error(f"Failed to get branch statistics for {branch}: {e}")
            raise StorageError(f"Failed to get branch statistics: {str(e)}")
    
    # Private helper methods
    
    async def _resolve_deduplicated_snapshot(self, entry: StorageEntry) -> Optional[StorageEntry]:
        """Resolve original snapshot for deduplicated entry."""
        dedup_marker = entry.path / ".deduplicated"
        if not dedup_marker.exists():
            return entry
        
        try:
            content = await self._read_file_async(dedup_marker)
            dedup_info = json.loads(content.decode())
            
            original_id = dedup_info.get("original_snapshot_id")
            if original_id:
                return await self.backend.retrieve_snapshot(original_id, update_access_time=False)
            
        except Exception as e:
            logger.warning(f"Failed to resolve deduplicated snapshot {entry.snapshot_id}: {e}")
        
        return None
    
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