"""Data models for storage management system."""

import hashlib
import sqlite3
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from pydantic import BaseModel, Field, ConfigDict


class CleanupReason(str, Enum):
    """Reasons for snapshot cleanup."""
    AGE_EXCEEDED = "age_exceeded"
    COUNT_EXCEEDED = "count_exceeded"
    SIZE_EXCEEDED = "size_exceeded"
    MANUAL = "manual"
    CORRUPTED = "corrupted"
    ORPHANED = "orphaned"


class StorageEntryStatus(str, Enum):
    """Status of storage entries."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    CORRUPTED = "corrupted"
    ORPHANED = "orphaned"
    PENDING_CLEANUP = "pending_cleanup"


class StorageEntry(BaseModel):
    """Represents a stored snapshot with metadata and ancestry information."""
    
    snapshot_id: str = Field(description="Unique snapshot identifier")
    name: str = Field(description="Snapshot name")
    branch: str = Field(description="Git branch name")
    parent_branch: Optional[str] = Field(default=None, description="Parent branch for ancestry")
    
    # Storage information
    path: Path = Field(description="Full path to snapshot directory")
    size_bytes: int = Field(description="Total snapshot size in bytes")
    compressed_size_bytes: int = Field(description="Compressed size in bytes")
    checksum: str = Field(description="SHA256 checksum of snapshot contents")
    
    # Temporal information
    created_at: datetime = Field(description="Creation timestamp")
    last_accessed: Optional[datetime] = Field(default=None, description="Last access timestamp")
    expires_at: Optional[datetime] = Field(default=None, description="Expiration timestamp")
    
    # Status and metadata
    status: StorageEntryStatus = Field(default=StorageEntryStatus.ACTIVE)
    tags: List[str] = Field(default_factory=list, description="Snapshot tags")
    description: Optional[str] = Field(default=None, description="Snapshot description")
    
    # Technical metadata
    database_type: str = Field(description="Database type (postgresql, mysql, sqlite)")
    database_version: str = Field(description="Database version")
    compression_type: str = Field(description="Compression algorithm used")
    compression_ratio: float = Field(description="Compression efficiency ratio")
    
    # Git integration
    git_commit: Optional[str] = Field(default=None, description="Git commit hash")
    git_author: Optional[str] = Field(default=None, description="Git commit author")
    
    # Ancestry and dependencies
    parent_snapshots: List[str] = Field(default_factory=list, description="Parent snapshot IDs")
    child_snapshots: List[str] = Field(default_factory=list, description="Child snapshot IDs")
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    def calculate_age_days(self) -> float:
        """Calculate age in days from creation time."""
        return (datetime.utcnow() - self.created_at).total_seconds() / 86400
    
    def is_expired(self) -> bool:
        """Check if snapshot has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def get_storage_efficiency(self) -> float:
        """Get storage efficiency as percentage."""
        if self.size_bytes == 0:
            return 0.0
        return (1.0 - (self.compressed_size_bytes / self.size_bytes)) * 100


class BranchAncestry(BaseModel):
    """Branch ancestry tracking for fallback snapshot chains."""
    
    branch_name: str = Field(description="Branch name")
    parent_branch: Optional[str] = Field(default=None, description="Parent branch")
    created_from: Optional[str] = Field(default=None, description="Source snapshot ID")
    
    # Snapshot chain information
    latest_snapshot: Optional[str] = Field(default=None, description="Latest snapshot ID")
    oldest_snapshot: Optional[str] = Field(default=None, description="Oldest snapshot ID")
    snapshot_count: int = Field(default=0, description="Number of snapshots")
    
    # Branch metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True, description="Whether branch is active")
    
    def get_ancestry_chain(self) -> List[str]:
        """Get ancestry chain from this branch to root."""
        chain = [self.branch_name]
        current_branch = self.parent_branch
        
        # Note: In a real implementation, this would query the storage index
        # to build the complete ancestry chain
        while current_branch:
            chain.append(current_branch)
            # Would need to look up parent of current_branch
            break  # Simplified for now
            
        return chain


