"""Main CLI interface for dbranching application."""

import logging
import sys
from pathlib import Path
from typing import Optional

import click

from .config import Config, ConfigManager
from .exceptions import DBranchingError, ConfigurationError, DatabaseConnectionError, StorageError

# Global configuration manager instance
config_manager: Optional[ConfigManager] = None


def setup_logging(config: Config) -> None:
    """Set up logging configuration.

    Args:
        config: Configuration object with logging settings
    """
    log_config = config.logging

    # Create log directory if needed
    if log_config.file:
        log_config.file.parent.mkdir(parents=True, exist_ok=True)

    # Configure logging format
    if log_config.format == "json":
        formatter = logging.Formatter(
            fmt=(
                '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
                '"logger": "%(name)s", "message": "%(message)s"}'
            )
        )
    elif log_config.format == "structured":
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:  # simple
        formatter = logging.Formatter("%(levelname)s: %(message)s")

    # Configure handlers
    handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    # File handler
    if log_config.file:
        file_handler = logging.FileHandler(log_config.file)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)  # type: ignore[arg-type]

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_config.level), handlers=handlers, force=True
    )


def handle_error(error: Exception, verbose: bool = False) -> None:
    """Handle and format errors for user display with helpful suggestions.

    Args:
        error: Exception to handle
        verbose: Whether to show detailed error information
    """
    logger = logging.getLogger(__name__)

    if isinstance(error, DBranchingError):
        click.echo(f"Error: {error.message}", err=True)
        
        # Provide helpful suggestions based on error type
        if isinstance(error, ConfigurationError):
            click.echo("\nTroubleshooting:", err=True)
            click.echo("  • Run 'dbranching init' to create default configuration", err=True)
            click.echo("  • Check configuration syntax with 'dbranching config list'", err=True)
            if hasattr(error, 'config_path') and error.config_path:
                click.echo(f"  • Verify file exists and is readable: {error.config_path}", err=True)
        
        elif isinstance(error, DatabaseConnectionError):
            click.echo("\nTroubleshooting:", err=True)
            click.echo("  • Verify database connection settings with 'dbranching config list'", err=True)
            click.echo("  • Check database password environment variable", err=True)
            click.echo("  • Ensure database server is running and accessible", err=True)
            
        elif isinstance(error, StorageError):
            click.echo("\nTroubleshooting:", err=True)
            click.echo("  • Check storage directory permissions", err=True)
            click.echo("  • Verify directory path with 'dbranching config get storage.directory'", err=True)
            click.echo("  • Ensure sufficient disk space available", err=True)
            
        if verbose:
            logger.exception("Detailed error information")
        sys.exit(error.exit_code)
    else:
        click.echo(f"Unexpected error: {error}", err=True)
        click.echo("\nThis appears to be an internal error. Please report it with:", err=True)
        click.echo("  • The command you were running", err=True)
        click.echo("  • Your configuration (dbranching config list)", err=True)
        click.echo("  • The full error output below", err=True)
        if verbose:
            logger.exception("Unexpected error details")
        sys.exit(1)


