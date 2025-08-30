# Quick Start Guide

Get up and running with DBranching in 5 minutes. This guide walks you through installation, setup, and creating your first database snapshots.

## Prerequisites

- Python 3.10+
- A PostgreSQL, MySQL, or SQLite database
- Basic command line familiarity

## 1. Installation

```bash
# Clone and install
git clone https://github.com/your-org/dbranching.git
cd dbranching
poetry install

# Or using pip
pip install -e .
```

For detailed installation instructions, see [Installation Guide](installation.md).

## 2. Initialize DBranching

```bash
# Create default configuration
dbranching init
```

This creates a `dbranching.yaml` file with default settings:

```yaml
database:
  type: postgresql
  host: localhost
  port: 5432
  database: myapp
  username: user
  password_env: DB_PASSWORD

storage:
  directory: ~/.dbranching/snapshots
  compression: gzip
  retention_days: 30

logging:
  level: INFO
  format: structured
  file: ~/.dbranching/logs/dbranching.log
```

## 3. Configure Database Connection

Edit `dbranching.yaml` to match your database:

```yaml
database:
  type: postgresql          # or mysql, sqlite
  host: localhost          # your database host
  port: 5432              # your database port
  database: your_db_name   # your database name
  username: your_username  # your username
  password_env: DB_PASSWORD
```

Set your database password as an environment variable:

```bash
export DB_PASSWORD='your_secure_password'
```

## 4. Verify Setup

```bash
# Check configuration
dbranching config list

# Test database connection
dbranching status --verbose
```

You should see output like:

```
DBranching Status
==================================================
Configuration file: /path/to/dbranching.yaml
Database type: postgresql
Storage directory: /home/user/.dbranching/snapshots
Storage directory: ✓ exists
```

## 5. Create Your First Snapshot

```bash
# Create a snapshot of current database state
dbranching snapshot create baseline --description "Initial database state"
```

## 6. List Snapshots

```bash
# View all snapshots
dbranching snapshot list
```

Expected output:
```
Name      Created              Description              Tags    Size
baseline  2024-01-15 14:30:15  Initial database state           2.3MB
```

## 7. Make Changes and Create Another Snapshot

Now make some changes to your database (add tables, insert data, etc.), then:

```bash
# Create another snapshot
dbranching snapshot create feature-work --description "Added user management"
```

## 8. Restore a Snapshot

```bash
# Restore to baseline
dbranching snapshot restore baseline --confirm
```

## Common Workflows

### Development Workflow

```bash
# 1. Create baseline before starting work
dbranching snapshot create start-of-sprint

# 2. Work on features...
# (make database changes)

# 3. Create feature snapshots
dbranching snapshot create feature/user-auth
dbranching snapshot create feature/payment-system

# 4. Switch between states
dbranching snapshot restore start-of-sprint    # Reset
dbranching snapshot restore feature/user-auth  # Test auth
dbranching snapshot restore feature/payment-system  # Test payments
```

### Testing Workflow

```bash
# 1. Create clean test state
dbranching snapshot create test-baseline

# 2. Run tests that modify data
./run-tests.sh

# 3. Reset to clean state for next test run
dbranching snapshot restore test-baseline
```

### Migration Workflow

```bash
# 1. Snapshot before migration
dbranching snapshot create before-migration-v2.1

# 2. Run migration
python manage.py migrate

# 3. Snapshot after successful migration
dbranching snapshot create after-migration-v2.1

# 4. If something goes wrong, rollback
dbranching snapshot restore before-migration-v2.1
```

## Configuration Examples

### SQLite for Local Development

```yaml
database:
  type: sqlite
  database: ./dev.db
  # host, port, username not needed for SQLite

storage:
  directory: ./snapshots
  compression: gzip
  retention_days: 7
```

### MySQL Production Setup

```yaml
database:
  type: mysql
  host: mysql.example.com
  port: 3306
  database: production_app
  username: app_user
  password_env: MYSQL_PASSWORD

storage:
  directory: /var/backups/dbranching
  compression: bzip2
  retention_days: 90
```

