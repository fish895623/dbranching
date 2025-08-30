"""Tests for Git branch detection functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess

from src.dbranching.git.branch_detector import BranchDetector, GitOperation
from src.dbranching.git.exceptions import BranchDetectionError, GitRepositoryError


class TestBranchDetector:
    """Test Git branch detection functionality."""

    def test_init_validates_git_repo(self, tmp_path):
        """Test that BranchDetector validates Git repository existence."""
        # Test with non-Git directory
        with pytest.raises(GitRepositoryError, match="Not a Git repository"):
            BranchDetector(tmp_path)

    @patch('subprocess.run')
    def test_init_finds_git_root(self, mock_run, tmp_path):
        """Test that BranchDetector finds Git repository root."""
        # Mock git rev-parse commands
        mock_run.side_effect = [
            Mock(returncode=0),  # rev-parse --git-dir
            Mock(returncode=0, stdout=str(tmp_path) + '\n')  # rev-parse --show-toplevel
        ]
        
        detector = BranchDetector(tmp_path)
        assert detector.repo_path == tmp_path

    @patch('subprocess.run')
    def test_detect_post_checkout_file_checkout(self, mock_run, tmp_path):
        """Test detection of file checkout operations."""
        # Mock git commands for repo validation
        mock_run.side_effect = [
            Mock(returncode=0),  # rev-parse --git-dir
            Mock(returncode=0, stdout=str(tmp_path) + '\n')  # rev-parse --show-toplevel
        ]
        
        detector = BranchDetector(tmp_path)
        
        # Test file checkout detection
        operation = detector.detect_post_checkout_operation("abc123", "def456", "0")
        
        assert operation.operation_type == "file_checkout"
        assert operation.is_file_checkout is True
        assert operation.previous_ref == "abc123"
        assert operation.current_ref == "def456"

    @patch('subprocess.run')
    def test_detect_post_checkout_branch_switch(self, mock_run, tmp_path):
        """Test detection of branch switch operations."""
        # Mock git commands
        mock_run.side_effect = [
            Mock(returncode=0),  # rev-parse --git-dir (init)
            Mock(returncode=0, stdout=str(tmp_path) + '\n'),  # show-toplevel (init)
            Mock(returncode=0, stdout='feature-branch\n'),  # get current branch
            Mock(returncode=1)  # merge-base check (not ancestor)
        ]
        
        detector = BranchDetector(tmp_path)
        
        operation = detector.detect_post_checkout_operation("abc123", "def456", "1")
        
        assert operation.operation_type == "branch_checkout"
        assert operation.is_file_checkout is False
        assert operation.branch_name == "feature-branch"
        assert operation.is_new_branch is True

    @patch('subprocess.run')
    def test_detect_post_merge_operation(self, mock_run, tmp_path):
        """Test detection of merge operations."""
        # Mock git commands
        mock_run.side_effect = [
            Mock(returncode=0),  # rev-parse --git-dir (init)
            Mock(returncode=0, stdout=str(tmp_path) + '\n'),  # show-toplevel (init)
            Mock(returncode=0, stdout='main\n'),  # get current branch
            Mock(returncode=0, stdout='abc123 def456 ghi789\n'),  # rev-list parents
            Mock(returncode=0, stdout='Merge feature into main\n')  # commit message
        ]
        
        detector = BranchDetector(tmp_path)
        
        operation = detector.detect_post_merge_operation("HEAD")
        
        assert operation.operation_type == "merge"
        assert operation.branch_name == "main"
        assert operation.merge_info["is_merge"] is True
        assert "parents" in operation.merge_info

    def test_should_trigger_snapshot_with_matching_pattern(self):
        """Test snapshot triggering with matching branch patterns."""
        detector = Mock()  # We don't need a real detector for this test
        detector._match_pattern = BranchDetector._match_pattern.__get__(detector)
        
        operation = GitOperation(
            operation_type="branch_checkout",
            branch_name="main",
            is_file_checkout=False
        )
        
        result = BranchDetector.should_trigger_snapshot(
            detector, operation, ["main", "develop"], ["temp/*"]
        )
        
        assert result is True

    def test_should_trigger_snapshot_with_ignore_pattern(self):
        """Test snapshot triggering with ignore patterns."""
        detector = Mock()
        detector._match_pattern = BranchDetector._match_pattern.__get__(detector)
        
        operation = GitOperation(
            operation_type="branch_checkout",
            branch_name="temp/testing",
            is_file_checkout=False
        )
        
        result = BranchDetector.should_trigger_snapshot(
            detector, operation, ["*"], ["temp/*"]
        )
        
        assert result is False

    def test_should_not_trigger_snapshot_for_file_checkout(self):
        """Test that file checkouts don't trigger snapshots."""
        detector = Mock()
        detector._match_pattern = BranchDetector._match_pattern.__get__(detector)
        
        operation = GitOperation(
            operation_type="file_checkout",
            is_file_checkout=True
        )
        
        result = BranchDetector.should_trigger_snapshot(
            detector, operation, ["*"], []
        )
        
        assert result is False

    @patch('subprocess.run')
    def test_get_repository_info(self, mock_run, tmp_path):
        """Test getting repository information."""
        # Mock git commands for initialization and info gathering
        mock_run.side_effect = [
            Mock(returncode=0),  # rev-parse --git-dir (init)
            Mock(returncode=0, stdout=str(tmp_path) + '\n'),  # show-toplevel (init)
            Mock(returncode=0, stdout='feature-branch\n'),  # current branch
            Mock(returncode=0, stdout='abc123def456\n'),  # current commit
            Mock(returncode=0, stdout=''),  # status --porcelain (clean)
            Mock(returncode=0, stdout='git@github.com:user/repo.git\n')  # remote URL
        ]
        
        detector = BranchDetector(tmp_path)
        info = detector.get_repository_info()
        
        assert info["repo_path"] == str(tmp_path)
        assert info["current_branch"] == "feature-branch"
        assert info["current_commit"] == "abc123def456"
        assert info["is_dirty"] is False
        assert info["remote_url"] == "git@github.com:user/repo.git"

    def test_match_pattern_with_wildcards(self):
        """Test pattern matching with wildcards."""
        detector = BranchDetector.__new__(BranchDetector)  # Create instance without __init__
        
        assert detector._match_pattern("feature-auth", "feature-*") is True
        assert detector._match_pattern("main", "main") is True
        assert detector._match_pattern("temp/testing", "temp/*") is True
        assert detector._match_pattern("feature-auth", "bug-*") is False

    @patch('subprocess.run')
    def test_error_handling_in_branch_detection(self, mock_run, tmp_path):
        """Test error handling during branch detection operations."""
        # Mock git commands for initialization
        mock_run.side_effect = [
            Mock(returncode=0),  # rev-parse --git-dir (init)
            Mock(returncode=0, stdout=str(tmp_path) + '\n'),  # show-toplevel (init)
            subprocess.TimeoutExpired(['git', 'rev-parse'], 5)  # Timeout on branch detection
        ]
        
        detector = BranchDetector(tmp_path)
        
        with pytest.raises(BranchDetectionError):
            detector.detect_post_checkout_operation("abc123", "def456", "1")