@click.group(invoke_without_command=True)
@click.option(
    "--config-file",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file (searches default locations if not provided)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output and detailed logging",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be done without executing (preview mode)",
)
@click.pass_context
def main(
    ctx: click.Context,
    config_file: Optional[Path],
    verbose: bool,
    dry_run: bool,
) -> None:
    """Database branching and snapshot management tool.

    DBranching enables database versioning and snapshot management similar to Git
    branches but for database state. Create, restore, and manage database snapshots
    to support development workflows, testing, and rollback scenarios.

    \b
    QUICK START:
      dbranching init                           # Initialize with default config
      dbranching snapshot create feature-x      # Create snapshot
      dbranching snapshot list                  # List all snapshots
      dbranching snapshot restore feature-x     # Restore snapshot

    \b
    CONFIGURATION:
      dbranching config list                    # Show current configuration
      dbranching config get database.host       # Get specific config value
      dbranching status --verbose               # Detailed status information

    \b
    GLOBAL OPTIONS:
      --config-file, -c  Use specific configuration file
      --verbose, -v      Enable detailed output and debug information
      --dry-run          Preview mode - show actions without executing

    \b
    COMMON WORKFLOWS:
      # Feature development
      dbranching snapshot create main           # Create baseline
      # ... develop features ...
      dbranching snapshot create feature/auth   # Save feature state
      dbranching snapshot restore main          # Reset to baseline

      # Testing and validation
      dbranching snapshot list --format=json   # List snapshots with metadata
      dbranching status                         # Check current state

    For detailed command help, use: dbranching COMMAND --help
    For configuration help, see: https://github.com/your-org/dbranching#configuration
    """
    global config_manager

    # Store global options in context
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["dry_run"] = dry_run

    try:
        # Initialize configuration manager
        config_manager = ConfigManager(config_file=config_file)

        # Load configuration if we have commands to run
        if ctx.invoked_subcommand:
            config = config_manager.load_config()
            setup_logging(config)
            ctx.obj["config"] = config

            if verbose:
                logger = logging.getLogger(__name__)
                logger.info(f"Using configuration file: {config_manager.config_file}")
                logger.info("Verbose mode enabled")
                if dry_run:
                    logger.info("Dry-run mode enabled")

    except Exception as e:
        handle_error(e, verbose)

    # Show help if no subcommand provided
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option(
    "--force",
    is_flag=True,
    help="Force initialization even if already initialized (overwrites existing config)",
)
@click.pass_context
def init(ctx: click.Context, force: bool) -> None:
    """Initialize dbranching in the current directory.

    Sets up dbranching for the current project by creating a default configuration
    file and required directories. This command is safe to run multiple times.

    \b
    WHAT THIS DOES:
      • Creates dbranching.yaml configuration file with defaults
      • Creates storage directory for snapshots (~/.dbranching/snapshots)
      • Creates log directory (~/.dbranching/logs)
      • Validates the configuration and tests directory creation

    \b
    EXAMPLES:
      dbranching init                   # Initialize with default settings
      dbranching init --force           # Reinitialize, overwriting existing config

    \b
    AFTER INITIALIZATION:
      • Review configuration: dbranching config list
      • Edit dbranching.yaml to customize settings
      • Set database password: export DB_PASSWORD='your_password'
      • Test connection: dbranching status --verbose

    The default configuration connects to PostgreSQL on localhost.
    Edit dbranching.yaml to change database type, connection details, or storage settings.
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]

    try:
        assert config_manager is not None  # Should be set in main()

        # Check if already initialized
        config_file = config_manager.find_config_file()
        if config_file and not force:
            click.echo(f"Already initialized with config: {config_file}")
            click.echo("Use --force to reinitialize")
            return

        # Create default configuration
        default_config_path = Path.cwd() / "dbranching.yaml"

        if dry_run:
            click.echo(f"Would create configuration file: {default_config_path}")
            return

        config_manager.create_default_config(default_config_path)

        # Load the new config to validate and create directories
        config_manager.config_file = default_config_path
        config = config_manager.load_config()

        # Create storage directories
        config.storage.path.mkdir(parents=True, exist_ok=True)
        if config.logging.file:
            config.logging.file.parent.mkdir(parents=True, exist_ok=True)

        click.echo(f"Initialized dbranching with configuration: {default_config_path}")
        if verbose:
            click.echo(f"Storage directory: {config.storage.path}")
            click.echo(f"Log file: {config.logging.file}")

    except Exception as e:
        handle_error(e, verbose)


@main.group()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Manage dbranching configuration.

    Configuration is loaded from YAML/JSON files in this order:
    1. .dbranching.yaml (current directory) 
    2. ~/.config/dbranching/config.yaml (user config)
    3. /etc/dbranching/config.yaml (system config)
    
    Environment variables can override any setting using DBRANCHING_ prefix.

    \b
    COMMON TASKS:
      dbranching config list                        # Show all configuration
      dbranching config list --format=yaml         # Export as YAML
      dbranching config get databases.default.host # Get specific value
      dbranching config validate                    # Validate configuration
      dbranching config sources                     # Show configuration sources

    \b  
    CONFIGURATION STRUCTURE:
      databases.*    # Database connection settings (multiple databases supported)
      storage.*      # Snapshot storage and retention configuration  
      git.*          # Git integration settings
      cli.*          # CLI behavior and output settings
      logging.*      # Logging configuration
      features.*     # Feature flags
      security.*     # Security settings

    Use 'dbranching config COMMAND --help' for detailed help on each command.
    """
    pass


