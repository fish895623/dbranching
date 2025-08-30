# CLI Reference

Complete reference for all DBranching command-line interface commands, options, and usage patterns.

## Global Options

These options are available for all commands:

### `--config-file`, `-c`
**Type:** Path  
**Description:** Path to configuration file (searches default locations if not provided)

```bash
dbranching --config-file /path/to/config.yaml status
dbranching -c ./custom-config.yaml snapshot list
```

### `--verbose`, `-v`
**Type:** Flag  
**Description:** Enable verbose output and detailed logging

```bash
dbranching --verbose status
dbranching -v snapshot create test
```

### `--dry-run`
**Type:** Flag  
**Description:** Show what would be done without executing (preview mode)

```bash
dbranching --dry-run init
dbranching --dry-run snapshot create test-snapshot
```

### `--help`
**Type:** Flag  
**Description:** Show help message and exit

```bash
dbranching --help
dbranching config --help
dbranching snapshot create --help
```

## Commands

### `dbranching`
**Usage:** `dbranching [GLOBAL_OPTIONS] [COMMAND]`  
**Description:** Main entry point for DBranching CLI

When run without a command, shows help information and usage examples.

**Examples:**
```bash
# Show main help
dbranching

# Show help for specific command
dbranching snapshot --help
```

---

## `init` - Initialize DBranching

**Usage:** `dbranching init [OPTIONS]`  
**Description:** Initialize dbranching in the current directory

Sets up dbranching for the current project by creating a default configuration file and required directories.

### Options

#### `--force`
**Type:** Flag  
**Description:** Force initialization even if already initialized (overwrites existing config)

### What This Command Does

- Creates `dbranching.yaml` configuration file with defaults
- Creates storage directory for snapshots (`~/.dbranching/snapshots`)
- Creates log directory (`~/.dbranching/logs`)
- Validates the configuration and tests directory creation

### Examples

```bash
# Initialize with default settings
dbranching init

# Reinitialize, overwriting existing config
dbranching init --force

# Preview what would be created
dbranching --dry-run init

# Initialize with verbose output
dbranching --verbose init
```

### After Initialization

1. Review configuration: `dbranching config list`
2. Edit `dbranching.yaml` to customize settings
3. Set database password: `export DB_PASSWORD='your_password'`
4. Test connection: `dbranching status --verbose`

---

## `config` - Configuration Management

**Usage:** `dbranching config COMMAND [OPTIONS]`  
**Description:** Manage dbranching configuration

Configuration is loaded from YAML/JSON files and can be overridden with environment variables using the `DBRANCHING_` prefix.

### Configuration Structure

- `database.*` - Database connection settings
- `storage.*` - Snapshot storage configuration  
- `logging.*` - Logging and output settings

---

### `config list` - Display Configuration

**Usage:** `dbranching config list [OPTIONS]`  
**Description:** Display current configuration settings in various formats

Shows the active configuration after merging all sources (files, environment variables, defaults).

#### Options

##### `--format`
**Type:** Choice [`yaml`, `json`, `table`]  
**Default:** `table`  
**Description:** Output format for configuration display

### Examples

```bash
# Show formatted table (default)
dbranching config list

# Export as YAML suitable for copying to config file
dbranching config list --format=yaml

# Export as JSON for programmatic use
dbranching config list --format=json

# Show with verbose details
dbranching --verbose config list
```

### Use Cases

- Verify configuration after changes
- Export configuration for sharing or backup
- Debug configuration loading issues
- Check which values are active from multiple sources

---

### `config get` - Get Configuration Value

**Usage:** `dbranching config get KEY`  
**Description:** Get a specific configuration value using dot notation

#### Arguments

##### `KEY`
**Type:** String  
**Required:** Yes  
**Description:** Configuration key in dot notation (e.g., `database.host`)

### Examples

```bash
# Get database host
dbranching config get database.host

# Get logging level
dbranching config get logging.level

# Get storage directory
dbranching config get storage.directory

# Get compression setting
dbranching config get storage.compression
```

### Configuration Keys

**Database Configuration:**
- `database.type` - Database type (postgresql, mysql, sqlite)
- `database.host` - Database host
- `database.port` - Database port
- `database.database` - Database name
- `database.username` - Database username
- `database.password_env` - Password environment variable name

