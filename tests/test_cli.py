"""Tests for CLI interface."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from dbranching.cli import main


class TestMainCommand:
    """Test main CLI command."""

    def setup_method(self) -> None:
        """Set up test method."""
        self.runner = CliRunner()

    def test_main_help(self) -> None:
        """Test main command help."""
        result = self.runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Database branching and snapshot management tool" in result.output
        assert "dbranching init" in result.output

    def test_main_no_command_shows_help(self) -> None:
        """Test that main command without subcommand shows help."""
        result = self.runner.invoke(main)
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_verbose_option(self) -> None:
        """Test verbose option."""
        result = self.runner.invoke(main, ["--verbose", "status"])
        # Should succeed even without config (uses defaults)
        assert result.exit_code == 0

    def test_dry_run_option(self) -> None:
        """Test dry-run option."""
        result = self.runner.invoke(main, ["--dry-run", "status"])
        assert result.exit_code == 0

    def test_config_file_option(self) -> None:
        """Test config file option with valid file."""
        config_data = {
            "database": {"type": "postgresql", "database": "test", "username": "user"}
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status"]
            )
            assert result.exit_code == 0
        finally:
            config_path.unlink()

    def test_invalid_config_file(self) -> None:
        """Test with invalid config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: [")
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status"]
            )
            assert result.exit_code == 2  # ConfigurationError exit code
            assert "Configuration error" in result.output
        finally:
            config_path.unlink()


class TestInitCommand:
    """Test init command."""

    def setup_method(self) -> None:
        """Set up test method."""
        self.runner = CliRunner()

    def test_init_command(self) -> None:
        """Test init command creates config file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "dbranching.yaml"

            with patch("pathlib.Path.cwd", return_value=Path(temp_dir)):
                result = self.runner.invoke(main, ["init"])

            assert result.exit_code == 0
            assert config_path.exists()
            assert "Initialized dbranching" in result.output

    def test_init_dry_run(self) -> None:
        """Test init command with dry-run."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "dbranching.yaml"

            with patch("pathlib.Path.cwd", return_value=Path(temp_dir)):
                result = self.runner.invoke(main, ["--dry-run", "init"])

            assert result.exit_code == 0
            assert not config_path.exists()
            assert "Would create configuration file" in result.output

    def test_init_already_initialized(self) -> None:
        """Test init command when already initialized."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "dbranching.yaml"
            config_path.write_text("database:\n  type: postgresql\n")

            with patch("pathlib.Path.cwd", return_value=Path(temp_dir)):
                result = self.runner.invoke(main, ["init"])

            assert result.exit_code == 0
            assert "Already initialized" in result.output
            assert "Use --force to reinitialize" in result.output

    def test_init_force_reinitialize(self) -> None:
        """Test init command with force flag."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "dbranching.yaml"
            config_path.write_text("old config")

            with patch("pathlib.Path.cwd", return_value=Path(temp_dir)):
                result = self.runner.invoke(main, ["init", "--force"])

            assert result.exit_code == 0
            assert "Initialized dbranching" in result.output
            # Config should be replaced with valid YAML
            content = config_path.read_text()
            assert "database:" in content

    def test_init_help(self) -> None:
        """Test init command help."""
        result = self.runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "Initialize dbranching in the current directory" in result.output
        assert "--force" in result.output


class TestConfigCommand:
    """Test config command group."""

    def setup_method(self) -> None:
        """Set up test method."""
        self.runner = CliRunner()

    def test_config_help(self) -> None:
        """Test config command help."""
        result = self.runner.invoke(main, ["config", "--help"])
        assert result.exit_code == 0
        assert "Manage dbranching configuration" in result.output

    def test_config_list_table_format(self) -> None:
        """Test config list command with table format."""
        result = self.runner.invoke(main, ["config", "list"])
        assert result.exit_code == 0
        assert "Database Configuration:" in result.output
        assert "Storage Configuration:" in result.output
        assert "Logging Configuration:" in result.output

    def test_config_list_yaml_format(self) -> None:
        """Test config list command with YAML format."""
        result = self.runner.invoke(main, ["config", "list", "--format", "yaml"])
        assert result.exit_code == 0
        assert "database:" in result.output
        assert "storage:" in result.output

    def test_config_list_json_format(self) -> None:
        """Test config list command with JSON format."""
        result = self.runner.invoke(main, ["config", "list", "--format", "json"])
        assert result.exit_code == 0
        # Should be valid JSON
        config_output = json.loads(result.output)
        assert "database" in config_output
        assert "storage" in config_output

    def test_config_get_existing_key(self) -> None:
        """Test config get command with existing key."""
        result = self.runner.invoke(main, ["config", "get", "database.type"])
        assert result.exit_code == 0
        assert "postgresql" in result.output.strip()

    def test_config_get_nested_key(self) -> None:
        """Test config get command with nested key."""
        result = self.runner.invoke(main, ["config", "get", "database.port"])
        assert result.exit_code == 0
        assert "5432" in result.output.strip()

    def test_config_get_nonexistent_key(self) -> None:
        """Test config get command with nonexistent key."""
        result = self.runner.invoke(main, ["config", "get", "nonexistent.key"])
        assert result.exit_code == 1
        assert "Configuration key 'nonexistent.key' not found" in result.output

    def test_config_set_not_implemented(self) -> None:
        """Test config set command (not yet implemented)."""
        result = self.runner.invoke(main, ["config", "set", "database.host", "newhost"])
        assert result.exit_code == 0
        assert "Configuration modification not yet implemented" in result.output

    def test_config_set_dry_run(self) -> None:
        """Test config set command with dry-run."""
        result = self.runner.invoke(
            main, ["--dry-run", "config", "set", "database.host", "newhost"]
        )
        assert result.exit_code == 0
        assert "Would set database.host = newhost" in result.output