@config.command("list")
@click.option(
    "--format",
    type=click.Choice(["yaml", "json", "table"]),
    default="table",
    help="Output format for configuration display",
)
@click.pass_context
def config_list(ctx: click.Context, format: str) -> None:
    """Display current configuration settings in various formats.

    Shows the active configuration after merging all sources (files, environment
    variables, defaults). Use this to verify your configuration is loaded correctly.

    \b
    OUTPUT FORMATS:
      table     # Human-readable table format (default)
      yaml      # YAML format suitable for copying to config file
      json      # JSON format for programmatic use

    \b
    EXAMPLES:
      dbranching config list                    # Show formatted table
      dbranching config list --format=yaml     # Export as YAML
      dbranching config list --format=json     # Export as JSON

    \b
    COMMON USE CASES:
      • Verify configuration after changes
      • Export configuration for sharing or backup
      • Debug configuration loading issues
      • Check which values are active from multiple sources

    Passwords and sensitive values are shown as environment variable names,
    not the actual values.
    """
    verbose = ctx.obj["verbose"]
    config_obj = ctx.obj["config"]

    try:
        if format == "yaml":
            import yaml

            click.echo(yaml.dump(config_obj.model_dump(), default_flow_style=False))
        elif format == "json":
            import json

            click.echo(json.dumps(config_obj.model_dump(mode="json"), indent=2))
        else:  # table
            click.echo("Database Configurations:")
            for name, db_config in config_obj.databases.items():
                click.echo(f"  [{name}]:")
                click.echo(f"    Driver: {db_config.driver}")
                click.echo(f"    Host: {db_config.host}")
                click.echo(f"    Port: {db_config.port}")
                click.echo(f"    Database: {db_config.database}")
                click.echo(f"    Username: {db_config.username or 'Not set'}")
                click.echo(f"    SSL Mode: {db_config.ssl_mode}")
                click.echo(f"    Pool Size: {db_config.pool_size}")

            click.echo("\nStorage Configuration:")
            click.echo(f"  Path: {config_obj.storage.path}")
            click.echo(f"  Compression: {config_obj.storage.compression.algorithm} (level {config_obj.storage.compression.level})")
            click.echo(f"  Retention: {config_obj.storage.retention.max_age} / {config_obj.storage.retention.max_count} snapshots")
            click.echo(f"  Max Size: {config_obj.storage.max_size}")
            if config_obj.storage.patterns:
                click.echo(f"  Branch Patterns: {len(config_obj.storage.patterns)} configured")

            click.echo("\nGit Integration:")
            click.echo(f"  Hooks Enabled: {config_obj.git.hooks['enabled']}")
            click.echo(f"  Auto-Install: {config_obj.git.hooks['auto_install']}")
            click.echo(f"  Auto-Snapshot Branches: {', '.join(config_obj.git.branches['auto_snapshot'])}")

            click.echo("\nCLI Configuration:")
            click.echo(f"  Output Format: {config_obj.cli.output_format}")
            click.echo(f"  Color: {config_obj.cli.color}")
            click.echo(f"  Confirm Destructive: {config_obj.cli.confirm_destructive}")

            click.echo("\nLogging Configuration:")
            click.echo(f"  Level: {config_obj.logging.level}")
            click.echo(f"  Format: {config_obj.logging.format}")
            click.echo(f"  File: {config_obj.logging.file}")
            click.echo(f"  Console: {config_obj.logging.console}")

            click.echo("\nFeature Flags:")
            click.echo(f"  Experimental Features: {config_obj.features.experimental_features}")
            click.echo(f"  Parallel Operations: {config_obj.features.parallel_operations}")
            click.echo(f"  Hot Reload: {config_obj.features.hot_reload}")

            click.echo("\nSecurity Settings:")
            click.echo(f"  Encrypt Snapshots: {config_obj.security.encrypt_snapshots}")
            click.echo(f"  Audit Logging: {config_obj.security.audit_logging}")
            click.echo(f"  Config File Permissions: {config_obj.security.config_file_permissions}")

    except Exception as e:
        handle_error(e, verbose)


@config.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx: click.Context, key: str) -> None:
    """Get a specific configuration value.

    Args:
        key: Configuration key in dot notation (e.g., database.host)

    Examples:
      dbranching config get database.host
      dbranching config get logging.level
    """
    verbose = ctx.obj["verbose"]
    config_obj = ctx.obj["config"]

    try:
        # Navigate through nested config
        value = config_obj.model_dump()
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                click.echo(f"Configuration key '{key}' not found", err=True)
                sys.exit(1)

        click.echo(str(value))

    except Exception as e:
        handle_error(e, verbose)


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set a configuration value.

    Args:
        key: Configuration key in dot notation (e.g., database.host)
        value: New value to set

    Examples:
      dbranching config set database.host localhost
      dbranching config set logging.level DEBUG
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]

    try:
        if dry_run:
            click.echo(f"Would set {key} = {value}")
            return

        # For now, delegate to the configuration manager
        assert config_manager is not None
        config_manager.set_config_value(key, value)
        click.echo(f"Set {key} = {value}")

    except NotImplementedError:
        click.echo("Configuration modification not yet implemented")
        click.echo("Please edit the configuration file directly")
    except Exception as e:
        handle_error(e, verbose)


@config.command("validate")
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate the current configuration.
    
    Checks configuration syntax, validates database connections,
    verifies storage paths, and reports any issues.
    
    Examples:
      dbranching config validate
    """
    verbose = ctx.obj["verbose"]
    
    try:
        assert config_manager is not None
        config_obj = ctx.obj["config"]
        
        # Run validation
        errors = config_manager.validate_config(config_obj)
        
        if not errors:
            click.echo("✓ Configuration is valid")
            return
            
        click.echo("Configuration validation errors:")
        for error in errors:
            click.echo(f"  ✗ {error}")
        
        sys.exit(1)
        
    except Exception as e:
        handle_error(e, verbose)


@config.command("sources")
@click.pass_context
def config_sources(ctx: click.Context) -> None:
    """Show configuration file sources and their status.
    
    Displays the configuration hierarchy and which files are loaded.
    
    Examples:
      dbranching config sources
    """
    verbose = ctx.obj["verbose"]
    
    try:
        assert config_manager is not None
        
        sources = config_manager.get_effective_config_sources()
        
        click.echo("Configuration Sources (in load order):")
        for source in sources:
            status = "✓ loaded" if source["exists"] and source["readable"] else "✗ not found"
            click.echo(f"  {source['level'].upper():>7}: {source['path']} ({status})")
            
            if 'variables' in source:
                click.echo(f"           Environment variables: {len(source['variables'])}")
                if verbose:
                    for var in sorted(source['variables']):
                        click.echo(f"             {var}")
        
    except Exception as e:
        handle_error(e, verbose)


@config.command("sample")
@click.argument("path", type=click.Path(path_type=Path))
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing file",
)
@click.pass_context
def config_sample(ctx: click.Context, path: Path, force: bool) -> None:
    """Create a sample configuration file with all options.
    
    Args:
        path: Path where to create the sample configuration
        
    Examples:
      dbranching config sample sample-config.yaml
      dbranching config sample ~/.dbranching/config.yaml --force
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]
    
    try:
        if path.exists() and not force:
            click.echo(f"File already exists: {path}")
            click.echo("Use --force to overwrite")
            return
            
        if dry_run:
            click.echo(f"Would create sample configuration: {path}")
            return
            
        assert config_manager is not None
        config_manager.create_sample_config(path)
        
        click.echo(f"Created sample configuration: {path}")
        if verbose:
            click.echo(f"Edit this file to customize your configuration, then copy to:")
            click.echo(f"  Project: .dbranching.yaml")
            click.echo(f"  User:    ~/.config/dbranching/config.yaml")
        
    except Exception as e:
        handle_error(e, verbose)