class CleanupPolicy(BaseModel):
    """Cleanup policy configuration."""
    
    name: str = Field(description="Policy name")
    description: Optional[str] = Field(default=None, description="Policy description")
    
    # Targeting criteria
    branch_patterns: List[str] = Field(default_factory=list, description="Branch patterns to match")
    tag_patterns: List[str] = Field(default_factory=list, description="Tag patterns to match")
    exclude_branches: List[str] = Field(default_factory=list, description="Branches to exclude")
    
    # Retention criteria
    max_age_days: Optional[int] = Field(default=None, description="Maximum age in days")
    max_count: Optional[int] = Field(default=None, description="Maximum number to keep")
    max_size_bytes: Optional[int] = Field(default=None, description="Maximum total size")
    
    # Advanced criteria
    preserve_ancestry: bool = Field(default=True, description="Preserve ancestry chains")
    preserve_tagged: bool = Field(default=True, description="Preserve tagged snapshots")
    preserve_recent_days: int = Field(default=1, description="Always preserve recent snapshots")
    
    # Execution settings
    enabled: bool = Field(default=True, description="Whether policy is enabled")
    priority: int = Field(default=50, description="Policy priority (higher = more important)")
    dry_run: bool = Field(default=False, description="Only simulate cleanup")
    
    def matches_branch(self, branch_name: str) -> bool:
        """Check if branch matches this policy."""
        import fnmatch
        
        # Check exclusions first
        for exclude_pattern in self.exclude_branches:
            if fnmatch.fnmatch(branch_name, exclude_pattern):
                return False
        
        # Check if branch matches any pattern (empty patterns match all)
        if not self.branch_patterns:
            return True
            
        return any(
            fnmatch.fnmatch(branch_name, pattern)
            for pattern in self.branch_patterns
        )
    
    def matches_tags(self, tags: List[str]) -> bool:
        """Check if tags match this policy."""
        import fnmatch
        
        if not self.tag_patterns:
            return True
            
        return any(
            fnmatch.fnmatch(tag, pattern)
            for pattern in self.tag_patterns
            for tag in tags
        )


class CleanupResult(BaseModel):
    """Result of cleanup operation."""
    
    policy_name: str = Field(description="Name of applied policy")
    total_examined: int = Field(description="Total snapshots examined")
    total_deleted: int = Field(description="Total snapshots deleted")
    total_preserved: int = Field(description="Total snapshots preserved")
    bytes_freed: int = Field(description="Bytes freed by cleanup")
    
    # Detailed results
    deleted_snapshots: List[str] = Field(default_factory=list, description="IDs of deleted snapshots")
    preserved_snapshots: List[str] = Field(default_factory=list, description="IDs of preserved snapshots")
    errors: List[str] = Field(default_factory=list, description="Cleanup errors")
    warnings: List[str] = Field(default_factory=list, description="Cleanup warnings")
    
    # Timing information
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    duration_seconds: Optional[float] = Field(default=None)
    
    def mark_completed(self) -> None:
        """Mark cleanup as completed and calculate duration."""
        self.completed_at = datetime.utcnow()
        if self.completed_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
    
    def get_cleanup_summary(self) -> str:
        """Get human-readable cleanup summary."""
        bytes_mb = self.bytes_freed / (1024 * 1024)
        return (
            f"Cleanup '{self.policy_name}': {self.total_deleted} deleted, "
            f"{self.total_preserved} preserved, {bytes_mb:.1f} MB freed"
        )