**Storage Configuration:**
- `storage.directory` - Snapshot storage directory
- `storage.compression` - Compression method
- `storage.retention_days` - Retention period in days

**Logging Configuration:**
- `logging.level` - Log level
- `logging.format` - Log format
- `logging.file` - Log file path

---

### `config set` - Set Configuration Value

**Usage:** `dbranching config set KEY VALUE`  
**Description:** Set a configuration value (planned feature - not yet implemented)

#### Arguments

##### `KEY`
**Type:** String  
**Required:** Yes  
**Description:** Configuration key in dot notation

##### `VALUE`
**Type:** String  
**Required:** Yes  
**Description:** New value to set

### Examples

```bash
# Set database host (planned)
dbranching config set database.host localhost

# Set logging level (planned)
dbranching config set logging.level DEBUG
```

**Current Implementation:** Configuration modification not yet implemented. Edit the configuration file directly.

---

## `snapshot` - Snapshot Management

**Usage:** `dbranching snapshot COMMAND [OPTIONS]`  
**Description:** Manage database snapshots for development workflows

Database snapshots capture the complete state of your database at a point in time, similar to Git commits but for database content.

### Snapshot Features

- Full database content capture
- Metadata: descriptions, tags, timestamps
- Compressed storage with multiple algorithms
- Automatic cleanup based on retention policies
- Fast restore operations

---

### `snapshot create` - Create Snapshot

**Usage:** `dbranching snapshot create NAME [OPTIONS]`  
**Description:** Create a new database snapshot from current database state

Captures the complete current state of the database including all tables, data, indexes, and schema.

#### Arguments

##### `NAME`
**Type:** String  
**Required:** Yes  
**Description:** Name for the snapshot (must be unique)

#### Options

##### `--description`, `-d`
**Type:** String  
**Description:** Human-readable description of the snapshot purpose

##### `--tags`
**Type:** String  
**Description:** Comma-separated list of tags for organization (e.g., 'feature,testing')

### What Gets Captured

- All table data and structure
- Database schema (tables, indexes, constraints)
- User-defined functions and procedures
- Views and materialized views
- Permissions and roles (database-specific)

### Snapshot Naming Guidelines

- Use descriptive names like `feature-auth` or `before-migration`
- Names must be unique (existing snapshots cannot be overwritten)
- Avoid spaces or special characters (use hyphens or underscores)
- Consider using date prefixes: `2024-01-15-baseline`

### Examples

```bash
# Basic snapshot
dbranching snapshot create dev-baseline

# With description  
dbranching snapshot create feature-auth --description "User authentication complete"

# With tags for organization
dbranching snapshot create test-data --tags "testing,sample-data" --description "Test dataset v1"

# Before dangerous operation
dbranching snapshot create before-migration --description "Before schema migration"

# Preview snapshot creation
dbranching --dry-run snapshot create test-snapshot

# Create with verbose output
dbranching --verbose snapshot create debug-snapshot
```

---

### `snapshot list` - List Snapshots

**Usage:** `dbranching snapshot list [OPTIONS]`  
**Description:** List available snapshots with metadata

Shows all snapshots with creation dates, descriptions, tags, and sizes.

#### Options

##### `--filter`
**Type:** String  
**Description:** Filter snapshots by name or tag pattern

##### `--format`
**Type:** Choice [`table`, `json`, `simple`]  
**Default:** `table`  
**Description:** Output format

### Examples

```bash
# List all snapshots
dbranching snapshot list

# Filter by name pattern
dbranching snapshot list --filter "dev*"
dbranching snapshot list --filter "*feature*"

# JSON output for programmatic use
dbranching snapshot list --format=json

# Simple format (names only)
dbranching snapshot list --format=simple

# Verbose listing
dbranching --verbose snapshot list
```

### Output Formats

**Table Format (default):**
```
Name            Created              Description                Tags        Size
baseline        2024-01-15 14:30:15  Initial database state                 2.3MB
feature-auth    2024-01-15 15:45:22  User authentication       feature     4.1MB
test-data       2024-01-16 09:15:10  Test dataset v1           testing     8.7MB
```