@config.command("export")
@click.argument("path", type=click.Path(path_type=Path))
@click.option(
    "--format", 
    type=click.Choice(["yaml", "json"]),
    default="yaml",
    help="Export format"
)
@click.option(
    "--include-defaults",
    is_flag=True,
    default=True,
    help="Include default values in export"
)
@click.pass_context
def config_export(ctx: click.Context, path: Path, format: str, include_defaults: bool) -> None:
    """Export current configuration to a file.
    
    Args:
        path: Output file path
        
    Examples:
      dbranching config export my-config.yaml
      dbranching config export backup.json --format=json
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]
    
    try:
        if dry_run:
            click.echo(f"Would export configuration to: {path}")
            return
            
        assert config_manager is not None
        config_manager.export_config(path, format, include_defaults)
        
        click.echo(f"Exported configuration to: {path}")
        
    except Exception as e:
        handle_error(e, verbose)


@main.group()
@click.pass_context
def snapshot(ctx: click.Context) -> None:
    """Manage database snapshots for development workflows.

    Database snapshots capture the complete state of your database at a point in time,
    similar to Git commits but for database content. Use snapshots to save states
    before making changes, experiment safely, and restore to known-good states.

    \b
    TYPICAL WORKFLOW:
      dbranching snapshot create baseline       # Save current state
      # ... make database changes ...
      dbranching snapshot create feature-x      # Save feature state
      dbranching snapshot restore baseline      # Reset to start
      dbranching snapshot restore feature-x     # Back to feature

    \b
    SNAPSHOT FEATURES:
      • Full database content capture
      • Metadata: descriptions, tags, timestamps
      • Compressed storage with multiple algorithms
      • Automatic cleanup based on retention policies
      • Fast restore operations

    \b
    COMMON COMMANDS:
      dbranching snapshot create <name>         # Create new snapshot
      dbranching snapshot list                  # Show all snapshots
      dbranching snapshot restore <name>        # Restore snapshot
      
    Use 'dbranching snapshot COMMAND --help' for detailed help on each command.
    Note: Snapshot functionality requires database connection to be configured.
    """
    pass


@snapshot.command("create")
@click.argument("name")
@click.option(
    "--description",
    "-d",
    help="Human-readable description of the snapshot purpose",
)
@click.option(
    "--tags",
    help="Comma-separated list of tags for organization (e.g., 'feature,testing')",
)
@click.pass_context
def snapshot_create(
    ctx: click.Context, name: str, description: Optional[str], tags: Optional[str]
) -> None:
    """Create a new database snapshot from current database state.

    Captures the complete current state of the database including all tables, data,
    indexes, and schema. The snapshot is compressed and stored in the configured
    storage directory with metadata for later restoration.

    \b
    SNAPSHOT NAMING:
      • Use descriptive names like 'feature-auth' or 'before-migration'
      • Names must be unique (existing snapshots cannot be overwritten)
      • Avoid spaces or special characters (use hyphens or underscores)
      • Consider using date prefixes: '2024-01-15-baseline'

    \b
    EXAMPLES:
      # Basic snapshot
      dbranching snapshot create dev-baseline

      # With description  
      dbranching snapshot create feature-auth --description "User authentication complete"

      # With tags for organization
      dbranching snapshot create test-data --tags "testing,sample-data" --description "Test dataset v1"

      # Before dangerous operation
      dbranching snapshot create before-migration --description "Before schema migration"

    \b
    WHAT GETS CAPTURED:
      • All table data and structure
      • Database schema (tables, indexes, constraints)
      • User-defined functions and procedures
      • Views and materialized views
      • Permissions and roles (database-specific)

    The snapshot will be compressed using the configured compression method
    and stored with timestamp and metadata for tracking.
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]

    try:
        if dry_run:
            click.echo(f"Would create snapshot '{name}'")
            if description:
                click.echo(f"  Description: {description}")
            if tags:
                click.echo(f"  Tags: {tags}")
            return

        click.echo("Snapshot creation not yet implemented")

    except Exception as e:
        handle_error(e, verbose)