class StorageStats(BaseModel):
    """Storage usage statistics and health metrics."""
    
    # Basic storage information
    total_snapshots: int = Field(description="Total number of snapshots")
    total_size_bytes: int = Field(description="Total storage used in bytes")
    total_compressed_bytes: int = Field(description="Total compressed size")
    
    # Breakdown by branch
    branch_stats: Dict[str, Dict[str, Union[int, float]]] = Field(
        default_factory=dict, description="Per-branch statistics"
    )
    
    # Storage efficiency
    average_compression_ratio: float = Field(description="Average compression ratio")
    storage_efficiency: float = Field(description="Storage efficiency percentage")
    
    # Health metrics
    corrupted_snapshots: int = Field(default=0, description="Number of corrupted snapshots")
    orphaned_snapshots: int = Field(default=0, description="Number of orphaned snapshots")
    missing_files: int = Field(default=0, description="Number of missing files")
    
    # Storage limits and usage
    storage_limit_bytes: Optional[int] = Field(default=None, description="Storage limit")
    storage_usage_percentage: float = Field(description="Storage usage as percentage of limit")
    storage_warning_threshold: float = Field(default=0.8, description="Warning threshold")
    
    # Temporal information
    oldest_snapshot: Optional[datetime] = Field(default=None, description="Oldest snapshot timestamp")
    newest_snapshot: Optional[datetime] = Field(default=None, description="Newest snapshot timestamp")
    last_cleanup: Optional[datetime] = Field(default=None, description="Last cleanup timestamp")
    
    def is_storage_full(self) -> bool:
        """Check if storage is at or above limit."""
        return self.storage_usage_percentage >= 1.0
    
    def needs_cleanup_warning(self) -> bool:
        """Check if storage usage exceeds warning threshold."""
        return self.storage_usage_percentage >= self.storage_warning_threshold
    
    def get_storage_health_score(self) -> float:
        """Calculate overall storage health score (0-100)."""
        health_factors = []
        
        # Storage usage factor (lower usage = better health)
        usage_factor = max(0, 100 - (self.storage_usage_percentage * 100))
        health_factors.append(usage_factor * 0.4)
        
        # Corruption factor
        corruption_rate = self.corrupted_snapshots / max(self.total_snapshots, 1)
        corruption_factor = max(0, 100 - (corruption_rate * 100))
        health_factors.append(corruption_factor * 0.3)
        
        # Orphan factor
        orphan_rate = self.orphaned_snapshots / max(self.total_snapshots, 1)
        orphan_factor = max(0, 100 - (orphan_rate * 100))
        health_factors.append(orphan_factor * 0.2)
        
        # Efficiency factor
        health_factors.append(self.storage_efficiency * 0.1)
        
        return sum(health_factors)


