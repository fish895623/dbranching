"""Main CLI interface for dbranching application."""

import logging
import sys
from pathlib import Path
from typing import Optional

import click

from .config import Config, ConfigManager
from .exceptions import DBranchingError

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
    """Handle and format errors for user display.

    Args:
        error: Exception to handle
        verbose: Whether to show detailed error information
    """
    logger = logging.getLogger(__name__)

    if isinstance(error, DBranchingError):
        click.echo(f"Error: {error.message}", err=True)
        if verbose:
            logger.exception("Detailed error information")
        sys.exit(error.exit_code)
    else:
        click.echo(f"Unexpected error: {error}", err=True)
        if verbose:
            logger.exception("Unexpected error details")
        sys.exit(1)


@click.group(invoke_without_command=True)
@click.option(
    "--config-file",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be done without executing",
)
@click.pass_context
def main(
    ctx: click.Context,
    config_file: Optional[Path],
    verbose: bool,
    dry_run: bool,
) -> None:
    """Database branching and snapshot management tool.

    dbranching provides tools for creating, managing, and restoring database snapshots
    to enable development workflows similar to git branches but for database state.

    Examples:
      dbranching init                    Initialize dbranching in current directory
      dbranching config list             Show current configuration
      dbranching snapshot create dev     Create snapshot named 'dev'
      dbranching snapshot restore dev    Restore snapshot named 'dev'
      dbranching status                  Show current status
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
    help="Force initialization even if already initialized",
)
@click.pass_context
def init(ctx: click.Context, force: bool) -> None:
    """Initialize dbranching in the current directory.

    This command sets up the necessary directories and creates a default
    configuration file if one doesn't exist.

    Examples:
      dbranching init              Initialize with default settings
      dbranching init --force      Reinitialize existing setup
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
        config.storage.directory.mkdir(parents=True, exist_ok=True)
        if config.logging.file:
            config.logging.file.parent.mkdir(parents=True, exist_ok=True)

        click.echo(f"Initialized dbranching with configuration: {default_config_path}")
        if verbose:
            click.echo(f"Storage directory: {config.storage.directory}")
            click.echo(f"Log file: {config.logging.file}")

    except Exception as e:
        handle_error(e, verbose)


@main.group()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Manage dbranching configuration.

    Commands to view and modify configuration settings.
    """
    pass


@config.command("list")
@click.option(
    "--format",
    type=click.Choice(["yaml", "json", "table"]),
    default="table",
    help="Output format",
)
@click.pass_context
def config_list(ctx: click.Context, format: str) -> None:
    """List current configuration settings.

    Examples:
      dbranching config list              Show config as table
      dbranching config list --format=yaml Show config as YAML
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
            click.echo("Database Configuration:")
            click.echo(f"  Type: {config_obj.database.type}")
            click.echo(f"  Host: {config_obj.database.host}")
            click.echo(f"  Port: {config_obj.database.port}")
            click.echo(f"  Database: {config_obj.database.database}")
            click.echo(f"  Username: {config_obj.database.username}")
            click.echo(f"  Password Environment: {config_obj.database.password_env}")

            click.echo("\nStorage Configuration:")
            click.echo(f"  Directory: {config_obj.storage.directory}")
            click.echo(f"  Compression: {config_obj.storage.compression}")
            click.echo(f"  Retention Days: {config_obj.storage.retention_days}")

            click.echo("\nLogging Configuration:")
            click.echo(f"  Level: {config_obj.logging.level}")
            click.echo(f"  Format: {config_obj.logging.format}")
            click.echo(f"  File: {config_obj.logging.file}")

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

        click.echo("Configuration modification not yet implemented")
        click.echo("Please edit the configuration file directly")

    except Exception as e:
        handle_error(e, verbose)


@main.group()
@click.pass_context
def snapshot(ctx: click.Context) -> None:
    """Manage database snapshots.

    Commands to create, list, and restore database snapshots.
    """
    pass


@snapshot.command("create")
@click.argument("name")
@click.option(
    "--description",
    "-d",
    help="Snapshot description",
)
@click.option(
    "--tags",
    help="Comma-separated list of tags",
)
@click.pass_context
def snapshot_create(
    ctx: click.Context, name: str, description: Optional[str], tags: Optional[str]
) -> None:
    """Create a new database snapshot.

    Args:
        name: Name for the snapshot

    Examples:
      dbranching snapshot create dev-feature
      dbranching snapshot create v1.0 --description "Release version"
      dbranching snapshot create test --tags "testing,feature-x"
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
    help="Show detailed status information",
)
@click.pass_context
def status(ctx: click.Context, verbose: bool) -> None:
    """Show current dbranching status.

    Display information about configuration, database connection,
    available snapshots, and system state.

    Examples:
      dbranching status           Show basic status
      dbranching status --verbose Show detailed status
    """
    global_verbose = ctx.obj["verbose"]
    show_verbose = verbose or global_verbose

    try:
        config_obj = ctx.obj["config"]
        assert config_manager is not None  # Should be set in main()

        click.echo("DBranching Status")
        click.echo("=" * 50)

        # Configuration status
        click.echo(f"Configuration file: {config_manager.config_file or 'Not found'}")
        click.echo(f"Database type: {config_obj.database.type}")
        click.echo(f"Storage directory: {config_obj.storage.directory}")

        if show_verbose:
            click.echo(
                f"Database host: {config_obj.database.host}:{config_obj.database.port}"
            )
            click.echo(f"Database name: {config_obj.database.database}")
            click.echo(f"Log level: {config_obj.logging.level}")
            click.echo(f"Log file: {config_obj.logging.file}")

        # Storage status
        if config_obj.storage.directory.exists():
            click.echo("Storage directory: ✓ exists")
        else:
            click.echo("Storage directory: ✗ does not exist")

        click.echo("\nSnapshot functionality not yet implemented")

    except Exception as e:
        handle_error(e, global_verbose)


if __name__ == "__main__":
    main()