@snapshot.command("list")
@click.option(
    "--filter",
    help="Filter snapshots by name or tag pattern",
)
@click.option(
    "--format",
    type=click.Choice(["table", "json", "simple"]),
    default="table",
    help="Output format",
)
@click.pass_context
def snapshot_list(ctx: click.Context, filter: Optional[str], format: str) -> None:
    """List available snapshots.

    Examples:
      dbranching snapshot list
      dbranching snapshot list --filter "dev*"
      dbranching snapshot list --format json
    """
    verbose = ctx.obj["verbose"]

    try:
        click.echo("Snapshot listing not yet implemented")

    except Exception as e:
        handle_error(e, verbose)


@snapshot.command("restore")
@click.argument("name")
@click.option(
    "--force",
    is_flag=True,
    help="Force restore without confirmation",
)
@click.option(
    "--confirm",
    is_flag=True,
    help="Prompt for confirmation before restoring",
)
@click.pass_context
def snapshot_restore(ctx: click.Context, name: str, force: bool, confirm: bool) -> None:
    """Restore a database snapshot.

    Args:
        name: Name of the snapshot to restore

    Examples:
      dbranching snapshot restore dev-feature
      dbranching snapshot restore v1.0 --force
      dbranching snapshot restore test --confirm
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]

    try:
        if dry_run:
            click.echo(f"Would restore snapshot '{name}'")
            return

        if confirm and not force:
            if not click.confirm(
                f"Restore snapshot '{name}'? This will overwrite current data."
            ):
                click.echo("Restore cancelled")
                return

        click.echo("Snapshot restore not yet implemented")

    except Exception as e:
        handle_error(e, verbose)


@main.command()
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed status including connection test and storage details",
)
@click.pass_context
def status(ctx: click.Context, verbose: bool) -> None:
    """Display comprehensive dbranching system status.

    Shows the current state of dbranching including configuration status, database
    connectivity, storage health, and snapshot statistics. Use this command to
    verify your setup and troubleshoot issues.

    \b
    BASIC STATUS INCLUDES:
      • Configuration file location and validity
      • Database type and connection parameters
      • Storage directory status and permissions
      • Quick snapshot count

    \b
    VERBOSE STATUS ADDS:
      • Database connection test results
      • Detailed storage and logging configuration  
      • Storage directory size and available space
      • Recent snapshot activity
      • System health indicators

    \b
    EXAMPLES:
      dbranching status                    # Quick status check
      dbranching status --verbose          # Full diagnostic information
      dbranching status -v                 # Same as --verbose

    \b
    TROUBLESHOOTING:
      Use verbose mode to diagnose:
      • Database connection issues
      • Configuration loading problems
      • Storage permission issues
      • Missing directories or files

    This command is safe to run at any time and never modifies your system.
    """
    global_verbose = ctx.obj["verbose"]
    show_verbose = verbose or global_verbose

    try:
        config_obj = ctx.obj["config"]
        assert config_manager is not None  # Should be set in main()

        click.echo("DBranching Status")
        click.echo("=" * 50)

        # Configuration status
        config_file = config_manager.find_config_file()
        click.echo(f"Configuration file: {config_file or 'Not found (using defaults)'}")
        
        # Show primary database info
        default_db = config_obj.database
        click.echo(f"Database driver: {default_db.driver}")
        click.echo(f"Database host: {default_db.host}:{default_db.port}")
        click.echo(f"Storage directory: {config_obj.storage.path}")

        if show_verbose:
            click.echo(f"Database name: {default_db.database}")
            click.echo(f"Database username: {default_db.username or 'Not set'}")
            click.echo(f"Database SSL mode: {default_db.ssl_mode}")
            click.echo(f"Database pool size: {default_db.pool_size}")
            
            # Show all databases if multiple
            if len(config_obj.databases) > 1:
                click.echo(f"Additional databases: {', '.join(name for name in config_obj.databases.keys() if name != 'default')}")
            
            click.echo(f"Storage compression: {config_obj.storage.compression.algorithm}")
            click.echo(f"Storage retention: {config_obj.storage.retention.max_age}")
            click.echo(f"Git hooks enabled: {config_obj.git.hooks['enabled']}")
            click.echo(f"Log level: {config_obj.logging.level}")
            click.echo(f"Log file: {config_obj.logging.file}")
            click.echo(f"CLI output format: {config_obj.cli.output_format}")

        # Storage status
        if config_obj.storage.path.exists():
            click.echo("Storage directory: ✓ exists")
        else:
            click.echo("Storage directory: ✗ does not exist")

        click.echo("\nSnapshot functionality not yet implemented")

    except Exception as e:
        handle_error(e, global_verbose)


@main.group()
@click.pass_context
def hook(ctx: click.Context) -> None:
    """Manage Git hook integration for automatic database snapshots.

    Git hooks enable automatic snapshot creation during Git operations like branch
    switches and merges. This provides seamless workflow integration without manual
    snapshot management.

    \b
    HOOK TYPES:
      post-checkout    # Triggers on branch switches and new branch creation
      post-merge       # Triggers on merge operations and conflict resolution

    \b
    INTEGRATION FEATURES:
      • Automatic snapshot creation on configured branch operations
      • Non-disruptive: Git operations never fail due to hook errors
      • Hook chaining: Preserves existing hooks through wrapper pattern
      • Safe installation/uninstallation with automatic backups
      • Performance optimized to minimize Git workflow impact

    \b
    COMMON COMMANDS:
      dbranching hook install                   # Install hooks with auto-detection
      dbranching hook status                    # Check hook installation status
      dbranching hook uninstall                 # Remove hooks and restore originals
      dbranching hook test                      # Test hook integration

    \b
    CONFIGURATION:
      Configure hook behavior in dbranching.yaml:
      • git.hooks.enabled: Enable/disable hook integration
      • git.hooks.auto_install: Install hooks automatically during init
      • git.branches.auto_snapshot: Branch patterns that trigger snapshots
      • git.branches.ignore: Branch patterns to ignore

    Use 'dbranching hook COMMAND --help' for detailed help on each command.
    """
    pass


@hook.command("install")
@click.option(
    "--force",
    is_flag=True,
    help="Force installation even if hooks already exist",
)
@click.pass_context
def hook_install(ctx: click.Context, force: bool) -> None:
    """Install Git hooks for automatic database snapshots.

    Installs post-checkout and post-merge hooks that automatically create database
    snapshots during Git operations. Existing hooks are preserved through a wrapper
    pattern that chains the original hook with dbranching functionality.

    \b
    WHAT THIS DOES:
      • Backs up existing hooks to .dbranching-original files  
      • Installs wrapper hooks that chain original + dbranching functionality
      • Sets proper executable permissions and validates installation
      • Tests hook integration without triggering operations

    \b
    SAFETY FEATURES:
      • Atomic installation: All hooks installed or none (rollback on failure)
      • Automatic backups: Original hooks preserved and restorable
      • Non-destructive: Original hooks executed first, then dbranching
      • Validation: Hooks tested before activation

    \b
    EXAMPLES:
      dbranching hook install                   # Install hooks with validation
      dbranching hook install --force           # Force reinstall existing hooks

    \b
    AFTER INSTALLATION:
      • Git operations on configured branches will create snapshots automatically
      • Check status: dbranching hook status
      • Test integration: dbranching hook test
      • View logs: Check configured log directory for hook execution details

    Hook installation requires write access to .git/hooks/ directory.
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]

    try:
        if dry_run:
            click.echo("Would install Git hooks:")
            click.echo("  • post-checkout hook for branch operations")
            click.echo("  • post-merge hook for merge operations")
            return

        config_obj = ctx.obj["config"]

        # Check if hooks are enabled
        if not config_obj.git.hooks.get("enabled", True):
            click.echo("Git hooks are disabled in configuration")
            click.echo("Enable with: dbranching config set git.hooks.enabled true")
            return

        # Import here to avoid circular imports
        from .git import GitHookManager

        # Initialize hook manager
        hook_manager = GitHookManager(config_obj)

        # Install hooks
        import asyncio
        results = asyncio.run(hook_manager.install_hooks(force))

        # Report results
        successful = sum(1 for success in results.values() if success)
        total = len(results)

        if successful == total:
            click.echo(f"✓ Successfully installed {successful} Git hooks")
            if verbose:
                for hook_name, success in results.items():
                    status = "✓ installed" if success else "⚠ skipped"
                    click.echo(f"  {hook_name}: {status}")
        else:
            click.echo(f"⚠ Partially installed: {successful}/{total} hooks")
            for hook_name, success in results.items():
                status = "✓ installed" if success else "✗ failed"
                click.echo(f"  {hook_name}: {status}")

    except Exception as e:
        handle_error(e, verbose)


