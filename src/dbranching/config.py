"""Configuration management for dbranching application."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .exceptions import ConfigurationError


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    type: Literal["postgresql", "mysql", "sqlite"] = Field(
        default="postgresql", description="Database type"
    )
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    database: str = Field(default="myapp", description="Database name")
    username: str = Field(default="user", description="Database username")
    password_env: str = Field(
        default="DB_PASSWORD", description="Environment variable for password"
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("type")
    @classmethod
    def validate_database_type(cls, v: str) -> str:
        """Validate database type."""
        if v not in ["postgresql", "mysql", "sqlite"]:
            raise ValueError("Database type must be postgresql, mysql, or sqlite")
        return v


class StorageConfig(BaseModel):
    """Storage configuration for snapshots."""

    directory: Path = Field(
        default_factory=lambda: Path.home() / ".dbranching" / "snapshots",
        description="Directory for storing snapshots",
    )
    compression: Literal["none", "gzip", "bzip2", "lzma"] = Field(
        default="gzip", description="Compression method"
    )
    retention_days: int = Field(
        default=30, description="Number of days to retain snapshots"
    )

    @field_validator("retention_days")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        """Validate retention days."""
        if v < 0:
            raise ValueError("Retention days must be non-negative")
        return v

    @field_validator("directory")
    @classmethod
    def validate_directory(cls, v: Union[str, Path]) -> Path:
        """Convert string to Path and validate."""
        if isinstance(v, str):
            v = Path(v)
        return v.expanduser().resolve()


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    format: Literal["structured", "simple", "json"] = Field(
        default="structured", description="Log format"
    )
    file: Optional[Path] = Field(
        default_factory=lambda: Path.home() / ".dbranching" / "logs" / "dbranching.log",
        description="Log file path",
    )

    @field_validator("file")
    @classmethod
    def validate_log_file(cls, v: Optional[Union[str, Path]]) -> Optional[Path]:
        """Convert string to Path and validate."""
        if v is None:
            return None
        if isinstance(v, str):
            v = Path(v)
        return v.expanduser().resolve()


class Config(BaseModel):
    """Main configuration model."""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    model_config = {"validate_assignment": True, "extra": "forbid"}


class ConfigManager:
    """Manages configuration loading, validation, and access."""

    def __init__(
        self,
        config_file: Optional[Path] = None,
        env_prefix: str = "DBRANCHING_",
    ) -> None:
        """Initialize configuration manager.

        Args:
            config_file: Path to configuration file
            env_prefix: Prefix for environment variables
        """
        self.config_file = config_file
        self.env_prefix = env_prefix
        self._config: Optional[Config] = None

    def load_config(self) -> Config:
        """Load and validate configuration from all sources.

        Precedence: CLI args > env vars > config file > defaults

        Returns:
            Validated configuration object

        Raises:
            ConfigurationError: If configuration is invalid
        """
        if self._config is not None:
            return self._config

        # Start with default configuration
        config_data = {}

        # Load from config file
        if self.config_file and self.config_file.exists():
            try:
                config_data = self._load_config_file(self.config_file)
            except Exception as e:
                raise ConfigurationError(
                    f"Failed to load config file: {e}", str(self.config_file)
                )

        # Override with environment variables
        env_overrides = self._load_env_vars()
        config_data = self._merge_configs(config_data, env_overrides)

        # Validate and create config object
        try:
            self._config = Config(**config_data)
        except ValidationError as e:
            errors = []
            for error in e.errors():
                field = " -> ".join(str(loc) for loc in error["loc"])
                errors.append(f"{field}: {error['msg']}")
            raise ConfigurationError(
                "Configuration validation failed:\n" + "\n".join(errors)
            )

        return self._config

    def _load_config_file(self, config_file: Path) -> Dict[str, Any]:
        """Load configuration from file.

        Args:
            config_file: Path to configuration file

        Returns:
            Configuration dictionary

        Raises:
            ConfigurationError: If file cannot be loaded or parsed
        """
        try:
            content = config_file.read_text(encoding="utf-8")
        except Exception as e:
            raise ConfigurationError(f"Cannot read config file: {e}")

        suffix = config_file.suffix.lower()
        try:
            if suffix in [".yaml", ".yml"]:
                data = yaml.safe_load(content) or {}
                return dict(data)  # Ensure it's a dict
            elif suffix == ".json":
                data = json.loads(content)
                return dict(data)
            else:
                raise ConfigurationError(
                    f"Unsupported config file format: {suffix}. "
                    "Supported formats: .yaml, .yml, .json"
                )
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ConfigurationError(f"Invalid {suffix} format: {e}")

    def _load_env_vars(self) -> Dict[str, Any]:
        """Load configuration from environment variables.

        Returns:
            Configuration dictionary with nested structure
        """
        env_config: Dict[str, Any] = {}

        # Map of environment variables to config paths
        env_mappings = {
            f"{self.env_prefix}DATABASE_TYPE": ["database", "type"],
            f"{self.env_prefix}DATABASE_HOST": ["database", "host"],
            f"{self.env_prefix}DATABASE_PORT": ["database", "port"],
            f"{self.env_prefix}DATABASE_NAME": ["database", "database"],
            f"{self.env_prefix}DATABASE_USERNAME": ["database", "username"],
            f"{self.env_prefix}DATABASE_PASSWORD_ENV": ["database", "password_env"],
            f"{self.env_prefix}STORAGE_DIRECTORY": ["storage", "directory"],
            f"{self.env_prefix}STORAGE_COMPRESSION": ["storage", "compression"],
            f"{self.env_prefix}STORAGE_RETENTION_DAYS": ["storage", "retention_days"],
            f"{self.env_prefix}LOG_LEVEL": ["logging", "level"],
            f"{self.env_prefix}LOG_FORMAT": ["logging", "format"],
            f"{self.env_prefix}LOG_FILE": ["logging", "file"],
        }

        for env_var, config_path in env_mappings.items():
            value_str = os.getenv(env_var)
            if value_str is not None:
                # Convert numeric values
                if config_path[-1] in ["port", "retention_days"]:
                    try:
                        value: Union[int, str] = int(value_str)
                    except ValueError:
                        raise ConfigurationError(
                            f"Invalid numeric value for {env_var}: {value_str}"
                        )
                else:
                    value = value_str

                # Set nested value
                current = env_config
                for key in config_path[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                current[config_path[-1]] = value

        return env_config

    def _merge_configs(
        self, base: Dict[str, Any], override: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Recursively merge configuration dictionaries.

        Args:
            base: Base configuration dictionary
            override: Override configuration dictionary

        Returns:
            Merged configuration dictionary
        """
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def get_default_config_paths(self) -> list[Path]:
        """Get default configuration file search paths.

        Returns:
            List of paths to search for configuration files
        """
        return [
            Path.cwd() / "dbranching.yaml",
            Path.cwd() / "dbranching.yml",
            Path.cwd() / "dbranching.json",
            Path.home() / ".dbranching" / "config.yaml",
            Path.home() / ".dbranching" / "config.yml",
            Path.home() / ".dbranching" / "config.json",
        ]

    def find_config_file(self) -> Optional[Path]:
        """Find the first existing configuration file in default locations.

        Returns:
            Path to configuration file, or None if not found
        """
        for path in self.get_default_config_paths():
            if path.exists() and path.is_file():
                return path
        return None

    def create_default_config(self, path: Path) -> None:
        """Create a default configuration file.

        Args:
            path: Path where to create the config file

        Raises:
            ConfigurationError: If file cannot be created
        """
        default_config = Config()

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if path.suffix.lower() in [".yaml", ".yml"]:
                content = yaml.dump(
                    default_config.model_dump(),
                    default_flow_style=False,
                    sort_keys=False,
                )
            elif path.suffix.lower() == ".json":
                # Convert Path objects to strings for JSON serialization
                config_dict = default_config.model_dump(mode="json")
                content = json.dumps(config_dict, indent=2)
            else:
                raise ConfigurationError(f"Unsupported config format: {path.suffix}")

            path.write_text(content, encoding="utf-8")
        except Exception as e:
            raise ConfigurationError(f"Failed to create config file: {e}")
