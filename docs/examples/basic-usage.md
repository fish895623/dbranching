# Basic Usage Examples

Simple, practical examples for getting started with DBranching. These examples demonstrate core functionality with real-world scenarios.

## Quick Start Examples

### Example 1: First Time Setup

```bash
# 1. Initialize DBranching
$ dbranching init
Initialized dbranching with configuration: /home/user/project/dbranching.yaml
Storage directory: /home/user/.dbranching/snapshots
Log file: /home/user/.dbranching/logs/dbranching.log

# 2. Set database password
$ export DB_PASSWORD='my_secure_password'

# 3. Check status
$ dbranching status
DBranching Status
==================================================
Configuration file: /home/user/project/dbranching.yaml
Database type: postgresql
Storage directory: /home/user/.dbranching/snapshots
Storage directory: ✓ exists

# 4. Create first snapshot
$ dbranching snapshot create initial-state --description "Fresh database setup"
Created snapshot 'initial-state' (2.3MB compressed)
```

### Example 2: Development Cycle

```bash
# Start from clean state
$ dbranching snapshot create baseline --description "Clean starting point"
Created snapshot 'baseline' (1.8MB compressed)

# Make some database changes
# ... add tables, insert data, etc. ...

# Save your work
$ dbranching snapshot create feature-work --description "User table and sample data"
Created snapshot 'feature-work' (4.2MB compressed)

# List your snapshots
$ dbranching snapshot list
Name           Created              Description                Size
baseline       2024-01-15 14:30:15  Clean starting point       1.8MB
feature-work   2024-01-15 15:45:30  User table and sample data 4.2MB

# Go back to clean state
$ dbranching snapshot restore baseline
Restored snapshot 'baseline' successfully
```

## Configuration Examples

### Example 3: PostgreSQL Setup

**dbranching.yaml:**
```yaml
database:
  type: postgresql
  host: localhost
  port: 5432
  database: myapp_dev
  username: developer
  password_env: DB_PASSWORD

storage:
  directory: ~/.dbranching/snapshots
  compression: gzip
  retention_days: 14

logging:
  level: INFO
  format: structured
  file: ~/.dbranching/logs/dbranching.log
```

**Usage:**
```bash
# Set password
$ export DB_PASSWORD='dev_password_123'

# Test configuration
$ dbranching config list
Database Configuration:
  Type: postgresql
  Host: localhost
  Port: 5432
  Database: myapp_dev
  Username: developer
  Password Environment: DB_PASSWORD

# Test connection
$ dbranching status --verbose
DBranching Status
==================================================
Configuration file: /home/user/dbranching.yaml
Database type: postgresql
Database host: localhost:5432
Database name: myapp_dev
Storage directory: /home/user/.dbranching/snapshots
Storage directory: ✓ exists
Database connection: ✓ successful
```

### Example 4: SQLite Setup

**dbranching.yaml:**
```yaml
database:
  type: sqlite
  database: ./myapp.db

storage:
  directory: ./snapshots
  compression: gzip
  retention_days: 7

logging:
  level: DEBUG
  format: simple
  file: null  # Log to console only
```

**Usage:**
```bash
# No password needed for SQLite
$ dbranching status
DBranching Status
==================================================
Configuration file: /home/user/dbranching.yaml
Database type: sqlite
Storage directory: /home/user/snapshots
Storage directory: ✓ exists

$ dbranching snapshot create sqlite-baseline
INFO: Created snapshot 'sqlite-baseline'
INFO: Compressed snapshot to 856KB
```

### Example 5: MySQL Setup

**dbranching.yaml:**
```yaml
database:
  type: mysql
  host: localhost
  port: 3306
  database: myapp
  username: root
  password_env: MYSQL_PASSWORD

storage:
  directory: ~/.dbranching/snapshots
  compression: bzip2
  retention_days: 30

logging:
  level: WARNING
  format: json
  file: ~/.dbranching/logs/dbranching.log
```

**Usage:**
```bash
# Set MySQL password
$ export MYSQL_PASSWORD='mysql_root_password'

# Test setup
$ dbranching config get database.type
mysql

$ dbranching config get storage.compression
bzip2

# Create snapshot
$ dbranching snapshot create mysql-baseline --description "MySQL baseline setup"
Created snapshot 'mysql-baseline' (3.1MB compressed with bzip2)
```