@hook.command("uninstall") 
@click.option(
    "--confirm",
    is_flag=True,
    help="Confirm uninstallation without prompting",
)
@click.pass_context
def hook_uninstall(ctx: click.Context, confirm: bool) -> None:
    """Uninstall Git hooks and restore original hooks.

    Removes dbranching Git hooks and restores any original hooks that were
    backed up during installation. This safely reverts the repository to
    its pre-dbranching hook state.

    \b
    WHAT THIS DOES:
      • Removes dbranching hook wrapper scripts
      • Restores original hooks from .dbranching-original backups
      • Validates successful restoration
      • Cleans up backup files

    \b
    SAFETY FEATURES:
      • Preserves original hook functionality
      • No data loss: Only removes dbranching-specific hooks
      • Validation: Ensures original hooks are properly restored

    \b
    EXAMPLES:
      dbranching hook uninstall                 # Uninstall with confirmation prompt
      dbranching hook uninstall --confirm       # Uninstall without prompting

    This operation is safe and can be reversed by reinstalling hooks.
    """
    verbose = ctx.obj["verbose"]
    dry_run = ctx.obj["dry_run"]

    try:
        if not confirm and not dry_run:
            if not click.confirm("Uninstall Git hooks and restore originals?"):
                click.echo("Uninstall cancelled")
                return

        if dry_run:
            click.echo("Would uninstall Git hooks:")
            click.echo("  • Remove post-checkout hook")
            click.echo("  • Remove post-merge hook") 
            click.echo("  • Restore original hooks if present")
            return

        config_obj = ctx.obj["config"]

        # Import here to avoid circular imports
        from .git import GitHookManager

        # Initialize hook manager
        hook_manager = GitHookManager(config_obj)

        # Uninstall hooks
        import asyncio
        results = asyncio.run(hook_manager.uninstall_hooks())

        # Report results
        successful = sum(1 for success in results.values() if success)
        total = len(results)

        if successful == total:
            click.echo(f"✓ Successfully uninstalled {successful} Git hooks")
            if verbose:
                for hook_name, success in results.items():
                    status = "✓ uninstalled" if success else "⚠ not installed"
                    click.echo(f"  {hook_name}: {status}")
        else:
            click.echo(f"⚠ Partially uninstalled: {successful}/{total} hooks")
            for hook_name, success in results.items():
                status = "✓ uninstalled" if success else "✗ failed"
                click.echo(f"  {hook_name}: {status}")

    except Exception as e:
        handle_error(e, verbose)


