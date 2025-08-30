"""Configuration management for dbranching application."""

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union, Callable

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .exceptions import ConfigurationError


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    driver: Literal["postgresql", "mysql", "sqlite"] = Field(
        default="postgresql", description="Database driver"
    )
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    database: str = Field(default="myapp", description="Database name")
    username: Optional[str] = Field(default=None, description="Database username")
    password: Optional[str] = Field(default=None, description="Database password (use env vars)")
    ssl_mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = Field(
        default="prefer", description="SSL connection mode"
    )
    pool_size: int = Field(default=10, description="Connection pool size")
    connect_timeout: str = Field(default="30s", description="Connection timeout")
    query_timeout: str = Field(default="60s", description="Query timeout")
    
    # Support for multiple named database configurations
    name: str = Field(default="default", description="Configuration name")

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("driver")
    @classmethod
    def validate_database_driver(cls, v: str) -> str:
        """Validate database driver."""
        if v not in ["postgresql", "mysql", "sqlite"]:
            raise ValueError("Database driver must be postgresql, mysql, or sqlite")
        return v
        
    @field_validator("connect_timeout", "query_timeout")
    @classmethod
    def validate_timeout(cls, v: str) -> str:
        """Validate timeout format (e.g., '30s', '5m', '1h')."""
        if not re.match(r'^\d+[smh]$', v):
            raise ValueError("Timeout must be in format: number followed by s/m/h (e.g., '30s', '5m', '1h')")
        return v
        
    @field_validator("pool_size")
    @classmethod
    def validate_pool_size(cls, v: int) -> int:
        """Validate connection pool size."""
        if not 1 <= v <= 100:
            raise ValueError("Pool size must be between 1 and 100")
        return v


class RetentionPolicyConfig(BaseModel):
    """Retention policy configuration."""
    
    max_age: str = Field(default="30d", description="Maximum age (e.g., '30d', '7d', '90d')")
    max_count: int = Field(default=100, description="Maximum number of snapshots")
    
    @field_validator("max_age")
    @classmethod
    def validate_max_age(cls, v: str) -> str:
        """Validate max_age format."""
        if not re.match(r'^\d+[dwmy]$', v):
            raise ValueError("max_age must be in format: number followed by d/w/m/y (e.g., '30d', '4w', '6m', '1y')")
        return v
        
    @field_validator("max_count")
    @classmethod
    def validate_max_count(cls, v: int) -> int:
        """Validate max_count."""
        if v < 0:
            raise ValueError("max_count must be non-negative")
        return v


class BranchRetentionConfig(BaseModel):
    """Branch-specific retention policy."""
    
    branches: List[str] = Field(description="Branch patterns to match")
    max_age: str = Field(description="Maximum age for matched branches")
    max_count: int = Field(description="Maximum count for matched branches")
    
    @field_validator("max_age")
    @classmethod
    def validate_max_age(cls, v: str) -> str:
        """Validate max_age format."""
        if not re.match(r'^\d+[dwmy]$', v):
            raise ValueError("max_age must be in format: number followed by d/w/m/y (e.g., '30d', '4w', '6m', '1y')")
        return v


class CompressionConfig(BaseModel):
    """Compression configuration."""
    
    algorithm: Literal["none", "gzip", "bzip2", "lzma", "zstd"] = Field(
        default="gzip", description="Compression algorithm"
    )
    level: int = Field(default=6, description="Compression level")
    
    @field_validator("level")
    @classmethod
    def validate_level(cls, v: int) -> int:
        """Validate compression level."""
        if not 0 <= v <= 9:
            raise ValueError("Compression level must be between 0 and 9")
        return v


