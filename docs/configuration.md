# Configuration Guide

Complete reference for configuring DBranching to work with your database setup, storage requirements, and operational needs.

## Configuration Overview

DBranching uses a hierarchical configuration system that merges settings from multiple sources:

1. **Default values** (built into the application)
2. **Configuration files** (YAML or JSON)
3. **Environment variables** (with `DBRANCHING_` prefix)
4. **Command-line options** (highest priority)

## Configuration File Locations

DBranching searches for configuration files in this order:

1. `dbranching.yaml` (current directory)
2. `dbranching.yml` (current directory)  
3. `dbranching.json` (current directory)
4. `~/.dbranching/config.yaml` (user home directory)
5. `~/.dbranching/config.yml` (user home directory)
6. `~/.dbranching/config.json` (user home directory)

Use `dbranching config list` to see which file is being used.

## Configuration Schema

### Complete Configuration Example

```yaml
database:
  type: postgresql              # Database type: postgresql, mysql, sqlite
  host: localhost               # Database host
  port: 5432                   # Database port
  database: myapp              # Database name
  username: user               # Database username
  password_env: DB_PASSWORD    # Environment variable containing password

storage:
  directory: ~/.dbranching/snapshots  # Snapshot storage directory
  compression: gzip                   # Compression: none, gzip, bzip2, lzma
  retention_days: 30                  # Days to keep snapshots (0 = forever)

logging:
  level: INFO                   # Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: structured           # Log format: structured, simple, json
  file: ~/.dbranching/logs/dbranching.log  # Log file path (null = console only)
```

## Database Configuration

### PostgreSQL

```yaml
database:
  type: postgresql
  host: localhost
  port: 5432
  database: myapp
  username: postgres
  password_env: POSTGRES_PASSWORD
```

**Environment Variables:**
```bash
export POSTGRES_PASSWORD='your_secure_password'
export DBRANCHING_DATABASE_HOST=postgres.example.com
export DBRANCHING_DATABASE_PORT=5433
```

**Connection String Format:**
`postgresql://username:password@host:port/database`

### MySQL

```yaml
database:
  type: mysql
  host: localhost
  port: 3306
  database: myapp
  username: root
  password_env: MYSQL_PASSWORD
```

**Environment Variables:**
```bash
export MYSQL_PASSWORD='your_secure_password'
export DBRANCHING_DATABASE_HOST=mysql.example.com
```

**Connection String Format:**
`mysql://username:password@host:port/database`

### SQLite

```yaml
database:
  type: sqlite
  database: /path/to/database.db
  # host, port, username, password_env not used for SQLite
```

**File Paths:**
- Absolute paths: `/home/user/app.db`
- Relative paths: `./data/app.db`
- Memory database: `:memory:` (not recommended for snapshots)

## Storage Configuration

### Directory Settings

```yaml
storage:
  directory: ~/.dbranching/snapshots
  compression: gzip
  retention_days: 30
```

**Directory Options:**
- `~/.dbranching/snapshots` - User home directory (default)
- `./snapshots` - Relative to current directory
- `/var/backups/dbranching` - Absolute system path
- `s3://bucket/prefix` - S3 bucket (future feature)

### Compression Options

| Algorithm | Speed | Compression Ratio | CPU Usage | Best For |
|-----------|--------|------------------|-----------|----------|
| `none` | Fastest | 1:1 | Minimal | Fast local storage |
| `gzip` | Fast | Good | Low | General purpose (default) |
| `bzip2` | Medium | Better | Medium | Network storage |
| `lzma` | Slow | Best | High | Long-term archival |

**Example Configurations:**

```yaml
# Fast local development
storage:
  compression: none
  retention_days: 7

# Network storage  
storage:
  compression: bzip2
  retention_days: 30

# Long-term archival
storage:
  compression: lzma
  retention_days: 365
```

### Retention Policies

```yaml
storage:
  retention_days: 30    # Delete snapshots older than 30 days
  # retention_days: 0   # Keep forever (not recommended)
```

