"""Cleanup policy engine with branch-aware retention and automatic cleanup."""

import asyncio
import logging
import fnmatch
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..config import StorageConfig
from ..exceptions import StorageError, ValidationError
from .models import (
    StorageEntry,
    StorageIndex,
    CleanupPolicy,
    CleanupResult,
    CleanupReason,
    StorageEntryStatus,
    BranchAncestry,
)
from .backend import StorageBackend

logger = logging.getLogger(__name__)


class CleanupPolicyEngine:
    """
    Cleanup policy engine that manages snapshot retention with branch ancestry awareness.
    
    Features:
    - Age, count, and size-based cleanup policies
    - Branch ancestry preservation for restore capability
    - Manual and automatic cleanup with dry-run support
    - Configurable retention rules per branch pattern
    """
    
    def __init__(self, storage_backend: StorageBackend, storage_config: StorageConfig):
        """
        Initialize cleanup policy engine.
        
        Args:
            storage_backend: Storage backend instance
            storage_config: Storage configuration
        """
        self.storage_backend = storage_backend
        self.storage_config = storage_config
        self._default_policies = self._create_default_policies()
        self._custom_policies: List[CleanupPolicy] = []
        
        logger.info("Cleanup policy engine initialized")
    
    def _create_default_policies(self) -> List[CleanupPolicy]:
        """Create default cleanup policies from storage configuration."""
        policies = []
        
        # Default retention policy
        default_policy = CleanupPolicy(
            name="default_retention",
            description="Default retention policy for all branches",
            branch_patterns=["*"],
            max_age_days=self._parse_age_string(self.storage_config.retention.max_age),
            max_count=self.storage_config.retention.max_count,
            preserve_ancestry=True,
            preserve_tagged=True,
            preserve_recent_days=1,
            priority=10
        )
        policies.append(default_policy)
        
        # Branch-specific policies
        for pattern_config in self.storage_config.patterns:
            policy = CleanupPolicy(
                name=f"pattern_{hash(str(pattern_config.branches))}",
                description=f"Custom policy for branches: {', '.join(pattern_config.branches)}",
                branch_patterns=pattern_config.branches,
                max_age_days=self._parse_age_string(pattern_config.max_age),
                max_count=pattern_config.max_count,
                preserve_ancestry=True,
                preserve_tagged=True,
                preserve_recent_days=1,
                priority=50
            )
            policies.append(policy)
        
        # Storage limit policy
        if self.storage_config.max_size:
            limit_bytes = self._parse_size_string(self.storage_config.max_size)
            size_policy = CleanupPolicy(
                name="storage_limit",
                description="Cleanup when storage limit is exceeded",
                branch_patterns=["*"],
                max_size_bytes=limit_bytes,
                preserve_ancestry=False,  # More aggressive when storage is full
                preserve_tagged=True,
                preserve_recent_days=1,
                priority=90
            )
            policies.append(size_policy)
        
        return policies
    
    def add_custom_policy(self, policy: CleanupPolicy) -> None:
        """Add custom cleanup policy."""
        self._custom_policies.append(policy)
        logger.info(f"Added custom cleanup policy: {policy.name}")
    
    def remove_custom_policy(self, policy_name: str) -> bool:
        """Remove custom cleanup policy by name."""
        for i, policy in enumerate(self._custom_policies):
            if policy.name == policy_name:
                del self._custom_policies[i]
                logger.info(f"Removed custom cleanup policy: {policy_name}")
                return True
        return False
    
    def get_all_policies(self) -> List[CleanupPolicy]:
        """Get all policies (default + custom) sorted by priority."""
        all_policies = self._default_policies + self._custom_policies
        return sorted(all_policies, key=lambda p: p.priority, reverse=True)
    
    async def execute_cleanup(
        self,
        policies: Optional[List[str]] = None,
        dry_run: bool = False,
        preserve_ancestry: bool = True
    ) -> List[CleanupResult]:
        """
        Execute cleanup policies.
        
        Args:
            policies: List of policy names to execute (None = all enabled)
            dry_run: Only simulate cleanup without actual deletion
            preserve_ancestry: Whether to preserve ancestry chains
            
        Returns:
            List of CleanupResult objects
        """
        logger.info(f"Starting cleanup execution (dry_run={dry_run})")
        
        all_policies = self.get_all_policies()
        
        # Filter policies to execute
        if policies:
            all_policies = [p for p in all_policies if p.name in policies]
        else:
            all_policies = [p for p in all_policies if p.enabled]
        
        results = []
        
        for policy in all_policies:
            try:
                result = await self._execute_single_policy(
                    policy, dry_run, preserve_ancestry
                )
                results.append(result)
                logger.info(f"Policy '{policy.name}' completed: {result.get_cleanup_summary()}")
            except Exception as e:
                logger.error(f"Policy '{policy.name}' failed: {e}")
                # Create failed result
                failed_result = CleanupResult(
                    policy_name=policy.name,
                    total_examined=0,
                    total_deleted=0,
                    total_preserved=0,
                    bytes_freed=0,
                    errors=[str(e)]
                )
                failed_result.mark_completed()
                results.append(failed_result)
        
        total_deleted = sum(r.total_deleted for r in results)
        total_freed_mb = sum(r.bytes_freed for r in results) / (1024 * 1024)
        
        logger.info(
            f"Cleanup execution completed: {total_deleted} snapshots deleted, "
            f"{total_freed_mb:.1f} MB freed"
        )
        
        return results
    
    async def _execute_single_policy(
        self,
        policy: CleanupPolicy,
        dry_run: bool,
        preserve_ancestry: bool
    ) -> CleanupResult:
        """Execute a single cleanup policy."""
        result = CleanupResult(policy_name=policy.name)
        
        try:
            # Get all snapshots
            snapshots = await self.storage_backend.list_snapshots()
            result.total_examined = len(snapshots)
            
            # Filter snapshots that match this policy
            matching_snapshots = []
            for snapshot in snapshots:
                if self._snapshot_matches_policy(snapshot, policy):
                    matching_snapshots.append(snapshot)
            
            logger.debug(f"Policy '{policy.name}' matches {len(matching_snapshots)} snapshots")
            
            # Determine snapshots to delete based on policy criteria
            snapshots_to_delete = await self._determine_deletions(
                matching_snapshots, policy, preserve_ancestry
            )
            
            # Execute deletions
            for snapshot in snapshots_to_delete:
                try:
                    if not dry_run:
                        await self.storage_backend.delete_snapshot(snapshot.snapshot_id, force=False)
                    
                    result.deleted_snapshots.append(snapshot.snapshot_id)
                    result.bytes_freed += snapshot.compressed_size_bytes
                    
                except Exception as e:
                    error_msg = f"Failed to delete {snapshot.snapshot_id}: {str(e)}"
                    result.errors.append(error_msg)
                    logger.error(error_msg)
            
            # Track preserved snapshots
            preserved_ids = set(s.snapshot_id for s in matching_snapshots) - set(result.deleted_snapshots)
            result.preserved_snapshots = list(preserved_ids)
            
            result.total_deleted = len(result.deleted_snapshots)
            result.total_preserved = len(result.preserved_snapshots)
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Policy execution failed: {e}")
        
        result.mark_completed()
        return result
    
    def _snapshot_matches_policy(self, snapshot: StorageEntry, policy: CleanupPolicy) -> bool:
        """Check if snapshot matches policy criteria."""
        # Check branch patterns
        if not policy.matches_branch(snapshot.branch):
            return False
        
        # Check tag patterns
        if not policy.matches_tags(snapshot.tags):
            return False
        
        return True
    
    async def _determine_deletions(
        self,
        snapshots: List[StorageEntry],
        policy: CleanupPolicy,
        preserve_ancestry: bool
    ) -> List[StorageEntry]:
        """Determine which snapshots should be deleted based on policy."""
        to_delete = []
        
        # Group snapshots by branch for branch-specific processing
        branch_groups = {}
        for snapshot in snapshots:
            if snapshot.branch not in branch_groups:
                branch_groups[snapshot.branch] = []
            branch_groups[snapshot.branch].append(snapshot)
        
        # Process each branch separately
        for branch, branch_snapshots in branch_groups.items():
            branch_deletions = await self._determine_branch_deletions(
                branch_snapshots, policy, preserve_ancestry
            )
            to_delete.extend(branch_deletions)
        
        return to_delete
    
    async def _determine_branch_deletions(
        self,
        snapshots: List[StorageEntry],
        policy: CleanupPolicy,
        preserve_ancestry: bool
    ) -> List[StorageEntry]:
        """Determine deletions for a specific branch."""
        to_delete = []
        
        # Sort snapshots by creation time (oldest first)
        sorted_snapshots = sorted(snapshots, key=lambda s: s.created_at)
        
        # Always preserve recent snapshots
        recent_cutoff = datetime.utcnow() - timedelta(days=policy.preserve_recent_days)
        recent_snapshots = [s for s in sorted_snapshots if s.created_at > recent_cutoff]
        older_snapshots = [s for s in sorted_snapshots if s.created_at <= recent_cutoff]
        
        # Always preserve tagged snapshots if policy requires
        if policy.preserve_tagged:
            tagged_snapshots = [s for s in older_snapshots if s.tags]
            untagged_snapshots = [s for s in older_snapshots if not s.tags]
        else:
            tagged_snapshots = []
            untagged_snapshots = older_snapshots
        
        # Apply age-based cleanup
        if policy.max_age_days:
            age_cutoff = datetime.utcnow() - timedelta(days=policy.max_age_days)
            expired_snapshots = [s for s in untagged_snapshots if s.created_at < age_cutoff]
            to_delete.extend(expired_snapshots)
            untagged_snapshots = [s for s in untagged_snapshots if s.created_at >= age_cutoff]
        
        # Apply count-based cleanup
        if policy.max_count:
            # Count all preserved snapshots
            preserved_count = len(recent_snapshots) + len(tagged_snapshots)
            remaining_allowance = max(0, policy.max_count - preserved_count)
            
            # Keep most recent untagged snapshots within allowance
            if len(untagged_snapshots) > remaining_allowance:
                # Sort by creation time (newest first) and keep only allowed count
                untagged_snapshots.sort(key=lambda s: s.created_at, reverse=True)
                excess_snapshots = untagged_snapshots[remaining_allowance:]
                to_delete.extend(excess_snapshots)
        
        # Apply ancestry preservation
        if preserve_ancestry and policy.preserve_ancestry:
            to_delete = await self._filter_ancestry_preservation(
                to_delete, snapshots[0].branch if snapshots else ""
            )
        
        return to_delete
    
    async def _filter_ancestry_preservation(
        self,
        candidates: List[StorageEntry],
        branch: str
    ) -> List[StorageEntry]:
        """Filter deletion candidates to preserve ancestry chains."""
        # Get fallback chain for this branch
        fallback_chain = await self.storage_backend.get_fallback_chain(branch)
        
        # Get critical snapshots that should be preserved for ancestry
        critical_snapshots = set()
        
        for fallback_branch in fallback_chain:
            # Get latest snapshot for each branch in fallback chain
            branch_snapshots = await self.storage_backend.list_snapshots(branch=fallback_branch)
            if branch_snapshots:
                # Preserve latest snapshot
                latest = max(branch_snapshots, key=lambda s: s.created_at)
                critical_snapshots.add(latest.snapshot_id)
                
                # Preserve oldest snapshot for historical continuity
                oldest = min(branch_snapshots, key=lambda s: s.created_at)
                critical_snapshots.add(oldest.snapshot_id)
        
        # Filter out critical snapshots from deletion candidates
        filtered_candidates = [
            candidate for candidate in candidates
            if candidate.snapshot_id not in critical_snapshots
        ]
        
        preserved_count = len(candidates) - len(filtered_candidates)
        if preserved_count > 0:
            logger.debug(f"Preserved {preserved_count} snapshots for ancestry chain integrity")
        
        return filtered_candidates
    
    async def execute_automatic_cleanup(self) -> List[CleanupResult]:
        """
        Execute automatic cleanup based on configured policies.
        
        Returns:
            List of CleanupResult objects
        """
        logger.info("Starting automatic cleanup")
        
        # Check if automatic cleanup is needed
        stats = await self.storage_backend.get_storage_stats()
        
        needs_cleanup = False
        cleanup_reasons = []
        
        # Check storage usage
        if stats.storage_usage_percentage >= self.storage_config.monitoring_threshold:
            needs_cleanup = True
            cleanup_reasons.append(f"Storage usage {stats.storage_usage_percentage:.1%} >= threshold")
        
        # Check for corrupted snapshots
        if stats.corrupted_snapshots > 0:
            needs_cleanup = True
            cleanup_reasons.append(f"{stats.corrupted_snapshots} corrupted snapshots found")
        
        # Check for orphaned snapshots
        if stats.orphaned_snapshots > 0:
            needs_cleanup = True
            cleanup_reasons.append(f"{stats.orphaned_snapshots} orphaned snapshots found")
        
        if not needs_cleanup:
            logger.info("No automatic cleanup needed")
            return []
        
        logger.info(f"Automatic cleanup triggered: {', '.join(cleanup_reasons)}")
        
        # Execute cleanup policies
        return await self.execute_cleanup(dry_run=False, preserve_ancestry=True)
    
    async def cleanup_corrupted_snapshots(self, dry_run: bool = False) -> CleanupResult:
        """
        Clean up corrupted and orphaned snapshots.
        
        Args:
            dry_run: Only simulate cleanup
            
        Returns:
            CleanupResult with cleanup statistics
        """
        result = CleanupResult(policy_name="cleanup_corrupted")
        
        try:
            # Find corrupted snapshots
            snapshots = await self.storage_backend.list_snapshots()
            corrupted_snapshots = [
                s for s in snapshots 
                if s.status in [StorageEntryStatus.CORRUPTED, StorageEntryStatus.ORPHANED]
            ]
            
            result.total_examined = len(snapshots)
            
            # Delete corrupted snapshots
            for snapshot in corrupted_snapshots:
                try:
                    if not dry_run:
                        await self.storage_backend.delete_snapshot(
                            snapshot.snapshot_id, force=True
                        )
                    
                    result.deleted_snapshots.append(snapshot.snapshot_id)
                    result.bytes_freed += snapshot.compressed_size_bytes
                    
                except Exception as e:
                    error_msg = f"Failed to delete corrupted snapshot {snapshot.snapshot_id}: {str(e)}"
                    result.errors.append(error_msg)
                    logger.error(error_msg)
            
            result.total_deleted = len(result.deleted_snapshots)
            result.total_preserved = result.total_examined - result.total_deleted
            
            logger.info(f"Corrupted snapshots cleanup: {result.total_deleted} deleted")
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Corrupted snapshots cleanup failed: {e}")
        
        result.mark_completed()
        return result
    
    async def cleanup_by_age(
        self,
        max_age_days: int,
        branch_pattern: str = "*",
        preserve_ancestry: bool = True,
        dry_run: bool = False
    ) -> CleanupResult:
        """
        Clean up snapshots older than specified age.
        
        Args:
            max_age_days: Maximum age in days
            branch_pattern: Branch pattern to match
            preserve_ancestry: Whether to preserve ancestry chains
            dry_run: Only simulate cleanup
            
        Returns:
            CleanupResult with cleanup statistics
        """
        policy = CleanupPolicy(
            name=f"age_cleanup_{max_age_days}d",
            description=f"Clean up snapshots older than {max_age_days} days",
            branch_patterns=[branch_pattern],
            max_age_days=max_age_days,
            preserve_ancestry=preserve_ancestry,
            preserve_tagged=True,
            preserve_recent_days=1
        )
        
        return await self._execute_single_policy(policy, dry_run, preserve_ancestry)
    
    async def cleanup_by_count(
        self,
        max_count: int,
        branch_pattern: str = "*",
        preserve_ancestry: bool = True,
        dry_run: bool = False
    ) -> CleanupResult:
        """
        Clean up excess snapshots keeping only the most recent.
        
        Args:
            max_count: Maximum number of snapshots to keep
            branch_pattern: Branch pattern to match
            preserve_ancestry: Whether to preserve ancestry chains
            dry_run: Only simulate cleanup
            
        Returns:
            CleanupResult with cleanup statistics
        """
        policy = CleanupPolicy(
            name=f"count_cleanup_{max_count}",
            description=f"Keep only {max_count} most recent snapshots",
            branch_patterns=[branch_pattern],
            max_count=max_count,
            preserve_ancestry=preserve_ancestry,
            preserve_tagged=True,
            preserve_recent_days=1
        )
        
        return await self._execute_single_policy(policy, dry_run, preserve_ancestry)
    
    async def cleanup_by_size(
        self,
        max_size_bytes: int,
        branch_pattern: str = "*",
        preserve_ancestry: bool = True,
        dry_run: bool = False
    ) -> CleanupResult:
        """
        Clean up snapshots to stay under size limit.
        
        Args:
            max_size_bytes: Maximum total size in bytes
            branch_pattern: Branch pattern to match
            preserve_ancestry: Whether to preserve ancestry chains
            dry_run: Only simulate cleanup
            
        Returns:
            CleanupResult with cleanup statistics
        """
        policy = CleanupPolicy(
            name=f"size_cleanup_{max_size_bytes}b",
            description=f"Keep storage under {max_size_bytes} bytes",
            branch_patterns=[branch_pattern],
            max_size_bytes=max_size_bytes,
            preserve_ancestry=preserve_ancestry,
            preserve_tagged=True,
            preserve_recent_days=1
        )
        
        return await self._execute_single_policy(policy, dry_run, preserve_ancestry)
    
    async def get_cleanup_preview(
        self,
        policies: Optional[List[str]] = None
    ) -> List[CleanupResult]:
        """
        Preview cleanup operations without executing them.
        
        Args:
            policies: List of policy names to preview (None = all enabled)
            
        Returns:
            List of CleanupResult objects from dry run
        """
        return await self.execute_cleanup(policies=policies, dry_run=True)
    
    async def schedule_background_cleanup(self, interval_hours: int = 24) -> None:
        """
        Schedule background cleanup task.
        
        Args:
            interval_hours: Cleanup interval in hours
        """
        async def cleanup_task():
            while True:
                try:
                    await asyncio.sleep(interval_hours * 3600)
                    logger.info("Running scheduled background cleanup")
                    results = await self.execute_automatic_cleanup()
                    
                    # Log summary
                    total_deleted = sum(r.total_deleted for r in results)
                    if total_deleted > 0:
                        logger.info(f"Background cleanup completed: {total_deleted} snapshots removed")
                    
                except Exception as e:
                    logger.error(f"Background cleanup failed: {e}")
        
        # Start background task
        asyncio.create_task(cleanup_task())
        logger.info(f"Scheduled background cleanup every {interval_hours} hours")
    
    # Private helper methods
    
    def _parse_age_string(self, age_str: str) -> int:
        """Parse age string (e.g., '30d') to days."""
        import re
        
        match = re.match(r'^(\d+)([dwmy])$', age_str.lower())
        if not match:
            raise ValueError(f"Invalid age format: {age_str}")
        
        number, unit = match.groups()
        number = int(number)
        
        multipliers = {
            'd': 1,      # days
            'w': 7,      # weeks
            'm': 30,     # months (approximate)
            'y': 365,    # years (approximate)
        }
        
        return number * multipliers[unit]
    
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
    
    async def _execute_single_policy(
        self,
        policy: CleanupPolicy,
        dry_run: bool,
        preserve_ancestry: bool
    ) -> CleanupResult:
        """Execute a single cleanup policy (reused from above)."""
        result = CleanupResult(policy_name=policy.name)
        
        try:
            # Get all snapshots
            snapshots = await self.storage_backend.list_snapshots()
            result.total_examined = len(snapshots)
            
            # Filter snapshots that match this policy
            matching_snapshots = []
            for snapshot in snapshots:
                if self._snapshot_matches_policy(snapshot, policy):
                    matching_snapshots.append(snapshot)
            
            # Determine snapshots to delete
            snapshots_to_delete = await self._determine_deletions(
                matching_snapshots, policy, preserve_ancestry
            )
            
            # Execute deletions
            for snapshot in snapshots_to_delete:
                try:
                    if not dry_run:
                        await self.storage_backend.delete_snapshot(snapshot.snapshot_id, force=False)
                    
                    result.deleted_snapshots.append(snapshot.snapshot_id)
                    result.bytes_freed += snapshot.compressed_size_bytes
                    
                except Exception as e:
                    error_msg = f"Failed to delete {snapshot.snapshot_id}: {str(e)}"
                    result.errors.append(error_msg)
                    logger.error(error_msg)
            
            # Track preserved snapshots
            preserved_ids = set(s.snapshot_id for s in matching_snapshots) - set(result.deleted_snapshots)
            result.preserved_snapshots = list(preserved_ids)
            
            result.total_deleted = len(result.deleted_snapshots)
            result.total_preserved = len(result.preserved_snapshots)
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Policy execution failed: {e}")
        
        result.mark_completed()
        return result