## Snapshot Management Examples

### Example 6: Working with Snapshots

```bash
# Create snapshots with descriptions and tags
$ dbranching snapshot create dev-start \
    --description "Development starting point" \
    --tags "development,baseline"

$ dbranching snapshot create feature-auth \
    --description "User authentication feature" \
    --tags "feature,authentication,ready-for-review"

$ dbranching snapshot create test-data \
    --description "Sample test data for QA" \
    --tags "testing,sample-data"

# List all snapshots
$ dbranching snapshot list
Name          Created              Description                    Tags                        Size
dev-start     2024-01-15 09:00:00  Development starting point    development,baseline        1.2MB
feature-auth  2024-01-15 14:30:00  User authentication feature  feature,authentication...   2.8MB
test-data     2024-01-15 16:45:00  Sample test data for QA       testing,sample-data         4.1MB

# Filter snapshots
$ dbranching snapshot list --filter "feature*"
Name          Created              Description                   Tags                        Size
feature-auth  2024-01-15 14:30:00  User authentication feature  feature,authentication...   2.8MB

# Get JSON output for scripting
$ dbranching snapshot list --format=json | jq '.[0].name'
"dev-start"
```

### Example 7: Snapshot Restore Scenarios

```bash
# Basic restore
$ dbranching snapshot restore dev-start
Restored snapshot 'dev-start' successfully

# Restore with confirmation prompt
$ dbranching snapshot restore test-data --confirm
Restore snapshot 'test-data'? This will overwrite current data. [y/N]: y
Restored snapshot 'test-data' successfully

# Force restore without prompt
$ dbranching snapshot restore feature-auth --force
Restored snapshot 'feature-auth' successfully

# Preview restore (dry run)
$ dbranching --dry-run snapshot restore dev-start
Would restore snapshot 'dev-start'
```

## Environment Variable Examples

### Example 8: Using Environment Variables

```bash
# Override database settings
$ export DBRANCHING_DATABASE_HOST=production-db.company.com
$ export DBRANCHING_DATABASE_PORT=5433
$ export DBRANCHING_DATABASE_NAME=prod_app

# Override storage settings
$ export DBRANCHING_STORAGE_DIRECTORY=/backups/dbranching
$ export DBRANCHING_STORAGE_COMPRESSION=lzma

# Override logging
$ export DBRANCHING_LOG_LEVEL=DEBUG
$ export DBRANCHING_LOG_FORMAT=json

# Verify settings
$ dbranching config list
Database Configuration:
  Type: postgresql
  Host: production-db.company.com
  Port: 5433
  Database: prod_app
  Username: user
  Password Environment: DB_PASSWORD

Storage Configuration:
  Directory: /backups/dbranching
  Compression: lzma
  Retention Days: 30

Logging Configuration:
  Level: DEBUG
  Format: json
  File: /home/user/.dbranching/logs/dbranching.log
```

## Command-Line Options Examples

### Example 9: Global Options

```bash
# Use custom config file
$ dbranching --config-file ./staging.yaml status
DBranching Status (using ./staging.yaml)
==================================================
Configuration file: ./staging.yaml
Database type: postgresql

# Enable verbose output
$ dbranching --verbose snapshot create verbose-test
[DEBUG] dbranching.config: Loading configuration from dbranching.yaml
[INFO] dbranching.cli: Creating snapshot 'verbose-test'
[DEBUG] dbranching.storage: Compressing snapshot with gzip
[INFO] dbranching.storage: Compressed 5.2MB to 2.1MB (59% reduction)
Created snapshot 'verbose-test' (2.1MB compressed)

# Dry run mode
$ dbranching --dry-run snapshot create test-snapshot
Would create snapshot 'test-snapshot'

# Combine options
$ dbranching --config-file prod.yaml --verbose --dry-run snapshot restore backup-2024-01-15
[INFO] Would restore snapshot 'backup-2024-01-15' using configuration from prod.yaml
```

## Error Handling Examples

### Example 10: Common Errors and Solutions