**JSON Format:**
```json
[
  {
    "name": "baseline",
    "created": "2024-01-15T14:30:15Z",
    "description": "Initial database state",
    "tags": [],
    "size": "2.3MB",
    "compressed_size": "1.1MB",
    "compression": "gzip"
  }
]
```

**Simple Format:**
```
baseline
feature-auth
test-data
```

---

### `snapshot restore` - Restore Snapshot

**Usage:** `dbranching snapshot restore NAME [OPTIONS]`  
**Description:** Restore a database snapshot

Restores the database to the exact state captured in the specified snapshot. This operation will overwrite current database content.

#### Arguments

##### `NAME`
**Type:** String  
**Required:** Yes  
**Description:** Name of the snapshot to restore

#### Options

##### `--force`
**Type:** Flag  
**Description:** Force restore without confirmation

##### `--confirm`
**Type:** Flag  
**Description:** Prompt for confirmation before restoring

### Examples

```bash
# Restore snapshot (with default confirmation)
dbranching snapshot restore dev-baseline

# Force restore without confirmation
dbranching snapshot restore v1.0 --force

# Explicitly require confirmation
dbranching snapshot restore test --confirm

# Preview restore operation
dbranching --dry-run snapshot restore baseline

# Restore with verbose output
dbranching --verbose snapshot restore feature-auth
```

### Safety Features

- Confirmation prompt by default (unless `--force` used)
- Dry-run mode to preview changes
- Backup recommendations before restore
- Database connection validation before restore
- Integrity checks during restore process

---

## `status` - System Status

**Usage:** `dbranching status [OPTIONS]`  
**Description:** Display comprehensive dbranching system status

Shows the current state of dbranching including configuration status, database connectivity, storage health, and snapshot statistics.

### Options

#### `--verbose`, `-v`
**Type:** Flag  
**Description:** Show detailed status including connection test and storage details

### Basic Status Information

- Configuration file location and validity
- Database type and connection parameters
- Storage directory status and permissions
- Quick snapshot count

### Verbose Status Additions

- Database connection test results
- Detailed storage and logging configuration  
- Storage directory size and available space
- Recent snapshot activity
- System health indicators

### Examples

```bash
# Quick status check
dbranching status

# Full diagnostic information
dbranching status --verbose
dbranching status -v

# Global verbose flag
dbranching --verbose status
```

### Sample Output

**Basic Status:**
```
DBranching Status
==================================================
Configuration file: /home/user/project/dbranching.yaml
Database type: postgresql
Storage directory: /home/user/.dbranching/snapshots
Storage directory: ✓ exists
```

**Verbose Status:**
```
DBranching Status
==================================================
Configuration file: /home/user/project/dbranching.yaml
Database type: postgresql
Database host: localhost:5432
Database name: myapp
Storage directory: /home/user/.dbranching/snapshots
Storage directory: ✓ exists
Storage size: 45.2MB (3 snapshots)
Available space: 250GB
Log level: INFO
Log file: /home/user/.dbranching/logs/dbranching.log

Database connection: ✓ successful
Last snapshot: feature-auth (2 hours ago)
```

### Troubleshooting Use

Use verbose mode to diagnose:
- Database connection issues
- Configuration loading problems
- Storage permission issues
- Missing directories or files

---

## Exit Codes

DBranching uses specific exit codes for different error conditions:

| Exit Code | Meaning | Example Scenarios |
|-----------|---------|------------------|
| 0 | Success | Command completed successfully |
| 1 | General error | Unexpected internal error |
| 2 | Configuration error | Invalid config file, missing settings |
| 3 | Database connection error | Cannot connect to database |
| 4 | Snapshot operation error | Snapshot creation/restore failed |
| 5 | Validation error | Invalid arguments or data |
| 6 | Storage error | Cannot access storage directory |

### Using Exit Codes

```bash
# Check if command succeeded
dbranching status
if [ $? -eq 0 ]; then
    echo "Status check successful"
else
    echo "Status check failed with code $?"
fi

# In scripts
dbranching snapshot create backup || {
    echo "Snapshot creation failed"
    exit 1
}
```

## Environment Variables

Override configuration with environment variables using the `DBRANCHING_` prefix:

### Database Variables

