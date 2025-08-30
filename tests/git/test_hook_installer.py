"""Tests for Git hook installation functionality."""

import pytest
import stat
from pathlib import Path
from unittest.mock import Mock, patch

from src.dbranching.git.hook_installer import HookInstaller
from src.dbranching.git.exceptions import HookInstallationError, GitRepositoryError


class TestHookInstaller:
    """Test Git hook installation functionality."""

    def test_init_validates_git_repo(self, tmp_path):
        """Test that HookInstaller validates Git repository."""
        with pytest.raises(GitRepositoryError):
            HookInstaller(tmp_path)

    def test_init_with_git_repo(self, tmp_path):
        """Test initialization with valid Git repository."""
        # Create .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir()
        
        installer = HookInstaller(tmp_path)
        assert installer.repo_path == tmp_path
        assert installer.hooks_dir == hooks_dir

    def test_install_single_hook_creates_wrapper(self, tmp_path):
        """Test installation of a single hook creates proper wrapper."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        installer = HookInstaller(tmp_path)
        
        # Install hook
        result = installer._install_single_hook("post-checkout", force=False)
        
        assert result is True
        
        # Check hook file exists and is executable
        hook_path = hooks_dir / "post-checkout"
        assert hook_path.exists()
        assert hook_path.stat().st_mode & stat.S_IEXEC
        
        # Check hook content
        content = hook_path.read_text()
        assert "DBranching Git Hook Wrapper" in content
        assert "dbranching hook post-checkout" in content

    def test_install_single_hook_preserves_existing(self, tmp_path):
        """Test that existing hooks are preserved during installation."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        # Create existing hook
        existing_hook = hooks_dir / "post-checkout"
        existing_hook.write_text("#!/bin/bash\necho 'Original hook'")
        existing_hook.chmod(stat.S_IRWXU)
        
        installer = HookInstaller(tmp_path)
        
        # Install hook
        result = installer._install_single_hook("post-checkout", force=False)
        
        assert result is True
        
        # Check backup was created
        backup_path = hooks_dir / "post-checkout.dbranching-original"
        assert backup_path.exists()
        assert "Original hook" in backup_path.read_text()
        
        # Check new hook calls original
        hook_content = existing_hook.read_text()
        assert "DBranching Git Hook Wrapper" in hook_content
        assert str(backup_path) in hook_content

    def test_install_hooks_atomic_operation(self, tmp_path):
        """Test that hook installation is atomic (all or none)."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        installer = HookInstaller(tmp_path)
        
        # Mock validation to fail
        with patch.object(installer, '_validate_hooks', return_value=['validation error']):
            with pytest.raises(HookInstallationError):
                installer.install_hooks(force=False)
        
        # Check no hooks were left behind
        for hook_name in installer.dbranching_hooks:
            hook_path = hooks_dir / hook_name
            assert not hook_path.exists()

    def test_uninstall_hooks_restores_originals(self, tmp_path):
        """Test that hook uninstallation restores original hooks."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        installer = HookInstaller(tmp_path)
        
        # Install hooks first
        installer.install_hooks(force=False)
        
        # Create fake original backup
        original_content = "#!/bin/bash\necho 'Original hook'"
        backup_path = hooks_dir / "post-checkout.dbranching-original"
        backup_path.write_text(original_content)
        
        # Uninstall hooks
        results = installer.uninstall_hooks()
        
        # Check results
        assert all(results.values())
        
        # Check original hook was restored
        hook_path = hooks_dir / "post-checkout"
        if hook_path.exists():  # May not exist if no original
            assert original_content in hook_path.read_text()
        
        # Check backup was removed
        assert not backup_path.exists()

    def test_is_dbranching_hook_installed(self, tmp_path):
        """Test detection of dbranching hooks."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        installer = HookInstaller(tmp_path)
        
        hook_path = hooks_dir / "post-checkout"
        
        # Test with no hook
        assert not installer._is_dbranching_hook_installed(hook_path)
        
        # Test with non-dbranching hook
        hook_path.write_text("#!/bin/bash\necho 'Some other hook'")
        assert not installer._is_dbranching_hook_installed(hook_path)
        
        # Test with dbranching hook
        hook_path.write_text("#!/bin/bash\n# DBranching Git Hook Wrapper\necho 'test'")
        assert installer._is_dbranching_hook_installed(hook_path)

    def test_get_hook_status(self, tmp_path):
        """Test getting comprehensive hook status."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        installer = HookInstaller(tmp_path)
        
        # Initially no hooks
        status = installer.get_hook_status()
        
        assert "post-checkout" in status
        assert "post-merge" in status
        assert not status["post-checkout"]["installed"]
        
        # Install hooks
        installer.install_hooks(force=False)
        status = installer.get_hook_status()
        
        assert status["post-checkout"]["installed"]
        assert status["post-checkout"]["is_dbranching_hook"]
        assert status["post-checkout"]["executable"]

    def test_backup_and_restore_hooks(self, tmp_path):
        """Test backup and restoration of existing hooks."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        # Create existing hook
        existing_hook = hooks_dir / "post-checkout"
        existing_content = "#!/bin/bash\necho 'Original hook'"
        existing_hook.write_text(existing_content)
        existing_hook.chmod(stat.S_IRWXU)
        
        installer = HookInstaller(tmp_path)
        
        # Test backup
        backup_dir = tmp_path / "backup"
        results = installer.backup_existing_hooks(backup_dir)
        
        assert results["post-checkout"] is True
        assert (backup_dir / "post-checkout").exists()
        assert existing_content in (backup_dir / "post-checkout").read_text()
        
        # Install dbranching hooks
        installer.install_hooks(force=False)
        
        # Test restoration
        restore_results = installer.restore_hooks_from_backup(backup_dir)
        
        assert restore_results["post-checkout"] is True
        assert existing_content in existing_hook.read_text()
        assert not installer._is_dbranching_hook_installed(existing_hook)

    def test_validate_hooks(self, tmp_path):
        """Test hook validation functionality."""
        # Setup Git repository
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        
        installer = HookInstaller(tmp_path)
        
        # Test with no hooks
        errors = installer._validate_hooks()
        assert len(errors) == len(installer.dbranching_hooks)  # All hooks missing
        
        # Install valid hooks
        installer.install_hooks(force=False)
        errors = installer._validate_hooks()
        assert len(errors) == 0  # No errors
        
        # Create invalid hook (not executable)
        hook_path = hooks_dir / "post-checkout"
        hook_path.chmod(0o644)  # Remove execute permission
        
        errors = installer._validate_hooks()
        assert any("not executable" in error for error in errors)