class StorageConfig(BaseModel):
    """Storage configuration for snapshots."""

    path: Path = Field(
        default_factory=lambda: Path.home() / ".dbranching" / "snapshots",
        description="Directory for storing snapshots",
    )
    compression: CompressionConfig = Field(
        default_factory=CompressionConfig, description="Compression settings"
    )
    retention: RetentionPolicyConfig = Field(
        default_factory=RetentionPolicyConfig, description="Default retention policy"
    )
    patterns: List[BranchRetentionConfig] = Field(
        default_factory=list, description="Branch-specific retention patterns"
    )
    max_size: str = Field(
        default="10GB", description="Maximum total storage size"
    )
    monitoring_threshold: float = Field(
        default=0.8, description="Storage usage warning threshold (0.0-1.0)"
    )

    @field_validator("max_size")
    @classmethod
    def validate_max_size(cls, v: str) -> str:
        """Validate max_size format (e.g., '10GB', '500MB')."""
        if not re.match(r'^\d+(?:\.\d+)?[KMGT]B$', v, re.IGNORECASE):
            raise ValueError("max_size must be in format: number followed by KB/MB/GB/TB (e.g., '10GB', '500MB')")
        return v
        
    @field_validator("monitoring_threshold")
    @classmethod
    def validate_monitoring_threshold(cls, v: float) -> float:
        """Validate monitoring threshold."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Monitoring threshold must be between 0.0 and 1.0")
        return v

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: Union[str, Path]) -> Path:
        """Convert string to Path and validate."""
        if isinstance(v, str):
            # Support environment variable expansion
            v = os.path.expandvars(v)
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
    rotate_size: str = Field(
        default="10MB", description="Log rotation size"
    )
    rotate_count: int = Field(
        default=5, description="Number of rotated log files to keep"
    )
    console: bool = Field(
        default=True, description="Enable console logging"
    )

    @field_validator("file")
    @classmethod
    def validate_log_file(cls, v: Optional[Union[str, Path]]) -> Optional[Path]:
        """Convert string to Path and validate."""
        if v is None:
            return None
        if isinstance(v, str):
            # Support environment variable expansion
            v = os.path.expandvars(v)
            v = Path(v)
        return v.expanduser().resolve()
        
    @field_validator("rotate_size")
    @classmethod
    def validate_rotate_size(cls, v: str) -> str:
        """Validate rotate_size format."""
        if not re.match(r'^\d+(?:\.\d+)?[KMGT]?B$', v, re.IGNORECASE):
            raise ValueError("rotate_size must be in format: number followed by B/KB/MB/GB/TB (e.g., '10MB')")
        return v
        
    @field_validator("rotate_count")
    @classmethod
    def validate_rotate_count(cls, v: int) -> int:
        """Validate rotate_count."""
        if v < 0:
            raise ValueError("rotate_count must be non-negative")
        return v


class GitConfig(BaseModel):
    """Git integration configuration."""
    
    hooks: Dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": True,
            "auto_install": True
        },
        description="Git hooks configuration"
    )
    branches: Dict[str, Any] = Field(
        default_factory=lambda: {
            "auto_snapshot": ["main", "develop"],
            "ignore": ["temp/*", "wip/*"]
        },
        description="Branch-specific settings"
    )


class CLIConfig(BaseModel):
    """CLI behavior configuration."""
    
    output_format: Literal["table", "json", "yaml"] = Field(
        default="table", description="Default output format"
    )
    color: Literal["auto", "always", "never"] = Field(
        default="auto", description="Color output setting"
    )
    progress_bars: bool = Field(
        default=True, description="Enable progress bars"
    )
    confirm_destructive: bool = Field(
        default=True, description="Confirm destructive operations"
    )
    pager: bool = Field(
        default=True, description="Use pager for long output"
    )


class FeatureFlagsConfig(BaseModel):
    """Feature flags for experimental functionality."""
    
    experimental_features: bool = Field(
        default=False, description="Enable experimental features"
    )
    parallel_operations: bool = Field(
        default=True, description="Enable parallel operations"
    )
    hot_reload: bool = Field(
        default=True, description="Enable configuration hot reloading"
    )
    performance_monitoring: bool = Field(
        default=False, description="Enable performance monitoring"
    )


class SecurityConfig(BaseModel):
    """Security settings and access controls."""
    
    encrypt_snapshots: bool = Field(
        default=False, description="Encrypt snapshot files"
    )
    encryption_key_env: str = Field(
        default="DBRANCHING_ENCRYPTION_KEY", description="Environment variable for encryption key"
    )
    config_file_permissions: str = Field(
        default="600", description="Configuration file permissions (octal)"
    )
    audit_logging: bool = Field(
        default=True, description="Enable audit logging"
    )
    
    @field_validator("config_file_permissions")
    @classmethod
    def validate_permissions(cls, v: str) -> str:
        """Validate file permissions format."""
        if not re.match(r'^[0-7]{3,4}$', v):
            raise ValueError("File permissions must be in octal format (e.g., '600', '644')")
        return v


class Config(BaseModel):
    """Main configuration model."""

    version: str = Field(default="1.0", description="Configuration schema version")
    databases: Dict[str, DatabaseConfig] = Field(
        default_factory=lambda: {"default": DatabaseConfig()},
        description="Database configurations"
    )
    storage: StorageConfig = Field(default_factory=StorageConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    cli: CLIConfig = Field(default_factory=CLIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    features: FeatureFlagsConfig = Field(default_factory=FeatureFlagsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    model_config = {"validate_assignment": True, "extra": "forbid"}
    
    @model_validator(mode="after")
    def validate_database_configs(self) -> 'Config':
        """Validate database configurations."""
        if not self.databases:
            raise ValueError("At least one database configuration is required")
        
        # Ensure database names are set correctly
        for name, db_config in self.databases.items():
            db_config.name = name
        
        return self
        
    def get_database(self, name: str = "default") -> DatabaseConfig:
        """Get database configuration by name."""
        if name not in self.databases:
            raise ValueError(f"Database configuration '{name}' not found")
        return self.databases[name]
        
    @property 
    def database(self) -> DatabaseConfig:
        """Get default database configuration for backward compatibility."""
        return self.get_database("default")


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
        self._watcher: Optional[ConfigWatcher] = None

    def load_config(self, force_reload: bool = False) -> Config:
        """Load and validate configuration from all sources.

        Precedence: CLI args > env vars > config file > defaults

        Args:
            force_reload: Force reload even if config is cached

        Returns:
            Validated configuration object

        Raises:
            ConfigurationError: If configuration is invalid
        """
        if self._config is not None and not force_reload:
            return self._config

        # Start with default configuration
        config_data = {}

        # Load from configuration hierarchy 
        if self.config_file:
            # Use explicitly specified config file
            if self.config_file.exists():
                try:
                    config_data = self._load_config_file(self.config_file)
                except Exception as e:
                    raise ConfigurationError(
                        f"Failed to load config file: {e}", str(self.config_file)
                    )
        else:
            # Load from configuration hierarchy
            config_data = self._load_config_hierarchy()

        # Override with environment variables
        env_overrides = self._load_env_vars()
        config_data = self._merge_configs(config_data, env_overrides)
        
        # Apply variable expansion
        config_data = self._expand_variables(config_data)

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
        return self._load_env_vars_dynamic()
        
    def _load_env_vars_dynamic(self) -> Dict[str, Any]:
        """Dynamically load environment variables based on config structure."""
        env_config: Dict[str, Any] = {}
        
        # Get all environment variables with our prefix
        for env_var, value in os.environ.items():
            if not env_var.startswith(self.env_prefix):
                continue
                
            # Remove prefix and convert to config path
            config_path = env_var[len(self.env_prefix):].lower().split('_')
            
            # Convert value to appropriate type
            converted_value = self._convert_env_value(config_path, value)
            
            # Set nested value in config
            current = env_config
            for key in config_path[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            current[config_path[-1]] = converted_value
            
        return env_config
        
    def _convert_env_value(self, config_path: List[str], value: str) -> Any:
        """Convert environment variable value to appropriate type."""
        # Integer fields (specific to certain contexts)
        if config_path[-1] in ['port', 'pool_size', 'max_count', 'rotate_count']:
            try:
                return int(value)
            except ValueError:
                raise ConfigurationError(
                    f"Invalid numeric value for {'.'.join(config_path)}: {value}"
                )
                
        # Compression level is also an integer
        if config_path[-1] == 'level' and len(config_path) > 1 and config_path[-2] == 'compression':
            try:
                return int(value)
            except ValueError:
                raise ConfigurationError(
                    f"Invalid numeric value for {'.'.join(config_path)}: {value}"
                )
        
        # Boolean fields  
        if config_path[-1] in ['enabled', 'auto_install', 'progress_bars', 'confirm_destructive', 
                               'console', 'pager', 'experimental_features', 'parallel_operations',
                               'hot_reload', 'performance_monitoring', 'encrypt_snapshots', 'audit_logging']:
            return value.lower() in ('true', '1', 'yes', 'on')
            
        # Float fields
        if config_path[-1] in ['monitoring_threshold']:
            try:
                return float(value)
            except ValueError:
                raise ConfigurationError(
                    f"Invalid float value for {'.'.join(config_path)}: {value}"
                )
        
        # List fields (comma-separated)
        if config_path[-1] in ['auto_snapshot', 'ignore', 'branches']:
            return [item.strip() for item in value.split(',') if item.strip()]
            
        return value

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
        
    def migrate_config(self, from_version: str, to_version: str) -> bool:
        """Migrate configuration from one version to another.
        
        Args:
            from_version: Source configuration version
            to_version: Target configuration version
            
        Returns:
            True if migration was successful
            
        Raises:
            ConfigurationError: If migration fails
        """
        # For now, only support migration to 1.0
        if to_version != "1.0":
            raise ConfigurationError(f"Migration to version {to_version} not supported")
            
        if from_version == to_version:
            return True  # No migration needed
            
        # Migration logic would go here
        # For now, just validate that the current config works
        try:
            config = self.load_config(force_reload=True)
            return config.version == to_version
        except Exception as e:
            raise ConfigurationError(f"Configuration migration failed: {e}")
            
    def __enter__(self) -> 'ConfigManager':
        """Context manager entry."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.stop_config_watcher()
        
    def get_effective_config_sources(self) -> List[Dict[str, Any]]:
        """Get information about effective configuration sources.
        
        Returns:
            List of configuration sources with their paths and status
        """
        sources = []
        
        # Check system configs
        for path in [Path("/etc/dbranching/config.yaml"), Path("/etc/dbranching/config.yml")]:
            sources.append({
                "path": str(path),
                "level": "system",
                "exists": path.exists(),
                "readable": path.exists() and os.access(path, os.R_OK)
            })
            
        # Check user configs
        user_config_dir = Path.home() / ".config" / "dbranching"
        for path in [user_config_dir / "config.yaml", Path.home() / ".dbranching" / "config.yaml"]:
            sources.append({
                "path": str(path),
                "level": "user", 
                "exists": path.exists(),
                "readable": path.exists() and os.access(path, os.R_OK)
            })
            
        # Check project configs
        for path in [Path.cwd() / ".dbranching.yaml", Path.cwd() / "dbranching.yaml"]:
            sources.append({
                "path": str(path),
                "level": "project",
                "exists": path.exists(),
                "readable": path.exists() and os.access(path, os.R_OK)
            })
            
        # Check environment variables
        env_vars = [var for var in os.environ.keys() if var.startswith(self.env_prefix)]
        if env_vars:
            sources.append({
                "path": "environment variables",
                "level": "environment", 
                "exists": True,
                "readable": True,
                "variables": env_vars
            })
            
        return sources

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
            
    def create_sample_config(self, path: Path) -> None:
        """Create a sample configuration file with comprehensive examples.
        
        Args:
            path: Path where to create the sample config file
            
        Raises:
            ConfigurationError: If file cannot be created
        """
        sample_config = {
            "version": "1.0",
            "databases": {
                "default": {
                    "driver": "postgresql",
                    "host": "localhost",
                    "port": 5432,
                    "database": "myapp_development", 
                    "username": "${DB_USER}",
                    "password": "${DB_PASSWORD}",
                    "ssl_mode": "prefer",
                    "pool_size": 10,
                    "connect_timeout": "30s",
                    "query_timeout": "60s"
                },
                "test": {
                    "driver": "sqlite",
                    "database": "test.db"
                }
            },
            "storage": {
                "path": "${HOME}/.dbranching/snapshots",
                "compression": {
                    "algorithm": "gzip",
                    "level": 6
                },
                "retention": {
                    "max_age": "30d",
                    "max_count": 100
                },
                "patterns": [
                    {
                        "branches": ["main", "master"],
                        "max_age": "90d",
                        "max_count": 50
                    },
                    {
                        "branches": ["feature/*"],
                        "max_age": "7d",
                        "max_count": 10
                    }
                ],
                "max_size": "10GB",
                "monitoring_threshold": 0.8
            },
            "git": {
                "hooks": {
                    "enabled": True,
                    "auto_install": True
                },
                "branches": {
                    "auto_snapshot": ["main", "develop"],
                    "ignore": ["temp/*", "wip/*"]
                }
            },
            "cli": {
                "output_format": "table",
                "color": "auto",
                "progress_bars": True,
                "confirm_destructive": True,
                "pager": True
            },
            "logging": {
                "level": "INFO",
                "format": "structured",
                "file": "${HOME}/.dbranching/logs/dbranching.log",
                "rotate_size": "10MB",
                "rotate_count": 5,
                "console": True
            },
            "features": {
                "experimental_features": False,
                "parallel_operations": True,
                "hot_reload": True,
                "performance_monitoring": False
            },
            "security": {
                "encrypt_snapshots": False,
                "encryption_key_env": "DBRANCHING_ENCRYPTION_KEY",
                "config_file_permissions": "600",
                "audit_logging": True
            }
        }
        
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            if path.suffix.lower() in [".yaml", ".yml"]:
                content = yaml.dump(
                    sample_config,
                    default_flow_style=False,
                    sort_keys=False,
                )
            elif path.suffix.lower() == ".json":
                content = json.dumps(sample_config, indent=2)
            else:
                raise ConfigurationError(f"Unsupported config format: {path.suffix}")
                
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            raise ConfigurationError(f"Failed to create sample config file: {e}")
            
    def get_config_hierarchy(self) -> List[Path]:
        """Get configuration file search paths in hierarchy order.
        
        Returns:
            List of paths in order: system, user, project
        """
        paths = []
        
        # System level configuration
        system_paths = [
            Path("/etc/dbranching/config.yaml"),
            Path("/etc/dbranching/config.yml"),
        ]
        paths.extend(system_paths)
        
        # User level configuration
        user_config_dir = Path.home() / ".config" / "dbranching"
        user_paths = [
            user_config_dir / "config.yaml",
            user_config_dir / "config.yml",
            Path.home() / ".dbranching" / "config.yaml",
            Path.home() / ".dbranching" / "config.yml",
        ]
        paths.extend(user_paths)
        
        # Project level configuration
        project_paths = [
            Path.cwd() / ".dbranching.yaml",
            Path.cwd() / ".dbranching.yml", 
            Path.cwd() / "dbranching.yaml",
            Path.cwd() / "dbranching.yml",
            Path.cwd() / "dbranching.json",
        ]
        paths.extend(project_paths)
        
        return paths

    def _load_config_hierarchy(self) -> Dict[str, Any]:
        """Load configuration from multiple files in hierarchy order."""
        config_data = {}
        config_files = self.get_config_hierarchy()
        
        for config_file in config_files:
            if config_file.exists() and config_file.is_file():
                try:
                    file_config = self._load_config_file(config_file)
                    config_data = self._merge_configs(config_data, file_config)
                except Exception as e:
                    # Log warning but continue with other files
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Failed to load config file {config_file}: {e}"
                    )
                    
        return config_data
        
    def validate_config(self, config: Config) -> List[str]:
        """Validate configuration and return list of validation errors.
        
        Args:
            config: Configuration to validate
            
        Returns:
            List of validation error messages
        """
        errors = []
        
        # Validate database connections
        for name, db_config in config.databases.items():
            errors.extend(self._validate_database_config(name, db_config))
            
        # Validate storage configuration
        errors.extend(self._validate_storage_config(config.storage))
        
        # Validate file permissions
        errors.extend(self._validate_file_permissions(config))
        
        return errors
        
    def _validate_database_config(self, name: str, db_config: DatabaseConfig) -> List[str]:
        """Validate database configuration."""
        errors = []
        
        # Check required fields based on driver
        if db_config.driver != "sqlite":
            if not db_config.username:
                errors.append(f"Database '{name}': username is required for {db_config.driver}")
                
        # Validate SSL mode compatibility
        if db_config.driver == "mysql" and db_config.ssl_mode in ["verify-ca", "verify-full"]:
            errors.append(f"Database '{name}': SSL mode '{db_config.ssl_mode}' not supported for MySQL")
            
        return errors
        
    def _validate_storage_config(self, storage_config: StorageConfig) -> List[str]:
        """Validate storage configuration."""
        errors = []
        
        # Check if storage path is writable
        try:
            storage_config.path.mkdir(parents=True, exist_ok=True)
            # Test write access
            test_file = storage_config.path / ".dbranching_test"
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            errors.append(f"Storage path '{storage_config.path}' is not writable: {e}")
            
        return errors
        
    def _validate_file_permissions(self, config: Config) -> List[str]:
        """Validate file permissions."""
        errors = []
        
        if self.config_file and self.config_file.exists():
            try:
                # Check config file permissions
                stat = self.config_file.stat()
                mode = oct(stat.st_mode)[-3:]
                required_mode = config.security.config_file_permissions
                
                if mode > required_mode:
                    errors.append(
                        f"Configuration file permissions '{mode}' are too permissive. "
                        f"Should be '{required_mode}' or more restrictive."
                    )
            except Exception:
                # Permission check failed, but don't fail validation
                pass
                
        return errors
        
    def hot_reload_config(self) -> Optional[Config]:
        """Reload configuration from files without restart.
        
        Returns:
            New configuration if successful, None if reload failed
        """
        try:
            old_config = self._config
            self._config = None  # Force reload
            new_config = self.load_config()
            
            # Validate new configuration
            validation_errors = self.validate_config(new_config)
            if validation_errors:
                # Rollback to old config
                self._config = old_config
                raise ConfigurationError(
                    "Configuration validation failed during hot reload:\n" + 
                    "\n".join(validation_errors)
                )
                
            return new_config
        except Exception:
            # Restore old config on any error
            if old_config:
                self._config = old_config
            return None
            
    def start_config_watcher(self) -> None:
        """Start watching configuration files for changes."""
        if not self._watcher:
            self._watcher = ConfigWatcher(self)
        self._watcher.start_watching()
        
    def stop_config_watcher(self) -> None:
        """Stop watching configuration files for changes."""
        if self._watcher:
            self._watcher.stop_watching()
            
    def add_config_change_callback(self, callback: Callable[[Config], None]) -> None:
        """Add callback to be called when configuration changes."""
        if not self._watcher:
            self._watcher = ConfigWatcher(self)
        self._watcher.add_callback(callback)
        
    def export_config(self, path: Path, format: str = "yaml", include_defaults: bool = True) -> None:
        """Export current configuration to file.
        
        Args:
            path: Output file path
            format: Export format (yaml, json)
            include_defaults: Whether to include default values
        """
        config = self.load_config()
        
        if include_defaults:
            config_data = config.model_dump()
        else:
            # Only export non-default values (would require more complex logic)
            config_data = config.model_dump()
            
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if format.lower() in ["yaml", "yml"]:
            content = yaml.dump(config_data, default_flow_style=False, sort_keys=False)
            path.write_text(content, encoding="utf-8")
        elif format.lower() == "json":
            content = json.dumps(config_data, indent=2)
            path.write_text(content, encoding="utf-8")
        else:
            raise ConfigurationError(f"Unsupported export format: {format}")
            
    def get_config_value(self, key_path: str) -> Any:
        """Get configuration value by dot notation path.
        
        Args:
            key_path: Dot-separated path (e.g., 'databases.default.host')
            
        Returns:
            Configuration value
            
        Raises:
            ConfigurationError: If key path not found
        """
        config = self.load_config()
        value = config.model_dump()
        
        for key in key_path.split('.'):
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                raise ConfigurationError(f"Configuration key '{key_path}' not found")
                
        return value
        
    def set_config_value(self, key_path: str, value: Any) -> None:
        """Set configuration value by dot notation path.
        
        Note: This method would require implementing configuration file modification,
        which is complex. For now, it raises NotImplementedError.
        """
        raise NotImplementedError(
            "Configuration modification not yet implemented. "
            "Please edit configuration files directly."
        )
        
    def _expand_variables(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Expand environment variables in configuration values.
        
        Args:
            config_data: Configuration dictionary
            
        Returns:
            Configuration dictionary with expanded variables
        """
        def expand_value(value: Any) -> Any:
            if isinstance(value, str):
                return os.path.expandvars(value)
            elif isinstance(value, dict):
                return {k: expand_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [expand_value(item) for item in value]
            return value
            
        return expand_value(config_data)
