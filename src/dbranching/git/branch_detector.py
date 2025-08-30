"""Branch detection and Git operation analysis."""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import logging

from .exceptions import BranchDetectionError, GitRepositoryError

logger = logging.getLogger(__name__)


class GitOperation:
    """Represents a Git operation that may trigger a snapshot."""
    
    def __init__(
        self,
        operation_type: str,
        previous_ref: Optional[str] = None,
        current_ref: Optional[str] = None,
        branch_name: Optional[str] = None,
        is_new_branch: bool = False,
        is_file_checkout: bool = False,
        merge_info: Optional[Dict[str, Any]] = None
    ):
        self.operation_type = operation_type
        self.previous_ref = previous_ref
        self.current_ref = current_ref
        self.branch_name = branch_name
        self.is_new_branch = is_new_branch
        self.is_file_checkout = is_file_checkout
        self.merge_info = merge_info or {}


class BranchDetector:
    """Detects Git branch operations and determines if snapshots should be triggered."""

    def __init__(self, repo_path: Optional[Path] = None):
        """
        Initialize branch detector.
        
        Args:
            repo_path: Path to Git repository (defaults to current directory)
        """
        self.repo_path = repo_path or Path.cwd()
        self._validate_git_repo()

    def _validate_git_repo(self) -> None:
        """Validate that we're in a Git repository."""
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            # Check if we're in a subdirectory of a Git repo
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode != 0:
                    raise GitRepositoryError(
                        f"Not a Git repository: {self.repo_path}",
                        str(self.repo_path)
                    )
                # Update repo path to actual Git root
                git_root = subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if git_root.returncode == 0:
                    self.repo_path = Path(git_root.stdout.strip())
            except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
                raise GitRepositoryError(f"Git command failed: {e}")

    def detect_post_checkout_operation(
        self,
        previous_ref: str,
        current_ref: str,
        branch_checkout_flag: str
    ) -> GitOperation:
        """
        Detect and analyze post-checkout hook operation.
        
        Args:
            previous_ref: Previous HEAD reference
            current_ref: New HEAD reference  
            branch_checkout_flag: "1" for branch checkout, "0" for file checkout
            
        Returns:
            GitOperation with analysis results
            
        Raises:
            BranchDetectionError: If operation analysis fails
        """
        try:
            is_file_checkout = branch_checkout_flag == "0"
            
            # If it's a file checkout, don't trigger snapshot
            if is_file_checkout:
                return GitOperation(
                    operation_type="file_checkout",
                    previous_ref=previous_ref,
                    current_ref=current_ref,
                    is_file_checkout=True
                )

            # Get current branch name
            current_branch = self._get_current_branch()
            
            # Check if this is a new branch creation
            is_new_branch = self._is_new_branch_creation(previous_ref, current_ref)
            
            logger.info(f"Post-checkout: {previous_ref[:8]} → {current_branch} (new: {is_new_branch})")
            
            return GitOperation(
                operation_type="branch_checkout",
                previous_ref=previous_ref,
                current_ref=current_ref,
                branch_name=current_branch,
                is_new_branch=is_new_branch,
                is_file_checkout=False
            )
            
        except Exception as e:
            raise BranchDetectionError(f"Failed to detect post-checkout operation: {e}")

    def detect_post_merge_operation(self, merge_commit: str = "HEAD") -> GitOperation:
        """
        Detect and analyze post-merge hook operation.
        
        Args:
            merge_commit: Merge commit reference (default: HEAD)
            
        Returns:
            GitOperation with merge analysis
            
        Raises:
            BranchDetectionError: If merge analysis fails
        """
        try:
            current_branch = self._get_current_branch()
            merge_info = self._analyze_merge(merge_commit)
            
            logger.info(f"Post-merge: branch={current_branch}, parents={len(merge_info.get('parents', []))}")
            
            return GitOperation(
                operation_type="merge",
                current_ref=merge_commit,
                branch_name=current_branch,
                merge_info=merge_info
            )
            
        except Exception as e:
            raise BranchDetectionError(f"Failed to detect post-merge operation: {e}")

    def should_trigger_snapshot(
        self,
        operation: GitOperation,
        auto_snapshot_branches: list[str],
        ignore_patterns: list[str]
    ) -> bool:
        """
        Determine if operation should trigger snapshot creation.
        
        Args:
            operation: Git operation to analyze
            auto_snapshot_branches: Branch patterns that trigger snapshots
            ignore_patterns: Branch patterns to ignore
            
        Returns:
            True if snapshot should be created
        """
        # Skip file checkouts
        if operation.is_file_checkout:
            return False
            
        # Skip if no branch name available
        if not operation.branch_name:
            return False
            
        # Check ignore patterns first
        for pattern in ignore_patterns:
            if self._match_pattern(operation.branch_name, pattern):
                logger.debug(f"Branch {operation.branch_name} matches ignore pattern: {pattern}")
                return False
                
        # Check auto-snapshot patterns
        for pattern in auto_snapshot_branches:
            if self._match_pattern(operation.branch_name, pattern):
                logger.debug(f"Branch {operation.branch_name} matches auto-snapshot pattern: {pattern}")
                return True
                
        logger.debug(f"Branch {operation.branch_name} does not match any auto-snapshot patterns")
        return False

    def _get_current_branch(self) -> Optional[str]:
        """Get current branch name, handling detached HEAD."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                branch_name = result.stdout.strip()
                return None if branch_name == "HEAD" else branch_name
            return None
            
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return None

    def _is_new_branch_creation(self, previous_ref: str, current_ref: str) -> bool:
        """Check if this checkout created a new branch."""
        try:
            # If previous ref is all zeros, it's likely a new branch
            if previous_ref == "0" * len(previous_ref):
                return True
                
            # Check if the current ref has a different commit than previous
            if previous_ref != current_ref:
                # Check if current ref exists in history before previous ref
                result = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", current_ref, previous_ref],
                    cwd=self.repo_path,
                    capture_output=True,
                    timeout=5
                )
                # If current_ref is not an ancestor of previous_ref, it might be a new branch
                return result.returncode != 0
                
            return False
            
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            # If we can't determine, err on the side of caution
            return False

    def _analyze_merge(self, merge_commit: str) -> Dict[str, Any]:
        """Analyze merge commit for metadata."""
        merge_info = {}
        
        try:
            # Get merge commit parents
            result = subprocess.run(
                ["git", "rev-list", "--parents", "-n", "1", merge_commit],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                if len(parts) > 2:  # Merge commit has multiple parents
                    merge_info["parents"] = parts[1:]  # Exclude the commit itself
                    merge_info["is_merge"] = True
                else:
                    merge_info["is_merge"] = False
                    
            # Get merge commit message
            result = subprocess.run(
                ["git", "log", "--format=%s", "-n", "1", merge_commit],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                merge_info["message"] = result.stdout.strip()
                # Check if it looks like a merge commit
                if "Merge " in merge_info["message"]:
                    merge_info["is_merge"] = True
                    
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            logger.warning(f"Failed to analyze merge commit {merge_commit}: {e}")
            
        return merge_info

    def _match_pattern(self, branch_name: str, pattern: str) -> bool:
        """Match branch name against pattern (supports simple wildcards)."""
        import fnmatch
        return fnmatch.fnmatch(branch_name, pattern)

    def get_repository_info(self) -> Dict[str, Any]:
        """Get general repository information."""
        info = {
            "repo_path": str(self.repo_path),
            "current_branch": None,
            "current_commit": None,
            "is_dirty": False,
            "remote_url": None
        }
        
        try:
            # Current branch
            info["current_branch"] = self._get_current_branch()
            
            # Current commit
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                info["current_commit"] = result.stdout.strip()
                
            # Check if working directory is dirty
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                info["is_dirty"] = bool(result.stdout.strip())
                
            # Get remote URL
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                info["remote_url"] = result.stdout.strip()
                
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            logger.warning(f"Failed to get repository info: {e}")
            
        return info