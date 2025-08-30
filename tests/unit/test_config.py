"""Tests for configuration management."""

import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from dbranching.config import (
    Config,
    ConfigManager,
    DatabaseConfig,
    LoggingConfig,
    StorageConfig,
)
from dbranching.exceptions import ConfigurationError


class TestDatabaseConfig:
    """Test database configuration model."""

    def test_default_config(self) -> None:
        """Test default database configuration."""
        config = DatabaseConfig()
        assert config.driver == "postgresql"
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "myapp"
        assert config.username is None  # Changed to optional
        assert config.password is None  # Changed from password_env

    def test_custom_config(self) -> None:
        """Test custom database configuration."""
        config = DatabaseConfig(
            driver="mysql",
            host="db.example.com",
            port=3306,
            database="myapp",
            username="myuser",
            password="secret",
        )
        assert config.driver == "mysql"
        assert config.host == "db.example.com"
        assert config.port == 3306

    def test_invalid_port(self) -> None:
        """Test validation of invalid port numbers."""
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            DatabaseConfig(port=70000)

        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            DatabaseConfig(port=0)

    def test_invalid_database_type(self) -> None:
        """Test validation of invalid database type."""
        with pytest.raises(ValueError, match="Input should be"):
            DatabaseConfig(driver="oracle")


class TestStorageConfig:
    """Test storage configuration model."""

    def test_default_config(self) -> None:
        """Test default storage configuration."""
        config = StorageConfig()
        assert config.path == Path.home() / ".dbranching" / "snapshots"
        assert config.compression.algorithm == "gzip"  # Now a nested object
        assert config.retention.max_age == "30d"  # Changed structure

    def test_custom_directory(self) -> None:
        """Test custom storage directory."""
        config = StorageConfig(path="/tmp/snapshots")
        assert config.path == Path("/tmp/snapshots")

    def test_home_directory_expansion(self) -> None:
        """Test home directory expansion."""
        config = StorageConfig(path="~/custom/snapshots")
        expected = Path.home() / "custom" / "snapshots"
        assert config.path == expected

    def test_invalid_retention_days(self) -> None:
        """Test validation of negative retention days."""
        with pytest.raises(ValueError, match="max_count must be non-negative"):
            StorageConfig(retention={"max_count": -1})


