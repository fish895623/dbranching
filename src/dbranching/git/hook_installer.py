"""Git hook installation and management system."""

import os
import shutil
import stat
from pathlib import Path
from typing import Dict, List, Optional, Set
import logging

from .exceptions import HookInstallationError, GitRepositoryError

logger = logging.getLogger(__name__)


class HookInstaller:
    """Manages Git hook installation, uninstallation, and chaining."""

    def __init__(self, repo_path: Optional[Path] = None):
        """
        Initialize hook installer.
        
        Args:
            repo_path: Path to Git repository (defaults to current directory)
        """
        self.repo_path = repo_path or Path.cwd()
        self.hooks_dir = self._find_git_hooks_dir()
        self.dbranching_hooks = ["post-checkout", "post-merge"]

    def _find_git_hooks_dir(self) -> Path:
        """Find the Git hooks directory."""
        # Check for .git directory
        git_dir = self.repo_path / ".git"
        
        if git_dir.is_file():
            # .git is a file (worktree or submodule)
            with open(git_dir, 'r') as f:
                git_dir_line = f.read().strip()
                if git_dir_line.startswith("gitdir: "):
                    git_dir = Path(git_dir_line[8:])
                    if not git_dir.is_absolute():
                        git_dir = self.repo_path / git_dir
        elif not git_dir.is_dir():
            raise GitRepositoryError(f"No Git repository found at {self.repo_path}")
        
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        return hooks_dir

    def install_hooks(self, force: bool = False) -> Dict[str, bool]:
        """
        Install dbranching hooks with chaining for existing hooks.
        
        Args:
            force: Force installation even if hooks already installed
            
        Returns:
            Dict mapping hook names to installation success
            
        Raises:
            HookInstallationError: If installation fails
        """
        results = {}
        
        for hook_name in self.dbranching_hooks:
            try:
                success = self._install_single_hook(hook_name, force)
                results[hook_name] = success
                logger.info(f"Hook {hook_name}: {'installed' if success else 'skipped'}")
            except Exception as e:
                logger.error(f"Failed to install {hook_name} hook: {e}")
                results[hook_name] = False
                if not force:
                    # Rollback on partial failure
                    self._rollback_installation(list(results.keys())[:-1])
                    raise HookInstallationError(f"Hook installation failed: {e}", hook_name)
        
        # Validate installed hooks
        validation_errors = self._validate_hooks()
        if validation_errors:
            self._rollback_installation(list(results.keys()))
            raise HookInstallationError(f"Hook validation failed: {'; '.join(validation_errors)}")
        
        return results

    def _install_single_hook(self, hook_name: str, force: bool) -> bool:
        """Install a single hook with proper chaining."""
        hook_path = self.hooks_dir / hook_name
        original_path = self.hooks_dir / f"{hook_name}.dbranching-original"
        
        # Check if already installed
        if not force and self._is_dbranching_hook_installed(hook_path):
            logger.debug(f"Hook {hook_name} already installed, skipping")
            return False
        
        # Backup existing hook if present
        if hook_path.exists() and not self._is_dbranching_hook_installed(hook_path):
            logger.debug(f"Backing up existing {hook_name} hook")
            shutil.copy2(hook_path, original_path)
        
        # Create dbranching hook wrapper
        hook_content = self._create_hook_wrapper(hook_name)
        
        # Write hook atomically
        temp_path = hook_path.with_suffix(".tmp")
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(hook_content)
            
            # Set executable permissions
            temp_path.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)
            
            # Atomic move
            temp_path.rename(hook_path)
            
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise HookInstallationError(f"Failed to write {hook_name} hook: {e}", hook_name)
        
        return True

    def _create_hook_wrapper(self, hook_name: str) -> str:
        """Create hook wrapper script that chains existing hooks with dbranching."""
        original_path = self.hooks_dir / f"{hook_name}.dbranching-original"
        
        hook_content = f'''#!/bin/bash
# DBranching Git Hook Wrapper for {hook_name}
# Generated automatically - do not edit manually

set -e  # Exit on any error

# Execute original hook if it exists
if [ -f "{original_path}" ] && [ -x "{original_path}" ]; then
    echo "Executing original {hook_name} hook..."
    "{original_path}" "$@"
    original_exit_code=$?
    if [ $original_exit_code -ne 0 ]; then
        echo "Original {hook_name} hook failed with exit code $original_exit_code" >&2
        exit $original_exit_code
    fi
fi

# Execute dbranching hook (non-blocking)
echo "Executing dbranching {hook_name} hook..."
if command -v dbranching >/dev/null 2>&1; then
    dbranching hook {hook_name} "$@" || {{
        hook_exit_code=$?
        echo "Warning: dbranching {hook_name} hook failed with exit code $hook_exit_code" >&2
        # Don't fail the Git operation for hook errors
        exit 0
    }}
else
    echo "Warning: dbranching command not found, skipping hook" >&2
fi

exit 0
'''
        return hook_content

    def uninstall_hooks(self) -> Dict[str, bool]:
        """
        Uninstall dbranching hooks and restore originals.
        
        Returns:
            Dict mapping hook names to uninstallation success
        """
        results = {}
        
        for hook_name in self.dbranching_hooks:
            try:
                success = self._uninstall_single_hook(hook_name)
                results[hook_name] = success
                logger.info(f"Hook {hook_name}: {'uninstalled' if success else 'not installed'}")
            except Exception as e:
                logger.error(f"Failed to uninstall {hook_name} hook: {e}")
                results[hook_name] = False
        
        return results

    def _uninstall_single_hook(self, hook_name: str) -> bool:
        """Uninstall a single hook and restore original."""
        hook_path = self.hooks_dir / hook_name
        original_path = self.hooks_dir / f"{hook_name}.dbranching-original"
        
        # Check if our hook is installed
        if not self._is_dbranching_hook_installed(hook_path):
            logger.debug(f"DBranching hook {hook_name} not installed")
            return False
        
        # Remove current hook
        hook_path.unlink()
        
        # Restore original if it exists
        if original_path.exists():
            logger.debug(f"Restoring original {hook_name} hook")
            shutil.move(original_path, hook_path)
        
        return True

    def _rollback_installation(self, installed_hooks: List[str]) -> None:
        """Rollback hook installation for the given hooks."""
        logger.warning("Rolling back hook installation")
        for hook_name in installed_hooks:
            try:
                self._uninstall_single_hook(hook_name)
            except Exception as e:
                logger.error(f"Failed to rollback {hook_name} hook: {e}")

    def _is_dbranching_hook_installed(self, hook_path: Path) -> bool:
        """Check if the hook at the given path is a dbranching hook."""
        if not hook_path.exists():
            return False
        
        try:
            content = hook_path.read_text(encoding='utf-8')
            return "DBranching Git Hook Wrapper" in content
        except Exception:
            return False

    def _validate_hooks(self) -> List[str]:
        """Validate installed hooks and return any errors."""
        errors = []
        
        for hook_name in self.dbranching_hooks:
            hook_path = self.hooks_dir / hook_name
            
            # Check if hook exists
            if not hook_path.exists():
                errors.append(f"Hook {hook_name} not found")
                continue
            
            # Check if hook is executable
            if not os.access(hook_path, os.X_OK):
                errors.append(f"Hook {hook_name} is not executable")
            
            # Check if hook contains our marker
            try:
                content = hook_path.read_text(encoding='utf-8')
                if "DBranching Git Hook Wrapper" not in content:
                    errors.append(f"Hook {hook_name} is not a dbranching hook")
            except Exception as e:
                errors.append(f"Cannot read hook {hook_name}: {e}")
        
        return errors

    def get_hook_status(self) -> Dict[str, Dict[str, any]]:
        """
        Get status of all dbranching hooks.
        
        Returns:
            Dict mapping hook names to their status information
        """
        status = {}
        
        for hook_name in self.dbranching_hooks:
            hook_path = self.hooks_dir / hook_name
            original_path = self.hooks_dir / f"{hook_name}.dbranching-original"
            
            hook_status = {
                "installed": False,
                "is_dbranching_hook": False,
                "executable": False,
                "has_original_backup": original_path.exists(),
                "path": str(hook_path),
                "size": 0,
                "modified_time": None,
            }
            
            if hook_path.exists():
                hook_status["installed"] = True
                hook_status["is_dbranching_hook"] = self._is_dbranching_hook_installed(hook_path)
                hook_status["executable"] = os.access(hook_path, os.X_OK)
                
                try:
                    stat_result = hook_path.stat()
                    hook_status["size"] = stat_result.st_size
                    hook_status["modified_time"] = stat_result.st_mtime
                except Exception:
                    pass
            
            status[hook_name] = hook_status
        
        return status

    def backup_existing_hooks(self, backup_dir: Path) -> Dict[str, bool]:
        """
        Create backup of existing hooks before installation.
        
        Args:
            backup_dir: Directory to store hook backups
            
        Returns:
            Dict mapping hook names to backup success
        """
        backup_dir.mkdir(parents=True, exist_ok=True)
        results = {}
        
        for hook_name in self.dbranching_hooks:
            hook_path = self.hooks_dir / hook_name
            
            if hook_path.exists() and not self._is_dbranching_hook_installed(hook_path):
                try:
                    backup_path = backup_dir / hook_name
                    shutil.copy2(hook_path, backup_path)
                    results[hook_name] = True
                    logger.info(f"Backed up {hook_name} hook to {backup_path}")
                except Exception as e:
                    logger.error(f"Failed to backup {hook_name} hook: {e}")
                    results[hook_name] = False
            else:
                results[hook_name] = True  # No backup needed
        
        return results

    def restore_hooks_from_backup(self, backup_dir: Path) -> Dict[str, bool]:
        """
        Restore hooks from backup directory.
        
        Args:
            backup_dir: Directory containing hook backups
            
        Returns:
            Dict mapping hook names to restore success
        """
        results = {}
        
        for hook_name in self.dbranching_hooks:
            backup_path = backup_dir / hook_name
            hook_path = self.hooks_dir / hook_name
            
            if backup_path.exists():
                try:
                    # Remove current dbranching hook
                    if hook_path.exists():
                        hook_path.unlink()
                    
                    # Restore from backup
                    shutil.copy2(backup_path, hook_path)
                    results[hook_name] = True
                    logger.info(f"Restored {hook_name} hook from {backup_path}")
                except Exception as e:
                    logger.error(f"Failed to restore {hook_name} hook: {e}")
                    results[hook_name] = False
            else:
                # Remove hook if no backup exists
                try:
                    if hook_path.exists():
                        hook_path.unlink()
                    results[hook_name] = True
                except Exception as e:
                    logger.error(f"Failed to remove {hook_name} hook: {e}")
                    results[hook_name] = False
        
        return results