### PostgreSQL with Custom Settings

```yaml
database:
  type: postgresql
  host: postgres.internal
  port: 5432
  database: app_production
  username: dbranching_user
  password_env: POSTGRES_PASSWORD

storage:
  directory: /opt/dbranching/snapshots
  compression: lzma
  retention_days: 60

logging:
  level: WARNING
  format: json
  file: /var/log/dbranching.log
```

## Useful Commands

### Status and Information

```bash
# Quick status
dbranching status

# Detailed status with connection test
dbranching status --verbose

# Show configuration
dbranching config list

# Get specific config values
dbranching config get database.host
dbranching config get storage.directory
```

### Snapshot Management

```bash
# Create snapshots
dbranching snapshot create <name>
dbranching snapshot create <name> --description "Purpose of snapshot"
dbranching snapshot create <name> --tags "tag1,tag2"

# List snapshots
dbranching snapshot list
dbranching snapshot list --format=json
dbranching snapshot list --filter "feature*"

# Restore snapshots
dbranching snapshot restore <name>
dbranching snapshot restore <name> --force    # Skip confirmation
dbranching snapshot restore <name> --confirm  # Force confirmation prompt
```

### Dry Run Mode

Test commands without executing them:

```bash
# Preview what would happen
dbranching --dry-run snapshot create test-snapshot
dbranching --dry-run snapshot restore baseline
```

### Verbose Mode

Get detailed output for troubleshooting:

```bash
# Enable verbose output
dbranching --verbose status
dbranching --verbose snapshot create debug-snapshot
```

## Best Practices

### Snapshot Naming

- Use descriptive names: `feature-user-auth` not `test1`
- Include dates for time-based snapshots: `2024-01-15-baseline`
- Use consistent prefixes: `dev-`, `test-`, `prod-`
- Avoid spaces and special characters

### Regular Snapshots

Create snapshots before:
- Major feature development
- Database schema changes
- Data migrations
- Production deployments
- Destructive operations

### Storage Management

- Monitor disk space usage
- Set appropriate retention policies
- Use compression to save space
- Consider separate storage for production

### Security

- Never store passwords in configuration files
- Use environment variables for sensitive data
- Secure snapshot storage directories
- Use encrypted connections for remote databases

## Troubleshooting

### Configuration Issues

```bash
# Check if config file exists and is valid
dbranching config list

# Reinitialize if needed
dbranching init --force
```

### Database Connection Issues

```bash
# Test connection
dbranching status --verbose

# Check environment variables
echo $DB_PASSWORD

# Verify network connectivity
ping your-database-host
```

### Storage Issues

```bash
# Check storage directory
dbranching config get storage.directory
ls -la ~/.dbranching/snapshots/

# Check permissions
chmod 755 ~/.dbranching/snapshots/
```

### Common Error Messages

**"Configuration file not found"**
- Run `dbranching init` to create default configuration

**"Database connection failed"**
- Check database is running
- Verify connection parameters in config
- Ensure password environment variable is set

**"Permission denied on storage directory"**
- Check directory permissions
- Create directory manually if needed

## Next Steps

Now that you have DBranching set up:

1. **Learn Advanced Features**: Read the [Configuration Guide](configuration.md)
2. **Explore Workflows**: Check out [Workflow Examples](workflows/)
3. **Integration**: Learn about [CI/CD Integration](workflows/deployment.md)
4. **API Usage**: See [Developer API Documentation](api/)

## Getting Help

- **Documentation**: Read the full [README](../README.md)
- **Examples**: Browse [example configurations](examples/)
- **Issues**: Report problems on [GitHub Issues](https://github.com/your-org/dbranching/issues)
- **Community**: Join discussions in [GitHub Discussions](https://github.com/your-org/dbranching/discussions)

## What's Next?

You now have a working DBranching setup! Here are some next steps to explore:

- Set up automated snapshots with cron jobs
- Integrate with your CI/CD pipeline
- Explore advanced configuration options
- Learn about snapshot cleanup and retention policies
- Try different compression algorithms for your use case

Happy branching! 🚀