class StorageIndex(BaseModel):
    """Storage index for efficient querying and management."""
    
    # Index metadata
    version: str = Field(default="1.0", description="Index schema version")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    
    # Storage entries
    entries: Dict[str, StorageEntry] = Field(
        default_factory=dict, description="Storage entries by snapshot ID"
    )
    
    # Branch ancestry
    ancestry: Dict[str, BranchAncestry] = Field(
        default_factory=dict, description="Branch ancestry information"
    )
    
    # Performance optimization indexes
    branch_index: Dict[str, List[str]] = Field(
        default_factory=dict, description="Branch to snapshot IDs mapping"
    )
    
    date_index: Dict[str, List[str]] = Field(
        default_factory=dict, description="Date to snapshot IDs mapping"
    )
    
    tag_index: Dict[str, List[str]] = Field(
        default_factory=dict, description="Tag to snapshot IDs mapping"
    )
    
    checksum_index: Dict[str, List[str]] = Field(
        default_factory=dict, description="Checksum to snapshot IDs mapping for deduplication"
    )
    
    def add_entry(self, entry: StorageEntry) -> None:
        """Add storage entry and update indexes."""
        self.entries[entry.snapshot_id] = entry
        
        # Update branch index
        if entry.branch not in self.branch_index:
            self.branch_index[entry.branch] = []
        self.branch_index[entry.branch].append(entry.snapshot_id)
        
        # Update date index (by day)
        date_key = entry.created_at.strftime("%Y-%m-%d")
        if date_key not in self.date_index:
            self.date_index[date_key] = []
        self.date_index[date_key].append(entry.snapshot_id)
        
        # Update tag index
        for tag in entry.tags:
            if tag not in self.tag_index:
                self.tag_index[tag] = []
            self.tag_index[tag].append(entry.snapshot_id)
        
        # Update checksum index for deduplication
        if entry.checksum not in self.checksum_index:
            self.checksum_index[entry.checksum] = []
        self.checksum_index[entry.checksum].append(entry.snapshot_id)
        
        self.last_updated = datetime.utcnow()
    
    def remove_entry(self, snapshot_id: str) -> Optional[StorageEntry]:
        """Remove storage entry and update indexes."""
        entry = self.entries.pop(snapshot_id, None)
        if not entry:
            return None
        
        # Update branch index
        if entry.branch in self.branch_index:
            try:
                self.branch_index[entry.branch].remove(snapshot_id)
                if not self.branch_index[entry.branch]:
                    del self.branch_index[entry.branch]
            except ValueError:
                pass
        
        # Update date index
        date_key = entry.created_at.strftime("%Y-%m-%d")
        if date_key in self.date_index:
            try:
                self.date_index[date_key].remove(snapshot_id)
                if not self.date_index[date_key]:
                    del self.date_index[date_key]
            except ValueError:
                pass
        
        # Update tag index
        for tag in entry.tags:
            if tag in self.tag_index:
                try:
                    self.tag_index[tag].remove(snapshot_id)
                    if not self.tag_index[tag]:
                        del self.tag_index[tag]
                except ValueError:
                    pass
        
        # Update checksum index
        if entry.checksum in self.checksum_index:
            try:
                self.checksum_index[entry.checksum].remove(snapshot_id)
                if not self.checksum_index[entry.checksum]:
                    del self.checksum_index[entry.checksum]
            except ValueError:
                pass
        
        self.last_updated = datetime.utcnow()
        return entry
    
    def get_snapshots_by_branch(self, branch: str) -> List[StorageEntry]:
        """Get all snapshots for a specific branch."""
        snapshot_ids = self.branch_index.get(branch, [])
        return [self.entries[sid] for sid in snapshot_ids if sid in self.entries]
    
    def get_snapshots_by_tags(self, tags: Set[str]) -> List[StorageEntry]:
        """Get snapshots that have any of the specified tags."""
        matching_ids = set()
        for tag in tags:
            if tag in self.tag_index:
                matching_ids.update(self.tag_index[tag])
        
        return [self.entries[sid] for sid in matching_ids if sid in self.entries]
    
    def find_duplicates(self) -> Dict[str, List[str]]:
        """Find snapshots with identical checksums (potential duplicates)."""
        duplicates = {}
        for checksum, snapshot_ids in self.checksum_index.items():
            if len(snapshot_ids) > 1:
                duplicates[checksum] = snapshot_ids
        return duplicates
    
    def get_expired_snapshots(self) -> List[StorageEntry]:
        """Get snapshots that have expired."""
        now = datetime.utcnow()
        return [
            entry for entry in self.entries.values()
            if entry.expires_at and entry.expires_at < now
        ]


class DeduplicationResult(BaseModel):
    """Result of storage deduplication operation."""
    
    # Deduplication statistics
    total_examined: int = Field(description="Total snapshots examined")
    duplicates_found: int = Field(description="Number of duplicate sets found")
    snapshots_deduplicated: int = Field(description="Number of snapshots deduplicated")
    bytes_saved: int = Field(description="Bytes saved through deduplication")
    
    # Detailed results
    duplicate_groups: Dict[str, List[str]] = Field(
        default_factory=dict, description="Checksum to snapshot IDs mapping"
    )
    preserved_snapshots: List[str] = Field(
        default_factory=list, description="Snapshots preserved as originals"
    )
    linked_snapshots: List[str] = Field(
        default_factory=list, description="Snapshots converted to links"
    )
    
    # Operation metadata
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    duration_seconds: Optional[float] = Field(default=None)
    
    def mark_completed(self) -> None:
        """Mark deduplication as completed."""
        self.completed_at = datetime.utcnow()
        if self.completed_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()


