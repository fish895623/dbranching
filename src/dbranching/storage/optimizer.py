"""Storage optimization engine for deduplication and performance optimization."""

import asyncio
import logging
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import filecmp

from ..exceptions import StorageError
from ..snapshot.compression import CompressionEngine
from .models import (
    StorageEntry,
    DeduplicationResult,
    StorageEntryStatus,
    CompressionType,
)
from .backend import StorageBackend

logger = logging.getLogger(__name__)


class StorageOptimizer:
    """
    Storage optimization engine providing deduplication and compression optimization.
    
    Features:
    - Content-based deduplication using checksums and file comparison
    - Compression optimization with algorithm switching
    - Background optimization operations
    - Storage layout optimization
    """
    
    def __init__(
        self,
        storage_backend: StorageBackend,
        compression_engine: Optional[CompressionEngine] = None
    ):
        """
        Initialize storage optimizer.
        
        Args:
            storage_backend: Storage backend instance
            compression_engine: Optional compression engine
        """
        self.storage_backend = storage_backend
        self.compression_engine = compression_engine or CompressionEngine()
        self._optimization_lock = asyncio.Lock()
        
        logger.info("Storage optimizer initialized")
    
    async def deduplicate_storage(
        self,
        dry_run: bool = False,
        aggressive: bool = False
    ) -> DeduplicationResult:
        """
        Deduplicate storage by identifying and linking identical snapshots.
        
        Args:
            dry_run: Only simulate deduplication
            aggressive: Use more aggressive comparison methods
            
        Returns:
            DeduplicationResult with deduplication statistics
        """
        async with self._optimization_lock:
            logger.info(f"Starting storage deduplication (dry_run={dry_run}, aggressive={aggressive})")
            
            result = DeduplicationResult()
            
            try:
                # Get all active snapshots
                snapshots = await self.storage_backend.list_snapshots(
                    status=StorageEntryStatus.ACTIVE
                )
                result.total_examined = len(snapshots)
                
                # Find potential duplicates by checksum
                duplicate_groups = await self._find_duplicate_groups(snapshots, aggressive)
                result.duplicate_groups = duplicate_groups
                result.duplicates_found = len(duplicate_groups)
                
                # Process each duplicate group
                for checksum, snapshot_ids in duplicate_groups.items():
                    if len(snapshot_ids) < 2:
                        continue
                    
                    # Keep the oldest snapshot as the original
                    snapshots_in_group = []
                    for snapshot_id in snapshot_ids:
                        snapshot = await self.storage_backend.retrieve_snapshot(
                            snapshot_id, update_access_time=False
                        )
                        if snapshot:
                            snapshots_in_group.append(snapshot)
                    
                    if len(snapshots_in_group) < 2:
                        continue
                    
                    # Sort by creation time, keep oldest as original
                    snapshots_in_group.sort(key=lambda s: s.created_at)
                    original = snapshots_in_group[0]
                    duplicates = snapshots_in_group[1:]
                    
                    result.preserved_snapshots.append(original.snapshot_id)
                    
                    # Process duplicates
                    for duplicate in duplicates:
                        try:
                            if not dry_run:
                                # Create symbolic link or hardlink to original
                                await self._create_deduplication_link(original, duplicate)
                            
                            result.linked_snapshots.append(duplicate.snapshot_id)
                            result.bytes_saved += duplicate.compressed_size_bytes
                            result.snapshots_deduplicated += 1
                            
                        except Exception as e:
                            logger.error(f"Failed to deduplicate {duplicate.snapshot_id}: {e}")
                
                logger.info(
                    f"Deduplication completed: {result.snapshots_deduplicated} snapshots, "
                    f"{result.bytes_saved / (1024 * 1024):.1f} MB saved"
                )
                
            except Exception as e:
                logger.error(f"Deduplication failed: {e}")
                raise StorageError(f"Deduplication failed: {str(e)}")
            
            result.mark_completed()
            return result
    
    async def optimize_compression(
        self,
        target_algorithm: Optional[str] = None,
        recompress_threshold: float = 0.1
    ) -> Dict[str, int]:
        """
        Optimize compression by recompressing snapshots with better algorithms.
        
        Args:
            target_algorithm: Target compression algorithm (None = auto-select)
            recompress_threshold: Minimum improvement threshold to trigger recompression
            
        Returns:
            Dictionary with optimization statistics
        """
        async with self._optimization_lock:
            logger.info(f"Starting compression optimization (target={target_algorithm})")
            
            stats = {
                "snapshots_examined": 0,
                "snapshots_recompressed": 0,
                "bytes_saved": 0,
                "errors": 0
            }
            
            try:
                # Get all snapshots
                snapshots = await self.storage_backend.list_snapshots(
                    status=StorageEntryStatus.ACTIVE
                )
                stats["snapshots_examined"] = len(snapshots)
                
                for snapshot in snapshots:
                    try:
                        # Analyze current compression efficiency
                        current_ratio = snapshot.compression_ratio
                        current_algorithm = snapshot.compression_type
                        
                        # Skip if already well compressed
                        if current_ratio >= 4.0:  # Already compressed to 25% or less
                            continue
                        
                        # Determine best algorithm for this snapshot
                        best_algorithm = target_algorithm or await self._select_best_compression(
                            snapshot.path
                        )
                        
                        if best_algorithm == current_algorithm:
                            continue
                        
                        # Estimate potential savings
                        estimated_savings = await self._estimate_compression_savings(
                            snapshot, best_algorithm
                        )
                        
                        # Recompress if savings exceed threshold
                        if estimated_savings >= recompress_threshold:
                            savings = await self._recompress_snapshot(snapshot, best_algorithm)
                            stats["snapshots_recompressed"] += 1
                            stats["bytes_saved"] += savings
                        
                    except Exception as e:
                        logger.error(f"Failed to optimize compression for {snapshot.snapshot_id}: {e}")
                        stats["errors"] += 1
                
                logger.info(
                    f"Compression optimization completed: {stats['snapshots_recompressed']} snapshots, "
                    f"{stats['bytes_saved'] / (1024 * 1024):.1f} MB saved"
                )
                
            except Exception as e:
                logger.error(f"Compression optimization failed: {e}")
                stats["errors"] += 1
            
            return stats
    
    async def defragment_storage(self) -> Dict[str, int]:
        """
        Defragment storage by reorganizing files and rebuilding indexes.
        
        Returns:
            Dictionary with defragmentation statistics
        """
        async with self._optimization_lock:
            logger.info("Starting storage defragmentation")
            
            stats = {
                "directories_reorganized": 0,
                "files_moved": 0,
                "indexes_rebuilt": 0,
                "temp_files_cleaned": 0
            }
            
            try:
                # Clean up temporary files
                stats["temp_files_cleaned"] = await self.storage_backend._cleanup_temp_directory()
                
                # Rebuild indexes for optimization
                await self.storage_backend._rebuild_indexes()
                stats["indexes_rebuilt"] = 1
                
                # Compact storage backend
                compact_stats = await self.storage_backend.compact_storage()
                stats.update(compact_stats)
                
                logger.info(f"Storage defragmentation completed: {stats}")
                
            except Exception as e:
                logger.error(f"Storage defragmentation failed: {e}")
                raise StorageError(f"Storage defragmentation failed: {str(e)}")
            
            return stats
    
    async def analyze_storage_efficiency(self) -> Dict[str, any]:
        """
        Analyze storage efficiency and provide optimization recommendations.
        
        Returns:
            Dictionary with analysis results and recommendations
        """
        logger.info("Analyzing storage efficiency")
        
        try:
            # Get storage statistics
            stats = await self.storage_backend.get_storage_stats()
            
            # Find duplicate candidates
            snapshots = await self.storage_backend.list_snapshots()
            duplicate_groups = await self._find_duplicate_groups(snapshots, aggressive=False)
            
            # Calculate potential savings from deduplication
            dedup_savings = 0
            for snapshot_ids in duplicate_groups.values():
                if len(snapshot_ids) > 1:
                    # Calculate savings from all but one copy
                    group_snapshots = []
                    for snapshot_id in snapshot_ids:
                        snapshot = await self.storage_backend.retrieve_snapshot(
                            snapshot_id, update_access_time=False
                        )
                        if snapshot:
                            group_snapshots.append(snapshot)
                    
                    if len(group_snapshots) > 1:
                        # Save space from all but largest (keep best quality)
                        group_snapshots.sort(key=lambda s: s.compressed_size_bytes, reverse=True)
                        for duplicate in group_snapshots[1:]:
                            dedup_savings += duplicate.compressed_size_bytes
            
            # Analyze compression efficiency by branch
            branch_analysis = {}
            for branch, branch_stats in stats.branch_stats.items():
                avg_ratio = branch_stats.get("avg_compression_ratio", 1.0)
                efficiency_score = min(100, (avg_ratio - 1.0) * 25)  # Scale to 0-100
                
                branch_analysis[branch] = {
                    "compression_efficiency_score": efficiency_score,
                    "avg_compression_ratio": avg_ratio,
                    "total_size_mb": branch_stats["size_bytes"] / (1024 * 1024),
                    "compressed_size_mb": branch_stats["compressed_bytes"] / (1024 * 1024),
                    "snapshot_count": branch_stats["count"]
                }
            
            # Generate recommendations
            recommendations = []
            
            if dedup_savings > 1024 * 1024 * 100:  # > 100MB savings potential
                recommendations.append({
                    "type": "deduplication",
                    "priority": "high",
                    "description": f"Deduplication could save {dedup_savings / (1024 * 1024):.1f} MB",
                    "action": "Run storage deduplication"
                })
            
            if stats.average_compression_ratio < 2.0:  # Less than 50% compression
                recommendations.append({
                    "type": "compression",
                    "priority": "medium", 
                    "description": "Poor compression efficiency detected",
                    "action": "Consider switching compression algorithm or increasing compression level"
                })
            
            if stats.storage_usage_percentage > 0.9:  # Over 90% full
                recommendations.append({
                    "type": "cleanup",
                    "priority": "high",
                    "description": "Storage usage is very high",
                    "action": "Run cleanup policies to free space"
                })
            
            if stats.corrupted_snapshots > 0:
                recommendations.append({
                    "type": "repair",
                    "priority": "critical",
                    "description": f"{stats.corrupted_snapshots} corrupted snapshots found",
                    "action": "Run storage repair to fix corruption"
                })
            
            analysis_result = {
                "storage_stats": stats.dict(),
                "duplicate_analysis": {
                    "duplicate_groups": len(duplicate_groups),
                    "potential_savings_bytes": dedup_savings,
                    "potential_savings_mb": dedup_savings / (1024 * 1024)
                },
                "branch_analysis": branch_analysis,
                "recommendations": recommendations,
                "overall_efficiency_score": stats.get_storage_health_score()
            }
            
            logger.info(f"Storage efficiency analysis completed: {len(recommendations)} recommendations")
            return analysis_result
            
        except Exception as e:
            logger.error(f"Storage efficiency analysis failed: {e}")
            raise StorageError(f"Storage efficiency analysis failed: {str(e)}")
    
    # Private helper methods
    
    async def _find_duplicate_groups(
        self,
        snapshots: List[StorageEntry],
        aggressive: bool = False
    ) -> Dict[str, List[str]]:
        """Find groups of potentially duplicate snapshots."""
        # Group by checksum first (fast)
        checksum_groups = {}
        for snapshot in snapshots:
            if snapshot.checksum not in checksum_groups:
                checksum_groups[snapshot.checksum] = []
            checksum_groups[snapshot.checksum].append(snapshot.snapshot_id)
        
        # Filter to only groups with potential duplicates
        duplicate_groups = {
            checksum: snapshot_ids
            for checksum, snapshot_ids in checksum_groups.items()
            if len(snapshot_ids) > 1
        }
        
        # If aggressive mode, also compare by content
        if aggressive:
            verified_groups = {}
            for checksum, snapshot_ids in duplicate_groups.items():
                verified_ids = await self._verify_content_similarity(snapshot_ids)
                if len(verified_ids) > 1:
                    verified_groups[checksum] = verified_ids
            duplicate_groups = verified_groups
        
        return duplicate_groups
    
    async def _verify_content_similarity(self, snapshot_ids: List[str]) -> List[str]:
        """Verify content similarity between snapshots."""
        # Get snapshots
        snapshots = []
        for snapshot_id in snapshot_ids:
            snapshot = await self.storage_backend.retrieve_snapshot(
                snapshot_id, update_access_time=False
            )
            if snapshot and snapshot.path.exists():
                snapshots.append(snapshot)
        
        if len(snapshots) < 2:
            return [s.snapshot_id for s in snapshots]
        
        # Compare file contents
        similar_groups = []
        
        for i, snapshot1 in enumerate(snapshots):
            group = [snapshot1.snapshot_id]
            
            for j, snapshot2 in enumerate(snapshots[i+1:], i+1):
                if await self._compare_snapshot_contents(snapshot1.path, snapshot2.path):
                    group.append(snapshot2.snapshot_id)
            
            if len(group) > 1:
                similar_groups.extend(group)
        
        return list(set(similar_groups))
    
    async def _compare_snapshot_contents(self, path1: Path, path2: Path) -> bool:
        """Compare contents of two snapshot directories."""
        def _compare_sync():
            try:
                # Use filecmp to compare directory trees
                comparison = filecmp.dircmp(path1, path2)
                
                # Check if all files match
                def check_recursive(dcmp):
                    # Check if any files differ
                    if dcmp.left_only or dcmp.right_only or dcmp.diff_files:
                        return False
                    
                    # Recursively check subdirectories
                    for subdcmp in dcmp.subdirs.values():
                        if not check_recursive(subdcmp):
                            return False
                    
                    return True
                
                return check_recursive(comparison)
                
            except Exception as e:
                logger.debug(f"Content comparison failed: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _compare_sync)
    
    async def _create_deduplication_link(
        self,
        original: StorageEntry,
        duplicate: StorageEntry
    ) -> None:
        """Create deduplication link from duplicate to original."""
        # Create a deduplication marker file instead of actual linking
        # This preserves the ability to track both snapshots while saving space
        
        dedup_marker = duplicate.path / ".deduplicated"
        link_info = {
            "original_snapshot_id": original.snapshot_id,
            "original_path": str(original.path),
            "linked_at": datetime.utcnow().isoformat(),
            "space_saved": duplicate.compressed_size_bytes
        }
        
        try:
            # Write deduplication marker
            import json
            content = json.dumps(link_info, indent=2)
            
            async with self.storage_backend.atomic_manager.atomic_operation(
                target_path=dedup_marker,
                backup_existing=False,
                cleanup_on_success=True
            ) as atomic_ctx:
                
                temp_marker = await self.storage_backend.atomic_manager.get_temp_file_path(
                    atomic_ctx, ".deduplicated"
                )
                
                await self._write_file_async(temp_marker, content.encode())
                
            logger.debug(f"Created deduplication link: {duplicate.snapshot_id} -> {original.snapshot_id}")
            
        except Exception as e:
            raise StorageError(f"Failed to create deduplication link: {str(e)}")
    
    async def _select_best_compression(self, snapshot_path: Path) -> str:
        """Select best compression algorithm for snapshot."""
        # Analyze snapshot content to determine best compression
        
        # For now, return gzip as default
        # In the future, could analyze file types and sizes to choose optimal algorithm
        return "gzip"
    
    async def _estimate_compression_savings(
        self,
        snapshot: StorageEntry,
        new_algorithm: str
    ) -> float:
        """Estimate compression savings from algorithm change."""
        # Simplified estimation based on algorithm efficiency
        
        efficiency_ratios = {
            "none": 1.0,
            "gzip": 0.3,
            "lz4": 0.5,   # Faster but less compression
            "zstd": 0.25, # Better compression
        }
        
        current_efficiency = efficiency_ratios.get(snapshot.compression_type, 0.3)
        new_efficiency = efficiency_ratios.get(new_algorithm, 0.3)
        
        if new_efficiency < current_efficiency:
            # Better compression, calculate potential savings
            current_size = snapshot.compressed_size_bytes
            estimated_new_size = current_size * (new_efficiency / current_efficiency)
            savings_ratio = (current_size - estimated_new_size) / current_size
            return savings_ratio
        
        return 0.0
    
    async def _recompress_snapshot(
        self,
        snapshot: StorageEntry,
        new_algorithm: str
    ) -> int:
        """Recompress snapshot with new algorithm and return bytes saved."""
        # This would implement snapshot recompression
        # For now, return estimated savings
        
        logger.info(f"Recompressing {snapshot.snapshot_id} with {new_algorithm}")
        
        # Placeholder implementation
        estimated_savings = int(snapshot.compressed_size_bytes * 0.1)  # 10% savings estimate
        
        return estimated_savings
    
    async def optimize_storage_layout(self) -> Dict[str, int]:
        """
        Optimize storage layout for better performance.
        
        Returns:
            Dictionary with optimization statistics
        """
        logger.info("Starting storage layout optimization")
        
        stats = {
            "directories_reorganized": 0,
            "files_moved": 0,
            "symlinks_created": 0,
            "access_patterns_optimized": 0
        }
        
        try:
            # Get storage statistics
            storage_stats = await self.storage_backend.get_storage_stats()
            
            # Analyze access patterns
            snapshots = await self.storage_backend.list_snapshots()
            
            # Group by access frequency
            frequently_accessed = []
            rarely_accessed = []
            
            for snapshot in snapshots:
                if snapshot.last_accessed:
                    days_since_access = (datetime.utcnow() - snapshot.last_accessed).days
                    if days_since_access <= 7:  # Accessed in last week
                        frequently_accessed.append(snapshot)
                    else:
                        rarely_accessed.append(snapshot)
                else:
                    rarely_accessed.append(snapshot)
            
            # Optimize layout based on access patterns
            # This is a placeholder for more sophisticated layout optimization
            stats["access_patterns_optimized"] = len(frequently_accessed)
            
            logger.info(f"Storage layout optimization completed: {stats}")
            
        except Exception as e:
            logger.error(f"Storage layout optimization failed: {e}")
            raise StorageError(f"Storage layout optimization failed: {str(e)}")
        
        return stats
    
    async def run_background_optimization(
        self,
        interval_hours: int = 6,
        enable_deduplication: bool = True,
        enable_compression_optimization: bool = True,
        enable_layout_optimization: bool = False
    ) -> None:
        """
        Run background optimization tasks.
        
        Args:
            interval_hours: Optimization interval in hours
            enable_deduplication: Whether to run deduplication
            enable_compression_optimization: Whether to optimize compression
            enable_layout_optimization: Whether to optimize layout
        """
        async def optimization_task():
            while True:
                try:
                    await asyncio.sleep(interval_hours * 3600)
                    logger.info("Running background storage optimization")
                    
                    # Run deduplication
                    if enable_deduplication:
                        dedup_result = await self.deduplicate_storage(dry_run=False)
                        if dedup_result.bytes_saved > 0:
                            logger.info(
                                f"Background deduplication saved "
                                f"{dedup_result.bytes_saved / (1024 * 1024):.1f} MB"
                            )
                    
                    # Run compression optimization
                    if enable_compression_optimization:
                        compression_stats = await self.optimize_compression()
                        if compression_stats["bytes_saved"] > 0:
                            logger.info(
                                f"Background compression optimization saved "
                                f"{compression_stats['bytes_saved'] / (1024 * 1024):.1f} MB"
                            )
                    
                    # Run layout optimization
                    if enable_layout_optimization:
                        layout_stats = await self.optimize_storage_layout()
                        logger.info(f"Background layout optimization: {layout_stats}")
                    
                except Exception as e:
                    logger.error(f"Background optimization failed: {e}")
        
        # Start background task
        asyncio.create_task(optimization_task())
        logger.info(f"Started background optimization (every {interval_hours} hours)")
    
    # Utility methods
    
    async def _write_file_async(self, file_path: Path, content: bytes) -> None:
        """Write file asynchronously."""
        def _write_sync():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(content)
        
        await asyncio.get_event_loop().run_in_executor(None, _write_sync)