```bash
export DBRANCHING_DATABASE_TYPE=postgresql
export DBRANCHING_DATABASE_HOST=db.example.com
export DBRANCHING_DATABASE_PORT=5432
export DBRANCHING_DATABASE_NAME=production_app
export DBRANCHING_DATABASE_USERNAME=dbranching_user
export DBRANCHING_DATABASE_PASSWORD_ENV=POSTGRES_PASSWORD
```

### Storage Variables

```bash
export DBRANCHING_STORAGE_DIRECTORY=/opt/dbranching/snapshots
export DBRANCHING_STORAGE_COMPRESSION=lzma
export DBRANCHING_STORAGE_RETENTION_DAYS=90
```

### Logging Variables

```bash
export DBRANCHING_LOG_LEVEL=DEBUG
export DBRANCHING_LOG_FORMAT=json
export DBRANCHING_LOG_FILE=/var/log/dbranching.log
```

### Password Variables

```bash
export DB_PASSWORD='production_password'
export POSTGRES_PASSWORD='postgres_password'
export MYSQL_PASSWORD='mysql_password'
```

## Shell Completion

Enable shell completion for better CLI experience:

### Bash Completion

```bash
# Add to ~/.bashrc
eval "$(_DBRANCHING_COMPLETE=bash_source dbranching)"
```

### Zsh Completion

```bash
# Add to ~/.zshrc
eval "$(_DBRANCHING_COMPLETE=zsh_source dbranching)"
```

### Fish Completion

```bash
# Add to ~/.config/fish/completions/dbranching.fish
_DBRANCHING_COMPLETE=fish_source dbranching | source
```

## Configuration File Examples

### Minimal Configuration

```yaml
database:
  type: sqlite
  database: ./app.db
```

### Development Configuration

```yaml
database:
  type: postgresql
  host: localhost
  port: 5432
  database: myapp_dev
  username: developer
  password_env: DEV_DB_PASSWORD

storage:
  directory: ./snapshots
  compression: gzip
  retention_days: 7

logging:
  level: DEBUG
  format: simple
```

### Production Configuration

```yaml
database:
  type: postgresql
  host: prod-db.internal
  port: 5432
  database: production_app
  username: dbranching_prod
  password_env: PROD_DB_PASSWORD

storage:
  directory: /var/backups/dbranching
  compression: lzma
  retention_days: 90

logging:
  level: WARNING
  format: json
  file: /var/log/dbranching/app.log
```

## Integration Examples

### CI/CD Pipeline

```yaml
# GitHub Actions example
- name: Create pre-deployment snapshot
  run: |
    dbranching snapshot create pre-deploy-$(date +%Y%m%d-%H%M%S) \
      --description "Before deployment of commit ${{ github.sha }}"

- name: Deploy application
  run: ./deploy.sh

- name: Create post-deployment snapshot
  run: |
    dbranching snapshot create post-deploy-$(date +%Y%m%d-%H%M%S) \
      --description "After deployment of commit ${{ github.sha }}"
```

### Backup Script

```bash
#!/bin/bash
# Daily backup script

set -e

DATE=$(date +%Y%m%d)
SNAPSHOT_NAME="daily-backup-$DATE"

# Create snapshot
dbranching snapshot create "$SNAPSHOT_NAME" \
  --description "Daily automated backup" \
  --tags "automated,backup"

# Check status
dbranching status --verbose

echo "Backup completed: $SNAPSHOT_NAME"
```

### Testing Integration

```bash
#!/bin/bash
# Test runner with database reset

set -e

# Create test baseline if it doesn't exist
if ! dbranching snapshot list --format=simple | grep -q "test-baseline"; then
    dbranching snapshot create test-baseline --description "Clean test database"
fi

# Reset to baseline before tests
dbranching snapshot restore test-baseline --force

# Run tests
pytest tests/

# Optionally restore to baseline after tests
dbranching snapshot restore test-baseline --force
```

## Getting Help

### Command Help

```bash
# General help
dbranching --help

# Command-specific help
dbranching init --help
dbranching config --help
dbranching snapshot --help
dbranching snapshot create --help
```

### Version Information

```bash
dbranching --version
```

### Online Resources

- [Full Documentation](../README.md)
- [Configuration Guide](../configuration.md)
- [Troubleshooting Guide](../troubleshooting.md)
- [GitHub Issues](https://github.com/your-org/dbranching/issues)