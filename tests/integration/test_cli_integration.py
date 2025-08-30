"""Integration tests for CLI commands with real database connections."""

import tempfile
import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
import yaml
from click.testing import CliRunner

from dbranching.cli import main


@pytest.mark.integration
class TestCLIWorkflows:
    """Test complete CLI workflows."""

    def setup_method(self):
        """Set up test method."""
        self.runner = CliRunner()

    def test_full_initialization_workflow(self):
        """Test complete initialization workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            with patch("pathlib.Path.cwd", return_value=temp_path):
                # Test initialization
                result = self.runner.invoke(main, ["init"])
                assert result.exit_code == 0
                assert "Initialized dbranching" in result.output
                
                config_file = temp_path / "dbranching.yaml"
                assert config_file.exists()
                
                # Test status after initialization
                result = self.runner.invoke(main, ["status"])
                assert result.exit_code == 0
                assert "DBranching Status" in result.output
                assert "Configuration file:" in result.output

    def test_config_management_workflow(self):
        """Test configuration management workflow."""
        config_data = {
            "database": {
                "type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "database": "testdb",
                "username": "testuser",
            },
            "storage": {"directory": "/tmp/test", "compression": "gzip"},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            # Test config list
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "config", "list"]
            )
            assert result.exit_code == 0
            assert "Database Configuration:" in result.output
            assert "postgresql" in result.output

            # Test config get
            result = self.runner.invoke(
                main,
                ["--config-file", str(config_path), "config", "get", "database.type"],
            )
            assert result.exit_code == 0
            assert "postgresql" in result.output.strip()

            # Test config list in different formats
            result = self.runner.invoke(
                main,
                ["--config-file", str(config_path), "config", "list", "--format", "json"],
            )
            assert result.exit_code == 0
            assert "database" in result.output

        finally:
            config_path.unlink()

    def test_error_handling_workflow(self):
        """Test error handling in CLI workflows."""
        # Test with invalid config
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: [")
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status"]
            )
            assert result.exit_code == 2  # Configuration error
            assert "Configuration error" in result.output

        finally:
            config_path.unlink()

    def test_verbose_and_dry_run_combinations(self):
        """Test combinations of verbose and dry-run flags."""
        config_data = {
            "database": {"type": "sqlite", "database": ":memory:"},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            # Test verbose status
            result = self.runner.invoke(
                main,
                ["--verbose", "--config-file", str(config_path), "status"],
            )
            assert result.exit_code == 0
            assert "Database host:" in result.output

            # Test dry-run with various commands
            result = self.runner.invoke(
                main,
                ["--dry-run", "--config-file", str(config_path), "snapshot", "create", "test"],
            )
            assert result.exit_code == 0
            assert "Would create snapshot 'test'" in result.output

        finally:
            config_path.unlink()


@pytest.mark.integration
class TestCLIWithDatabases:
    """Test CLI commands with actual database connections."""

    def setup_method(self):
        """Set up test method."""
        self.runner = CliRunner()

    def test_status_with_sqlite(self):
        """Test status command with SQLite database."""
        config_data = {
            "database": {"type": "sqlite", "database": ":memory:"},
            "storage": {"directory": "/tmp/test"},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status", "--verbose"]
            )
            assert result.exit_code == 0
            assert "sqlite" in result.output.lower()

        finally:
            config_path.unlink()

    def test_snapshot_commands_mock_database(self):
        """Test snapshot commands with mocked database operations."""
        config_data = {
            "database": {"type": "sqlite", "database": ":memory:"},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            # Test snapshot list (not implemented yet)
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "snapshot", "list"]
            )
            assert result.exit_code == 0
            assert "not yet implemented" in result.output

            # Test snapshot create (not implemented yet)
            result = self.runner.invoke(
                main,
                ["--config-file", str(config_path), "snapshot", "create", "test-snapshot"],
            )
            assert result.exit_code == 0
            assert "not yet implemented" in result.output

        finally:
            config_path.unlink()

    @pytest.mark.mysql
    def test_status_with_mysql_unavailable(self):
        """Test status command with MySQL when database is unavailable."""
        config_data = {
            "database": {
                "type": "mysql",
                "host": "nonexistent-host",
                "database": "testdb",
                "username": "testuser",
                "password": "testpass",
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status"]
            )
            # Should succeed even if database is unavailable for status
            assert result.exit_code == 0
            assert "mysql" in result.output.lower()

        finally:
            config_path.unlink()

    @pytest.mark.postgresql
    def test_status_with_postgresql_unavailable(self):
        """Test status command with PostgreSQL when database is unavailable."""
        config_data = {
            "database": {
                "type": "postgresql",
                "host": "nonexistent-host",
                "database": "testdb",
                "username": "testuser",
                "password": "testpass",
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status"]
            )
            # Should succeed even if database is unavailable for status
            assert result.exit_code == 0
            assert "postgresql" in result.output.lower()

        finally:
            config_path.unlink()


@pytest.mark.integration
class TestCLIErrorRecovery:
    """Test CLI error recovery and resilience."""

    def setup_method(self):
        """Set up test method."""
        self.runner = CliRunner()

    def test_graceful_handling_of_missing_config(self):
        """Test graceful handling when config file is missing."""
        result = self.runner.invoke(
            main, ["--config-file", "/nonexistent/path.yaml", "status"]
        )
        assert result.exit_code == 2
        assert "Configuration error" in result.output

    def test_graceful_handling_of_invalid_command(self):
        """Test graceful handling of invalid commands."""
        result = self.runner.invoke(main, ["nonexistent-command"])
        assert result.exit_code == 2
        assert "No such command" in result.output

    def test_help_system_comprehensive(self):
        """Test that help system works for all commands."""
        # Test main help
        result = self.runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Database branching and snapshot management tool" in result.output

        # Test subcommand helps
        for command in ["init", "config", "snapshot", "status"]:
            result = self.runner.invoke(main, [command, "--help"])
            assert result.exit_code == 0
            assert "--help" in result.output or "Show this message and exit" in result.output

        # Test config subcommand helps
        for subcommand in ["list", "get", "set"]:
            result = self.runner.invoke(main, ["config", subcommand, "--help"])
            assert result.exit_code == 0

        # Test snapshot subcommand helps
        for subcommand in ["create", "list", "restore"]:
            result = self.runner.invoke(main, ["snapshot", subcommand, "--help"])
            assert result.exit_code == 0

    def test_global_options_with_all_commands(self):
        """Test that global options work with all commands."""
        # Test verbose flag with different commands
        for command in ["status", ["config", "list"], ["snapshot", "list"]]:
            if isinstance(command, str):
                cmd_args = [command]
            else:
                cmd_args = command

            result = self.runner.invoke(main, ["--verbose"] + cmd_args)
            assert result.exit_code == 0

            # Test dry-run flag
            result = self.runner.invoke(main, ["--dry-run"] + cmd_args)
            assert result.exit_code == 0