**Automatic Cleanup:**
- Runs during snapshot creation
- Only removes snapshots older than retention period
- Tagged snapshots may have different retention rules (future feature)

## Logging Configuration

### Log Levels

```yaml
logging:
  level: DEBUG      # Most verbose
  level: INFO       # Default
  level: WARNING    # Warnings and errors only
  level: ERROR      # Errors only
  level: CRITICAL   # Critical errors only
```

### Log Formats

#### Structured Format (Default)
```yaml
logging:
  format: structured
```

Output:
```
2024-01-15 14:30:15 [    INFO] dbranching.cli: Created snapshot 'baseline'
2024-01-15 14:30:16 [   DEBUG] dbranching.storage: Compressed snapshot to 2.3MB
```

#### Simple Format
```yaml
logging:
  format: simple
```

Output:
```
INFO: Created snapshot 'baseline'
DEBUG: Compressed snapshot to 2.3MB
```

#### JSON Format
```yaml
logging:
  format: json
```

Output:
```json
{"timestamp": "2024-01-15T14:30:15", "level": "INFO", "logger": "dbranching.cli", "message": "Created snapshot 'baseline'"}
{"timestamp": "2024-01-15T14:30:16", "level": "DEBUG", "logger": "dbranching.storage", "message": "Compressed snapshot to 2.3MB"}
```

### Log Destinations

```yaml
logging:
  file: ~/.dbranching/logs/dbranching.log    # Log to file
  # file: null                               # Console output only
  # file: /var/log/dbranching.log            # System log directory
```

## Environment Variables

Override any configuration setting using environment variables with the `DBRANCHING_` prefix:

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

Store database passwords in separate environment variables:

```bash
export DB_PASSWORD='production_password'
export POSTGRES_PASSWORD='postgres_password'
export MYSQL_PASSWORD='mysql_password'
```

## Configuration Validation

### Test Configuration

```bash
# Check configuration syntax
dbranching config list

# Test database connection
dbranching status --verbose

# Validate with dry-run
dbranching --dry-run snapshot create test
```

### Common Validation Errors

**Invalid database type:**
```yaml
database:
  type: invalid_db    # Must be: postgresql, mysql, sqlite
```

**Invalid port range:**
```yaml
database:
  port: 99999         # Must be 1-65535
```

**Invalid retention days:**
```yaml
storage:
  retention_days: -1  # Must be >= 0
```

**Invalid log level:**
```yaml
logging:
  level: VERBOSE      # Must be: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Environment-Specific Configurations

### Development Environment

```yaml
# dev.dbranching.yaml
database:
  type: sqlite
  database: ./dev.db

storage:
  directory: ./dev-snapshots
  compression: none
  retention_days: 7

logging:
  level: DEBUG
  format: simple
  file: ./dev.log
```

### Testing Environment

```yaml
# test.dbranching.yaml
database:
  type: postgresql
  host: test-db
  port: 5432
  database: test_db
  username: test_user
  password_env: TEST_DB_PASSWORD

storage:
  directory: ./test-snapshots
  compression: gzip
  retention_days: 3

logging:
  level: INFO
  format: structured
  file: ./test.log
```

### Production Environment

```yaml
# prod.dbranching.yaml
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

### Using Different Configs

```bash
# Specify config file explicitly
dbranching --config-file dev.dbranching.yaml status
dbranching --config-file prod.dbranching.yaml snapshot create release-v1.0

# Use environment variables to switch configs
export DBRANCHING_CONFIG_FILE=test.dbranching.yaml
dbranching status
```

## Security Best Practices

### Password Management

**✅ Good:**
```yaml
database:
  password_env: DB_PASSWORD
```
```bash
export DB_PASSWORD='secure_password_from_vault'
```

**❌ Bad:**
```yaml
database:
  password: plaintext_password_in_file  # Never do this!
```

### File Permissions

```bash
# Secure configuration file
chmod 600 dbranching.yaml

# Secure storage directory
chmod 700 ~/.dbranching/snapshots/

# Secure log files
chmod 640 ~/.dbranching/logs/dbranching.log
```