class TestLoggingConfig:
    """Test logging configuration model."""

    def test_default_config(self) -> None:
        """Test default logging configuration."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.format == "structured"
        assert config.file == Path.home() / ".dbranching" / "logs" / "dbranching.log"

    def test_custom_config(self) -> None:
        """Test custom logging configuration."""
        config = LoggingConfig(
            level="DEBUG",
            format="json",
            file="/var/log/dbranching.log",
        )
        assert config.level == "DEBUG"
        assert config.format == "json"
        assert config.file == Path("/var/log/dbranching.log")

    def test_none_log_file(self) -> None:
        """Test None log file."""
        config = LoggingConfig(file=None)
        assert config.file is None


class TestConfig:
    """Test main configuration model."""

    def test_default_config(self) -> None:
        """Test default configuration."""
        config = Config()
        assert isinstance(config.databases["default"], DatabaseConfig)
        assert isinstance(config.storage, StorageConfig)
        assert isinstance(config.logging, LoggingConfig)

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config_data = {
            "databases": {
                "default": {
                    "driver": "mysql",
                    "database": "myapp",
                    "username": "myuser",
                }
            },
            "storage": {
                "compression": {
                    "algorithm": "bzip2"
                },
                "retention": {
                    "max_age": "7d"
                },
            },
            "logging": {
                "level": "DEBUG",
                "format": "json",
            },
        }
        config = Config(**config_data)
        assert config.databases["default"].driver == "mysql"
        assert config.storage.compression.algorithm == "bzip2"
        assert config.logging.level == "DEBUG"

    def test_validation_error(self) -> None:
        """Test configuration validation error."""
        config_data = {
            "databases": {
                "default": {
                    "driver": "invalid",
                }
            }
        }
        with pytest.raises(ValueError):
            Config(**config_data)


class TestConfigManager:
    """Test configuration manager."""

    def test_init(self) -> None:
        """Test config manager initialization."""
        manager = ConfigManager()
        assert manager.config_file is None
        assert manager.env_prefix == "DBRANCHING_"
        assert manager._config is None

    def test_init_with_config_file(self) -> None:
        """Test config manager with config file."""
        config_path = Path("/path/to/config.yaml")
        manager = ConfigManager(config_file=config_path)
        assert manager.config_file == config_path

    def test_load_default_config(self) -> None:
        """Test loading default configuration."""
        manager = ConfigManager()
        config = manager.load_config()

        assert isinstance(config, Config)
        assert config.databases["default"].driver == "postgresql"
        assert config.storage.compression.algorithm == "gzip"

    def test_load_yaml_config_file(self) -> None:
        """Test loading YAML configuration file."""
        config_data = {
            "databases": {
                "default": {
                    "driver": "mysql",
                    "host": "db.example.com",
                    "database": "myapp",
                    "username": "myuser",
                }
            },
            "storage": {
                "compression": {
                    "algorithm": "bzip2"
                },
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            manager = ConfigManager(config_file=config_path)
            config = manager.load_config()

            assert config.databases["default"].driver == "mysql"
            assert config.databases["default"].host == "db.example.com"
            assert config.storage.compression.algorithm == "bzip2"
        finally:
            config_path.unlink()

    def test_load_json_config_file(self) -> None:
        """Test loading JSON configuration file."""
        config_data = {
            "databases": {
                "default": {
                    "driver": "sqlite",
                    "database": "app.db",
                    "username": "user",
                }
            },
            "logging": {
                "level": "DEBUG",
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            manager = ConfigManager(config_file=config_path)
            config = manager.load_config()

            assert config.databases["default"].driver == "sqlite"
            assert config.logging.level == "DEBUG"
        finally:
            config_path.unlink()

    def test_unsupported_config_format(self) -> None:
        """Test unsupported configuration file format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("invalid config")
            config_path = Path(f.name)

        try:
            manager = ConfigManager(config_file=config_path)
            with pytest.raises(
                ConfigurationError, match="Unsupported config file format"
            ):
                manager.load_config()
        finally:
            config_path.unlink()

    def test_invalid_yaml_config(self) -> None:
        """Test invalid YAML configuration."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            config_path = Path(f.name)

        try:
            manager = ConfigManager(config_file=config_path)
            with pytest.raises(ConfigurationError, match="Invalid .yaml format"):
                manager.load_config()
        finally:
            config_path.unlink()

    def test_invalid_json_config(self) -> None:
        """Test invalid JSON configuration."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"invalid": json}')
            config_path = Path(f.name)

        try:
            manager = ConfigManager(config_file=config_path)
            with pytest.raises(ConfigurationError, match="Invalid .json format"):
                manager.load_config()
        finally:
            config_path.unlink()

    def test_nonexistent_config_file(self) -> None:
        """Test nonexistent configuration file."""
        manager = ConfigManager(config_file=Path("/nonexistent/config.yaml"))
        # Should load default config if file doesn't exist
        config = manager.load_config()
        assert isinstance(config, Config)

    def test_unreadable_config_file(self) -> None:
        """Test unreadable configuration file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("database:\n  type: postgresql\n")
            config_path = Path(f.name)

        try:
            # Remove read permissions
            config_path.chmod(0o000)

            manager = ConfigManager(config_file=config_path)
            with pytest.raises(ConfigurationError, match="Cannot read config file"):
                manager.load_config()
        finally:
            # Restore permissions and cleanup
            config_path.chmod(0o644)
            config_path.unlink()

    def test_environment_variable_overrides(self) -> None:
        """Test environment variable configuration overrides."""
        env_vars = {
            "DBRANCHING_DATABASES_DEFAULT_DRIVER": "mysql",
            "DBRANCHING_DATABASES_DEFAULT_HOST": "env.example.com",
            "DBRANCHING_DATABASES_DEFAULT_PORT": "3306",
            "DBRANCHING_DATABASES_DEFAULT_DATABASE": "envdb",
            "DBRANCHING_DATABASES_DEFAULT_USERNAME": "envuser",
            "DBRANCHING_STORAGE_COMPRESSION_ALGORITHM": "none",
            "DBRANCHING_LOGGING_LEVEL": "DEBUG",
        }

        # Set environment variables
        original_env = {}
        for key, value in env_vars.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            manager = ConfigManager()
            config = manager.load_config()

            assert config.databases["default"].driver == "mysql"
            assert config.databases["default"].host == "env.example.com"
            assert config.databases["default"].port == 3306
            assert config.databases["default"].database == "envdb"
            assert config.databases["default"].username == "envuser"
            assert config.storage.compression.algorithm == "none"
            assert config.logging.level == "DEBUG"

        finally:
            # Restore original environment
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value

    def test_invalid_env_numeric_value(self) -> None:
        """Test invalid numeric environment variable value."""
        os.environ["DBRANCHING_DATABASES_DEFAULT_PORT"] = "invalid"

        try:
            manager = ConfigManager()
            with pytest.raises(ConfigurationError, match="Invalid numeric value"):
                manager.load_config()
        finally:
            os.environ.pop("DBRANCHING_DATABASES_DEFAULT_PORT", None)

    def test_config_validation_error(self) -> None:
        """Test configuration validation error."""
        config_data = {
            "databases": {
                "default": {
                    "driver": "invalid_type",
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)

        try:
            manager = ConfigManager(config_file=config_path)
            with pytest.raises(
                ConfigurationError, match="Configuration validation failed"
            ):
                manager.load_config()
        finally:
            config_path.unlink()

    def test_get_default_config_paths(self) -> None:
        """Test getting default config paths."""
        manager = ConfigManager()
        paths = manager.get_default_config_paths()

        assert isinstance(paths, list)
        assert len(paths) > 0
        assert all(isinstance(p, Path) for p in paths)

        # Check that we have expected paths
        expected_names = [
            "dbranching.yaml",
            "dbranching.yml",
            "dbranching.json",
            "config.yaml",
        ]
        path_names = [p.name for p in paths]
        for name in expected_names:
            assert name in path_names

    def test_find_config_file_none(self) -> None:
        """Test find config file when none exists."""
        manager = ConfigManager()
        found_path = manager.find_config_file()
        assert found_path is None

    def test_find_config_file_exists(self) -> None:
        """Test find config file when one exists."""
        # Create a temporary config file in current directory
        config_path = Path.cwd() / "dbranching.yaml"
        config_path.write_text("database:\n  type: postgresql\n")

        try:
            manager = ConfigManager()
            found_path = manager.find_config_file()
            assert found_path == config_path
        finally:
            if config_path.exists():
                config_path.unlink()

    def test_create_default_config_yaml(self) -> None:
        """Test creating default YAML configuration file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            manager = ConfigManager()
            manager.create_default_config(config_path)

            assert config_path.exists()
            content = config_path.read_text()
            assert "database:" in content
            assert "storage:" in content
            assert "logging:" in content

    def test_create_default_config_json(self) -> None:
        """Test creating default JSON configuration file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            manager = ConfigManager()
            manager.create_default_config(config_path)

            assert config_path.exists()
            content = config_path.read_text()
            config_data = json.loads(content)
            assert "databases" in config_data  # Changed from 'database' to 'databases'
            assert "storage" in config_data
            assert "logging" in config_data

    def test_create_default_config_unsupported_format(self) -> None:
        """Test creating config with unsupported format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.txt"

            manager = ConfigManager()
            with pytest.raises(ConfigurationError, match="Unsupported config format"):
                manager.create_default_config(config_path)

    def test_merge_configs(self) -> None:
        """Test configuration merging."""
        manager = ConfigManager()

        base = {
            "databases": {"default": {"host": "localhost", "port": 5432}},
            "storage": {"compression": {"algorithm": "gzip"}},
        }

        override = {
            "databases": {"default": {"host": "remote.example.com"}},
            "logging": {"level": "DEBUG"},
        }

        result = manager._merge_configs(base, override)

        assert result["databases"]["default"]["host"] == "remote.example.com"  # overridden
        assert result["databases"]["default"]["port"] == 5432  # preserved
        assert result["storage"]["compression"]["algorithm"] == "gzip"  # preserved
        assert result["logging"]["level"] == "DEBUG"  # added