class StorageValidationResult(BaseModel):
    """Result of storage validation and integrity check."""
    
    valid: bool = Field(description="Whether storage is valid")
    
    # Validation statistics
    total_snapshots: int = Field(description="Total snapshots validated")
    valid_snapshots: int = Field(description="Number of valid snapshots")
    corrupted_snapshots: List[str] = Field(default_factory=list, description="Corrupted snapshot IDs")
    orphaned_files: List[str] = Field(default_factory=list, description="Orphaned file paths")
    missing_files: List[str] = Field(default_factory=list, description="Missing file paths")
    
    # Index validation
    index_valid: bool = Field(description="Whether storage index is valid")
    index_inconsistencies: List[str] = Field(default_factory=list, description="Index inconsistencies")
    
    # Repair suggestions
    repairable_issues: List[str] = Field(default_factory=list, description="Issues that can be auto-repaired")
    manual_fixes_required: List[str] = Field(default_factory=list, description="Issues requiring manual intervention")
    
    # Operation metadata
    validation_time_seconds: float = Field(description="Time taken for validation")
    
    def get_health_score(self) -> float:
        """Calculate storage health score (0-100)."""
        if self.total_snapshots == 0:
            return 100.0
        
        # Base score on valid snapshots
        valid_ratio = self.valid_snapshots / self.total_snapshots
        health_score = valid_ratio * 100
        
        # Penalize for corrupted snapshots
        corruption_penalty = (len(self.corrupted_snapshots) / self.total_snapshots) * 20
        health_score -= corruption_penalty
        
        # Penalize for index issues
        if not self.index_valid:
            health_score -= 10
        
        return max(0, min(100, health_score))


class StorageMigrationResult(BaseModel):
    """Result of storage migration operation."""
    
    source_version: str = Field(description="Source storage version")
    target_version: str = Field(description="Target storage version")
    
    # Migration statistics
    snapshots_migrated: int = Field(description="Number of snapshots migrated")
    snapshots_skipped: int = Field(description="Number of snapshots skipped")
    migration_errors: List[str] = Field(default_factory=list, description="Migration errors")
    
    # Operation metadata
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    duration_seconds: Optional[float] = Field(default=None)
    
    def mark_completed(self) -> None:
        """Mark migration as completed."""
        self.completed_at = datetime.utcnow()
        if self.completed_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()


class StorageConfiguration(BaseModel):
    """Storage-specific configuration."""
    
    # Storage paths
    base_path: Path = Field(description="Base storage directory")
    temp_path: Path = Field(description="Temporary storage directory")
    index_path: Path = Field(description="Storage index database path")
    
    # Storage limits
    max_total_size_bytes: Optional[int] = Field(default=None, description="Maximum total storage size")
    max_snapshots_per_branch: Optional[int] = Field(default=None, description="Maximum snapshots per branch")
    warning_threshold: float = Field(default=0.8, description="Storage warning threshold")
    
    # Default retention policies
    default_max_age_days: int = Field(default=30, description="Default maximum age in days")
    default_max_count: int = Field(default=100, description="Default maximum count")
    
    # Performance settings
    enable_compression: bool = Field(default=True, description="Enable compression")
    enable_deduplication: bool = Field(default=True, description="Enable deduplication")
    background_cleanup: bool = Field(default=True, description="Enable background cleanup")
    cleanup_interval_hours: int = Field(default=24, description="Cleanup interval in hours")
    
    # Integrity and validation
    verify_integrity_on_startup: bool = Field(default=False, description="Verify integrity on startup")
    auto_repair_corruption: bool = Field(default=True, description="Auto-repair corruption")
    checksum_verification: bool = Field(default=True, description="Enable checksum verification")
    
    model_config = ConfigDict(arbitrary_types_allowed=True)