**Configuration Error:**
```bash
$ dbranching status
Error: Configuration error: Database type must be postgresql, mysql, or sqlite

# Solution: Fix the config file
$ dbranching config get database.type
postgres  # Wrong!

# Edit dbranching.yaml to use 'postgresql' not 'postgres'
$ dbranching config get database.type
postgresql  # Correct!
```

**Database Connection Error:**
```bash
$ dbranching status
Error: Database connection error: Connection refused

Troubleshooting:
  • Verify database connection settings with 'dbranching config list'
  • Check database password environment variable
  • Ensure database server is running and accessible

# Solutions:
$ dbranching config list  # Check settings
$ echo $DB_PASSWORD       # Check password is set
$ pg_isready -h localhost -p 5432  # Test PostgreSQL connection
```

**Storage Error:**
```bash
$ dbranching snapshot create test
Error: Storage error: Permission denied: /home/user/.dbranching/snapshots

Troubleshooting:
  • Check storage directory permissions
  • Verify directory path with 'dbranching config get storage.directory'
  • Ensure sufficient disk space available

# Solutions:
$ mkdir -p ~/.dbranching/snapshots
$ chmod 755 ~/.dbranching/snapshots
```

## Practical Use Cases

### Example 11: Before Database Migration

```bash
# Before running a risky migration
$ dbranching snapshot create before-migration-v2.5 \
    --description "Database state before v2.5 schema migration" \
    --tags "migration,backup,v2.5"

# Run migration
$ python manage.py migrate

# If migration succeeds
$ dbranching snapshot create after-migration-v2.5 \
    --description "Database state after successful v2.5 migration" \
    --tags "migration,success,v2.5"

# If migration fails, rollback
$ dbranching snapshot restore before-migration-v2.5 --force
```

### Example 12: Testing with Clean Data

```bash
# Create clean test baseline
$ dbranching snapshot create test-baseline \
    --description "Clean database for testing" \
    --tags "testing,baseline,clean"

# Before each test run
$ dbranching snapshot restore test-baseline --force

# Run tests
$ npm test

# After tests (database may be modified)
$ dbranching snapshot restore test-baseline --force
```

### Example 13: Feature Development

```bash
# Start feature development
$ dbranching snapshot create feature-start \
    --description "Starting point for payment feature"

# Develop feature (add tables, test data, etc.)
# ... development work ...

# Save progress
$ dbranching snapshot create feature-payments-wip \
    --description "Payment feature work in progress" \
    --tags "feature,payments,wip"

# Continue development
# ... more work ...

# Feature complete
$ dbranching snapshot create feature-payments-complete \
    --description "Payment feature development complete" \
    --tags "feature,payments,complete,ready-for-review"

# Switch to work on different feature
$ dbranching snapshot restore feature-start
$ dbranching snapshot create feature-notifications-start \
    --description "Starting notifications feature from clean state"
```

## Automation Examples

### Example 14: Backup Script

```bash
#!/bin/bash
# backup-script.sh

DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_NAME="automated-backup-$DATE"

echo "Creating automated backup: $BACKUP_NAME"

dbranching snapshot create "$BACKUP_NAME" \
  --description "Automated backup created on $(date)" \
  --tags "automated,backup,$(date +%A)"

echo "Backup created successfully: $BACKUP_NAME"

# List recent backups
echo "Recent backups:"
dbranching snapshot list --filter "automated-backup-*" | head -5
```

### Example 15: Development Setup Script

```bash
#!/bin/bash
# setup-dev.sh

echo "Setting up development environment..."

# Initialize if not already done
if [ ! -f dbranching.yaml ]; then
    dbranching init
fi

# Set development password
export DB_PASSWORD='dev_password_123'

# Check status
dbranching status

# Create or restore development baseline
if ! dbranching snapshot list --format=simple | grep -q "dev-baseline"; then
    echo "Creating development baseline..."
    dbranching snapshot create dev-baseline \
      --description "Development environment baseline" \
      --tags "development,baseline,setup"
else
    echo "Restoring to development baseline..."
    dbranching snapshot restore dev-baseline --force
fi

echo "Development environment ready!"
```

These examples provide practical starting points for using DBranching in real development scenarios. Start with the basic examples and gradually incorporate more advanced patterns as you become comfortable with database state management.