@hook.command("status")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed status including file sizes and timestamps",
)
@click.pass_context
def hook_status(ctx: click.Context, verbose_flag: bool) -> None:
    """Display Git hook installation and configuration status.

    Shows the current state of dbranching Git hooks including installation status,
    configuration settings, and repository information. Use this to verify hook
    installation and troubleshoot integration issues.

    \b
    BASIC STATUS:
      • Hook installation status (installed/not installed)
      • Hook type verification (dbranching/original/other)
      • Configuration settings (enabled/disabled, branch patterns)
      • Repository information (current branch, clean/dirty state)

    \b
    VERBOSE STATUS ADDS:
      • Hook file details (size, modification time, permissions)
      • Full configuration dump for Git integration settings
      • Repository details (remote URL, commit hash)
      • Backup status and restoration capability

    \b
    EXAMPLES:
      dbranching hook status                    # Basic status overview
      dbranching hook status --verbose          # Detailed status information
      dbranching hook status -v                 # Same as --verbose

    This command never modifies the repository and is safe to run at any time.
    """
    global_verbose = ctx.obj["verbose"]
    show_verbose = verbose_flag or global_verbose

    try:
        config_obj = ctx.obj["config"]

        # Import here to avoid circular imports
        from .git import GitHookManager

        # Initialize hook manager  
        hook_manager = GitHookManager(config_obj)

        # Get hook status
        status = hook_manager.get_hook_status()

        # Display status
        click.echo("Git Hook Status")
        click.echo("=" * 50)

        # Configuration status
        hooks_enabled = config_obj.git.hooks.get("enabled", True)
        click.echo(f"Configuration: {'✓ enabled' if hooks_enabled else '✗ disabled'}")

        if not hooks_enabled:
            click.echo("  Git hooks are disabled in configuration")
            return

        # Hook installation status
        installed_count = sum(1 for info in status.values() if info["installed"] and info["is_dbranching_hook"])
        total_hooks = len(status)

        click.echo(f"Hook installation: {installed_count}/{total_hooks} hooks installed")

        for hook_name, info in status.items():
            if info["installed"] and info["is_dbranching_hook"]:
                status_icon = "✓"
                status_text = "installed"
            elif info["installed"]:
                status_icon = "⚠"
                status_text = "other hook present"
            else:
                status_icon = "✗"
                status_text = "not installed"

            click.echo(f"  {hook_name}: {status_icon} {status_text}")

            if show_verbose and info["installed"]:
                click.echo(f"    Path: {info['path']}")
                click.echo(f"    Size: {info['size']} bytes")
                click.echo(f"    Executable: {'yes' if info['executable'] else 'no'}")
                click.echo(f"    Has backup: {'yes' if info['has_original_backup'] else 'no'}")

        # Configuration details
        if show_verbose:
            click.echo("\nConfiguration Details:")
            auto_branches = config_obj.git.branches.get("auto_snapshot", [])
            ignore_patterns = config_obj.git.branches.get("ignore", [])
            
            click.echo(f"  Auto-snapshot branches: {', '.join(auto_branches) if auto_branches else 'none'}")
            click.echo(f"  Ignore patterns: {', '.join(ignore_patterns) if ignore_patterns else 'none'}")

        # Repository information
        try:
            repo_info = hook_manager.branch_detector.get_repository_info()
            click.echo(f"\nRepository: {repo_info['repo_path']}")
            click.echo(f"  Current branch: {repo_info['current_branch'] or 'detached HEAD'}")
            
            if show_verbose:
                click.echo(f"  Current commit: {repo_info['current_commit'][:8] if repo_info['current_commit'] else 'none'}")
                click.echo(f"  Working directory: {'dirty' if repo_info['is_dirty'] else 'clean'}")
                if repo_info['remote_url']:
                    click.echo(f"  Remote URL: {repo_info['remote_url']}")

        except Exception as e:
            click.echo(f"  Repository info unavailable: {e}")

    except Exception as e:
        handle_error(e, global_verbose)


