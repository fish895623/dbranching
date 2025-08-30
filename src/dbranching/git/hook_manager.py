"""Git hook manager that coordinates hook operations and snapshot integration."""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Any
import tempfile

from ..config import Config
from ..snapshot.engine import SnapshotEngine
from ..snapshot.models import SnapshotCreateOptions
from .branch_detector import BranchDetector, GitOperation
from .hook_installer import HookInstaller
from .exceptions import GitIntegrationError, HookExecutionError

logger = logging.getLogger(__name__)


class GitHookManager:
    """Manages Git hook lifecycle and integration with snapshot engine."""

    def __init__(self, config: Config, repo_path: Optional[Path] = None):
        """
        Initialize Git hook manager.
        
        Args:
            config: dbranching configuration
            repo_path: Path to Git repository (defaults to current directory)
        """
        self.config = config
        self.repo_path = repo_path or Path.cwd()
        
        # Initialize components
        self.branch_detector = BranchDetector(repo_path)
        self.hook_installer = HookInstaller(repo_path)
        
        # Setup logging for hook execution
        self.hook_log_file = self._setup_hook_logging()

    def _setup_hook_logging(self) -> Optional[Path]:
        """Setup dedicated logging for hook execution."""
        if self.config.logging.file:
            hook_log_dir = self.config.logging.file.parent / "hooks"
            hook_log_dir.mkdir(parents=True, exist_ok=True)
            return hook_log_dir / "git-hooks.log"
        return None

    async def install_hooks(self, force: bool = False) -> Dict[str, bool]:
        """
        Install Git hooks with validation.
        
        Args:
            force: Force installation even if hooks already exist
            
        Returns:
            Dict mapping hook names to installation success
            
        Raises:
            GitIntegrationError: If installation fails
        """
        try:
            logger.info("Installing Git hooks...")
            
            # Check if hooks are enabled
            if not self.config.git.hooks.get("enabled", True):
                logger.info("Git hooks are disabled in configuration")
                return {}
            
            # Create backup before installation
            backup_dir = self._create_backup_directory()
            backup_results = self.hook_installer.backup_existing_hooks(backup_dir)
            
            failed_backups = [name for name, success in backup_results.items() if not success]
            if failed_backups and not force:
                raise GitIntegrationError(f"Failed to backup existing hooks: {', '.join(failed_backups)}")
            
            # Install hooks
            install_results = self.hook_installer.install_hooks(force)
            
            # Verify installation
            status = self.get_hook_status()
            failed_hooks = [name for name, info in status.items() 
                          if info["installed"] and not info["is_dbranching_hook"]]
            
            if failed_hooks:
                raise GitIntegrationError(f"Hook installation verification failed: {', '.join(failed_hooks)}")
            
            logger.info(f"Successfully installed {len(install_results)} Git hooks")
            return install_results
            
        except Exception as e:
            logger.error(f"Git hook installation failed: {e}")
            raise GitIntegrationError(f"Hook installation failed: {e}")

    async def uninstall_hooks(self) -> Dict[str, bool]:
        """
        Uninstall Git hooks and restore originals.
        
        Returns:
            Dict mapping hook names to uninstallation success
        """
        try:
            logger.info("Uninstalling Git hooks...")
            results = self.hook_installer.uninstall_hooks()
            
            successful = sum(1 for success in results.values() if success)
            logger.info(f"Successfully uninstalled {successful}/{len(results)} Git hooks")
            return results
            
        except Exception as e:
            logger.error(f"Git hook uninstallation failed: {e}")
            raise GitIntegrationError(f"Hook uninstallation failed: {e}")

    def get_hook_status(self) -> Dict[str, Dict[str, Any]]:
        """Get comprehensive status of all Git hooks."""
        return self.hook_installer.get_hook_status()

    async def handle_post_checkout(self, previous_ref: str, current_ref: str, branch_flag: str) -> int:
        """
        Handle post-checkout hook execution.
        
        Args:
            previous_ref: Previous HEAD reference
            current_ref: New HEAD reference
            branch_flag: "1" for branch checkout, "0" for file checkout
            
        Returns:
            Exit code (0 for success, non-zero for failure)
        """
        try:
            # Log hook execution
            self._log_hook_execution("post-checkout", {
                "previous_ref": previous_ref,
                "current_ref": current_ref,
                "branch_flag": branch_flag
            })
            
            # Detect operation type
            operation = self.branch_detector.detect_post_checkout_operation(
                previous_ref, current_ref, branch_flag
            )
            
            # Check if snapshot should be triggered
            if not self._should_create_snapshot(operation):
                logger.debug(f"Skipping snapshot for {operation.operation_type}")
                return 0
            
            # Create snapshot asynchronously to avoid blocking Git
            await self._create_hook_snapshot(operation, "post-checkout")
            return 0
            
        except Exception as e:
            # Log error but don't fail the Git operation
            self._log_hook_error("post-checkout", e)
            logger.warning(f"Post-checkout hook failed: {e}")
            return 0  # Don't block Git operations

    async def handle_post_merge(self, merge_commit: str = "HEAD") -> int:
        """
        Handle post-merge hook execution.
        
        Args:
            merge_commit: Merge commit reference
            
        Returns:
            Exit code (0 for success)
        """
        try:
            # Log hook execution
            self._log_hook_execution("post-merge", {
                "merge_commit": merge_commit
            })
            
            # Detect merge operation
            operation = self.branch_detector.detect_post_merge_operation(merge_commit)
            
            # Check if snapshot should be triggered
            if not self._should_create_snapshot(operation):
                logger.debug("Skipping snapshot for merge operation")
                return 0
            
            # Create snapshot for merge
            await self._create_hook_snapshot(operation, "post-merge")
            return 0
            
        except Exception as e:
            # Log error but don't fail the Git operation
            self._log_hook_error("post-merge", e)
            logger.warning(f"Post-merge hook failed: {e}")
            return 0

    def _should_create_snapshot(self, operation: GitOperation) -> bool:
        """Determine if operation should trigger snapshot creation."""
        auto_snapshot_branches = self.config.git.branches.get("auto_snapshot", ["main", "develop"])
        ignore_patterns = self.config.git.branches.get("ignore", ["temp/*", "wip/*"])
        
        return self.branch_detector.should_trigger_snapshot(
            operation, auto_snapshot_branches, ignore_patterns
        )

    async def _create_hook_snapshot(self, operation: GitOperation, hook_type: str) -> None:
        """Create snapshot for Git hook operation."""
        try:
            # Generate snapshot name
            snapshot_name = self._generate_snapshot_name(operation, hook_type)
            
            # Generate description
            description = self._generate_snapshot_description(operation, hook_type)
            
            # Create snapshot options
            options = SnapshotCreateOptions(
                name=snapshot_name,
                description=description,
                tags=["git-hook", hook_type, operation.branch_name] if operation.branch_name else ["git-hook", hook_type],
                compression_level=6,  # Medium compression for speed
                verify_integrity=False,  # Skip verification for speed
                atomic=True
            )
            
            # Initialize snapshot engine
            snapshot_engine = SnapshotEngine(
                database_config=self.config.database,
                storage_base_path=self.config.storage.path,
                temp_dir=Path(tempfile.gettempdir()) / "dbranching" / "hooks"
            )
            
            logger.info(f"Creating Git hook snapshot: {snapshot_name}")
            
            # Create snapshot asynchronously
            snapshot_info = await snapshot_engine.create_snapshot(options)
            
            logger.info(f"Git hook snapshot created: {snapshot_info.name} ({snapshot_info.size_bytes} bytes)")
            
        except Exception as e:
            # Log error but continue (don't block Git operations)
            logger.error(f"Failed to create Git hook snapshot: {e}")
            raise HookExecutionError(f"Snapshot creation failed: {e}", hook_type)

    def _generate_snapshot_name(self, operation: GitOperation, hook_type: str) -> str:
        """Generate descriptive snapshot name for Git operation."""
        timestamp = int(time.time())
        
        if operation.operation_type == "branch_checkout":
            if operation.is_new_branch and operation.branch_name:
                return f"git-{hook_type}-new-{operation.branch_name}-{timestamp}"
            elif operation.branch_name:
                return f"git-{hook_type}-{operation.branch_name}-{timestamp}"
            else:
                return f"git-{hook_type}-checkout-{timestamp}"
                
        elif operation.operation_type == "merge":
            if operation.branch_name:
                return f"git-{hook_type}-{operation.branch_name}-{timestamp}"
            else:
                return f"git-{hook_type}-merge-{timestamp}"
        
        return f"git-{hook_type}-{timestamp}"

    def _generate_snapshot_description(self, operation: GitOperation, hook_type: str) -> str:
        """Generate descriptive snapshot description for Git operation."""
        if operation.operation_type == "branch_checkout":
            if operation.is_new_branch and operation.branch_name:
                return f"Automatic snapshot after creating new branch '{operation.branch_name}'"
            elif operation.branch_name:
                return f"Automatic snapshot after switching to branch '{operation.branch_name}'"
            else:
                return f"Automatic snapshot after Git checkout"
                
        elif operation.operation_type == "merge":
            merge_info = operation.merge_info or {}
            if operation.branch_name:
                if merge_info.get("is_merge"):
                    return f"Automatic snapshot after merge into branch '{operation.branch_name}'"
                else:
                    return f"Automatic snapshot after commit to branch '{operation.branch_name}'"
            else:
                return f"Automatic snapshot after Git merge"
        
        return f"Automatic snapshot from Git {hook_type} hook"

    def _create_backup_directory(self) -> Path:
        """Create backup directory for existing hooks."""
        backup_dir = self.config.storage.path / "hook-backups" / f"backup-{int(time.time())}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def _log_hook_execution(self, hook_type: str, params: Dict[str, Any]) -> None:
        """Log hook execution for debugging."""
        if not self.hook_log_file:
            return
        
        log_entry = {
            "timestamp": time.time(),
            "hook_type": hook_type,
            "params": params,
            "repo_path": str(self.repo_path)
        }
        
        try:
            with open(self.hook_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.warning(f"Failed to write hook log: {e}")

    def _log_hook_error(self, hook_type: str, error: Exception) -> None:
        """Log hook execution error."""
        if not self.hook_log_file:
            return
        
        log_entry = {
            "timestamp": time.time(),
            "hook_type": hook_type,
            "error": str(error),
            "error_type": type(error).__name__,
            "repo_path": str(self.repo_path)
        }
        
        try:
            with open(self.hook_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.warning(f"Failed to write hook error log: {e}")

    async def test_hook_integration(self) -> Dict[str, Any]:
        """Test Git hook integration without triggering actual operations."""
        test_results = {
            "hook_status": self.get_hook_status(),
            "repository_info": {},
            "configuration": {
                "hooks_enabled": self.config.git.hooks.get("enabled", True),
                "auto_snapshot_branches": self.config.git.branches.get("auto_snapshot", []),
                "ignore_patterns": self.config.git.branches.get("ignore", [])
            },
            "tests": {}
        }
        
        try:
            # Test repository access
            test_results["repository_info"] = self.branch_detector.get_repository_info()
            test_results["tests"]["repository_access"] = True
        except Exception as e:
            test_results["tests"]["repository_access"] = False
            test_results["tests"]["repository_error"] = str(e)
        
        try:
            # Test snapshot engine initialization
            snapshot_engine = SnapshotEngine(
                database_config=self.config.database,
                storage_base_path=self.config.storage.path
            )
            test_results["tests"]["snapshot_engine"] = True
        except Exception as e:
            test_results["tests"]["snapshot_engine"] = False
            test_results["tests"]["snapshot_error"] = str(e)
        
        return test_results