class TestSnapshotCommand:
    """Test snapshot command group."""

    def setup_method(self) -> None:
        """Set up test method."""
        self.runner = CliRunner()

    def test_snapshot_help(self) -> None:
        """Test snapshot command help."""
        result = self.runner.invoke(main, ["snapshot", "--help"])
        assert result.exit_code == 0
        assert "Manage database snapshots" in result.output

    def test_snapshot_create_not_implemented(self) -> None:
        """Test snapshot create command (not yet implemented)."""
        result = self.runner.invoke(main, ["snapshot", "create", "test-snapshot"])
        assert result.exit_code == 0
        assert "Snapshot creation not yet implemented" in result.output

    def test_snapshot_create_dry_run(self) -> None:
        """Test snapshot create command with dry-run."""
        result = self.runner.invoke(
            main,
            [
                "--dry-run",
                "snapshot",
                "create",
                "test-snapshot",
                "--description",
                "Test desc",
                "--tags",
                "test,dev",
            ],
        )
        assert result.exit_code == 0
        assert "Would create snapshot 'test-snapshot'" in result.output
        assert "Description: Test desc" in result.output
        assert "Tags: test,dev" in result.output

    def test_snapshot_list_not_implemented(self) -> None:
        """Test snapshot list command (not yet implemented)."""
        result = self.runner.invoke(main, ["snapshot", "list"])
        assert result.exit_code == 0
        assert "Snapshot listing not yet implemented" in result.output

    def test_snapshot_restore_not_implemented(self) -> None:
        """Test snapshot restore command (not yet implemented)."""
        result = self.runner.invoke(main, ["snapshot", "restore", "test-snapshot"])
        assert result.exit_code == 0
        assert "Snapshot restore not yet implemented" in result.output

    def test_snapshot_restore_dry_run(self) -> None:
        """Test snapshot restore command with dry-run."""
        result = self.runner.invoke(
            main, ["--dry-run", "snapshot", "restore", "test-snapshot"]
        )
        assert result.exit_code == 0
        assert "Would restore snapshot 'test-snapshot'" in result.output

    def test_snapshot_restore_with_confirmation(self) -> None:
        """Test snapshot restore with confirmation prompt."""
        # Mock click.confirm to return False (user cancels)
        with patch("click.confirm", return_value=False):
            result = self.runner.invoke(
                main, ["snapshot", "restore", "test-snapshot", "--confirm"]
            )
            assert result.exit_code == 0
            assert "Restore cancelled" in result.output


class TestStatusCommand:
    """Test status command."""

    def setup_method(self) -> None:
        """Set up test method."""
        self.runner = CliRunner()

    def test_status_command(self) -> None:
        """Test status command."""
        result = self.runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "DBranching Status" in result.output
        assert "Configuration file:" in result.output
        assert "Database type:" in result.output
        assert "Storage directory:" in result.output

    def test_status_verbose(self) -> None:
        """Test status command with verbose flag."""
        result = self.runner.invoke(main, ["status", "--verbose"])
        assert result.exit_code == 0
        assert "Database host:" in result.output
        assert "Log level:" in result.output

    def test_status_global_verbose(self) -> None:
        """Test status command with global verbose flag."""
        result = self.runner.invoke(main, ["--verbose", "status"])
        assert result.exit_code == 0
        assert "Database host:" in result.output

    def test_status_with_custom_config(self) -> None:
        """Test status command with custom configuration."""
        config_data = {
            "database": {"type": "mysql", "database": "testdb", "username": "testuser"},
            "storage": {"compression": "bzip2"},
            "logging": {"level": "DEBUG"},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status", "--verbose"]
            )
            assert result.exit_code == 0
            assert "mysql" in result.output
            assert "DEBUG" in result.output
        finally:
            config_path.unlink()


class TestErrorHandling:
    """Test error handling across CLI."""

    def setup_method(self) -> None:
        """Set up test method."""
        self.runner = CliRunner()

    def test_configuration_error_handling(self) -> None:
        """Test configuration error handling."""
        # Create invalid config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("database:\n  type: invalid_type\n")
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--config-file", str(config_path), "status"]
            )
            assert result.exit_code == 2  # ConfigurationError exit code
            assert "Error:" in result.output
        finally:
            config_path.unlink()

    def test_verbose_error_handling(self) -> None:
        """Test verbose error handling shows more details."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: [")
            config_path = Path(f.name)

        try:
            result = self.runner.invoke(
                main, ["--verbose", "--config-file", str(config_path), "status"]
            )
            assert result.exit_code == 2
            assert "Error:" in result.output
        finally:
            config_path.unlink()