### Network Security

```yaml
database:
  # Use SSL connections (database-specific)
  ssl_mode: require
  ssl_cert: /path/to/client-cert.pem
  ssl_key: /path/to/client-key.pem
  ssl_ca: /path/to/ca-cert.pem
```

## Configuration Management

### Version Control

Create a template configuration for version control:

```yaml
# dbranching.yaml.template
database:
  type: postgresql
  host: ${DATABASE_HOST}
  port: ${DATABASE_PORT}
  database: ${DATABASE_NAME}
  username: ${DATABASE_USER}
  password_env: DB_PASSWORD

storage:
  directory: ${SNAPSHOTS_DIR}
  compression: gzip
  retention_days: ${RETENTION_DAYS}

logging:
  level: ${LOG_LEVEL}
  format: structured
  file: ${LOG_FILE}
```

### Configuration Deployment

```bash
# Generate config from template
envsubst < dbranching.yaml.template > dbranching.yaml

# Or use configuration management tools
ansible-playbook deploy-dbranching-config.yml
```

### Multiple Environments

```bash
# Directory structure
configs/
├── base.yaml           # Common settings
├── dev.yaml           # Development overrides
├── test.yaml          # Testing overrides
└── prod.yaml          # Production overrides

# Merge configurations
yq eval-all 'select(fileIndex == 0) * select(fileIndex == 1)' base.yaml dev.yaml > dbranching.yaml
```

## Advanced Configuration

### Custom Configuration Schema

Future versions may support:

```yaml
# Advanced features (planned)
snapshots:
  auto_cleanup: true
  parallel_operations: 4
  verification: true

compression:
  level: 9              # Compression level (1-9)
  threads: 4            # Parallel compression threads

database:
  connection_pool_size: 10
  connection_timeout: 30
  ssl_mode: require

storage:
  backends:
    - type: local
      directory: /primary/storage
    - type: s3
      bucket: dbranching-snapshots
      prefix: production/
```

### Plugin Configuration

```yaml
# Plugin system (planned)
plugins:
  - name: slack_notifications
    config:
      webhook_url: ${SLACK_WEBHOOK}
      channel: "#database-alerts"
  
  - name: backup_verification
    config:
      verify_after_creation: true
      test_restore: weekly
```

## Troubleshooting Configuration

### Debug Configuration Loading

```bash
# Show configuration loading process
dbranching --verbose config list

# Show environment variables
env | grep DBRANCHING_

# Test specific configuration
dbranching --config-file /path/to/config.yaml --dry-run status
```

### Configuration Conflicts

When values come from multiple sources, the precedence is:

1. Command-line flags (highest)
2. Environment variables
3. Configuration files
4. Default values (lowest)

### Migration Between Versions

When upgrading DBranching, check for configuration changes:

```bash
# Backup current config
cp dbranching.yaml dbranching.yaml.backup

# Generate new default config
dbranching init --force

# Merge your customizations
# (manual process - compare files)
```

## Best Practices

### Configuration Organization

- Use environment-specific configuration files
- Store sensitive values in environment variables only
- Document configuration choices with comments
- Version control configuration templates, not actual configs
- Use configuration validation in CI/CD pipelines

### Monitoring and Maintenance

- Monitor storage directory size growth
- Review retention policies regularly
- Test configuration changes in development first
- Set up log rotation for log files
- Monitor database connection health

### Performance Optimization

```yaml
# For high-frequency snapshots
storage:
  compression: gzip    # Balance of speed and size
  retention_days: 7    # Frequent cleanup

# For large databases
storage:
  compression: lzma    # Maximum compression
  retention_days: 30   # Less frequent cleanup

# For development
storage:
  compression: none    # Fastest operations
  retention_days: 3    # Minimal storage
```

## Getting Help

- **Validation**: Use `dbranching config list` to check syntax
- **Testing**: Use `--dry-run` and `--verbose` flags
- **Documentation**: Reference this guide and inline help
- **Issues**: Report configuration problems on GitHub
- **Examples**: See [example configurations](examples/) directory