@hook.command("test")
@click.pass_context
def hook_test(ctx: click.Context) -> None:
    """Test Git hook integration without triggering operations.

    Validates Git hook installation and integration with the snapshot engine
    without actually creating snapshots or modifying the repository. Use this
    to verify that hooks are properly installed and configured.

    \b
    WHAT THIS TESTS:
      • Hook installation and executable permissions
      • Repository access and branch detection capability
      • Snapshot engine initialization and configuration
      • Configuration validation for Git integration
      • File system access for hook logging

    \b
    TEST RESULTS:
      ✓ Pass: Component is working correctly
      ✗ Fail: Component has issues that need attention
      ⚠ Warn: Component works but has non-critical issues

    \b
    EXAMPLES:
      dbranching hook test                      # Run all integration tests

    This command is safe and never modifies the repository or creates snapshots.
    Use it after installation to verify everything is working correctly.
    """
    verbose = ctx.obj["verbose"]

    try:
        config_obj = ctx.obj["config"]

        # Import here to avoid circular imports
        from .git import GitHookManager

        # Initialize hook manager
        hook_manager = GitHookManager(config_obj)

        # Run integration tests
        import asyncio
        test_results = asyncio.run(hook_manager.test_hook_integration())

        # Display results
        click.echo("Git Hook Integration Test")
        click.echo("=" * 50)

        # Hook status
        hook_status = test_results["hook_status"]
        installed_hooks = sum(1 for info in hook_status.values() 
                            if info["installed"] and info["is_dbranching_hook"])
        
        if installed_hooks > 0:
            click.echo(f"✓ Hooks installed: {installed_hooks} hooks active")
        else:
            click.echo("⚠ Hooks not installed: No active dbranching hooks")

        # Test results
        tests = test_results["tests"]
        
        if tests.get("repository_access"):
            click.echo("✓ Repository access: Working correctly")
        else:
            click.echo(f"✗ Repository access: {tests.get('repository_error', 'Failed')}")

        if tests.get("snapshot_engine"):
            click.echo("✓ Snapshot engine: Initialization successful")
        else:
            click.echo(f"✗ Snapshot engine: {tests.get('snapshot_error', 'Failed')}")

        # Configuration
        config_info = test_results["configuration"]
        if config_info["hooks_enabled"]:
            click.echo("✓ Configuration: Hooks enabled")
        else:
            click.echo("⚠ Configuration: Hooks disabled")

        # Branch patterns
        auto_branches = config_info["auto_snapshot_branches"]
        if auto_branches:
            click.echo(f"✓ Auto-snapshot branches: {', '.join(auto_branches)}")
        else:
            click.echo("⚠ Auto-snapshot branches: No patterns configured")

        if verbose:
            # Repository details
            repo_info = test_results.get("repository_info", {})
            if repo_info:
                click.echo(f"\nRepository Details:")
                click.echo(f"  Path: {repo_info.get('repo_path', 'Unknown')}")
                click.echo(f"  Branch: {repo_info.get('current_branch', 'Unknown')}")
                click.echo(f"  Clean: {not repo_info.get('is_dirty', True)}")

    except Exception as e:
        handle_error(e, verbose)


@hook.command("post-checkout")
@click.argument("previous_ref")
@click.argument("current_ref") 
@click.argument("branch_flag")
@click.pass_context
def hook_post_checkout(ctx: click.Context, previous_ref: str, current_ref: str, branch_flag: str) -> None:
    """Handle post-checkout hook execution (called by Git).
    
    This command is called automatically by Git during checkout operations.
    It should not be run manually unless testing hook functionality.

    Args:
        previous_ref: Previous HEAD reference
        current_ref: New HEAD reference
        branch_flag: "1" for branch checkout, "0" for file checkout
    """
    try:
        config_obj = ctx.obj["config"]

        # Import here to avoid circular imports
        from .git import GitHookManager

        # Initialize hook manager
        hook_manager = GitHookManager(config_obj)

        # Handle post-checkout
        import asyncio
        exit_code = asyncio.run(hook_manager.handle_post_checkout(
            previous_ref, current_ref, branch_flag
        ))

        sys.exit(exit_code)

    except Exception as e:
        # Hook errors should not fail Git operations
        logger = logging.getLogger(__name__)
        logger.error(f"Post-checkout hook error: {e}")
        sys.exit(0)


@hook.command("post-merge")
@click.argument("merge_commit", default="HEAD")
@click.pass_context
def hook_post_merge(ctx: click.Context, merge_commit: str) -> None:
    """Handle post-merge hook execution (called by Git).
    
    This command is called automatically by Git during merge operations.
    It should not be run manually unless testing hook functionality.

    Args:
        merge_commit: Merge commit reference (defaults to HEAD)
    """
    try:
        config_obj = ctx.obj["config"]

        # Import here to avoid circular imports
        from .git import GitHookManager

        # Initialize hook manager
        hook_manager = GitHookManager(config_obj)

        # Handle post-merge
        import asyncio
        exit_code = asyncio.run(hook_manager.handle_post_merge(merge_commit))

        sys.exit(exit_code)

    except Exception as e:
        # Hook errors should not fail Git operations
        logger = logging.getLogger(__name__)
        logger.error(f"Post-merge hook error: {e}")
        sys.exit(0)


if __name__ == "__main__":
    main()
