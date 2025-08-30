# Troubleshooting Guide

Common issues and solutions for DBranching. Use this guide to diagnose and resolve problems quickly.

## Quick Diagnostics

Start with these commands to gather information:

```bash
# Check basic status
dbranching status

# Get detailed diagnostic information  
dbranching status --verbose

# Test configuration
dbranching config list

# Test with dry-run mode
dbranching --dry-run snapshot create test-snapshot
```

## Common Issues

### Configuration Problems

#### Issue: "Configuration file not found"

**Symptoms:**
```
Error: Configuration error: No configuration file found
```

**Solutions:**

1. **Initialize DBranching:**
   ```bash
   dbranching init
   ```

2. **Check search locations:**
   ```bash
   # DBranching looks in these locations:
   ls -la dbranching.yaml dbranching.yml dbranching.json
   ls -la ~/.dbranching/config.yaml ~/.dbranching/config.yml ~/.dbranching/config.json
   ```

3. **Specify config file explicitly:**
   ```bash
   dbranching --config-file /path/to/config.yaml status
   ```

#### Issue: "Invalid configuration syntax"

**Symptoms:**
```
Error: Configuration validation failed:
database -> type: Invalid database type 'postgres'
```

**Solutions:**

1. **Check YAML syntax:**
   ```bash
   # Test YAML validity
   python -c "import yaml; yaml.safe_load(open('dbranching.yaml'))"
   ```

2. **Fix common syntax errors:**
   ```yaml
   # Wrong - invalid database type
   database:
     type: postgres

   # Correct - use postgresql
   database:
     type: postgresql
   ```

3. **Validate configuration:**
   ```bash
   dbranching config list
   ```

#### Issue: "Permission denied reading config file"

**Symptoms:**
```
Error: Configuration error: Cannot read config file: Permission denied
```

**Solutions:**

1. **Fix file permissions:**
   ```bash
   chmod 644 dbranching.yaml
   ```

2. **Check file ownership:**
   ```bash
   ls -la dbranching.yaml
   sudo chown $USER:$USER dbranching.yaml
   ```

### Database Connection Problems

#### Issue: "Database connection failed"

**Symptoms:**
```
Error: Database connection error: Connection refused
Error: Database connection error: Authentication failed
Error: Database connection error: Database does not exist
```

**Solutions:**

1. **Verify database is running:**
   ```bash
   # PostgreSQL
   systemctl status postgresql
   pg_isready -h localhost -p 5432
   
   # MySQL
   systemctl status mysql
   mysqladmin -h localhost -P 3306 ping
   ```

2. **Test connection manually:**
   ```bash
   # PostgreSQL
   psql -h localhost -p 5432 -U username -d database
   
   # MySQL
   mysql -h localhost -P 3306 -u username -p database
   ```

3. **Check configuration:**
   ```bash
   dbranching config list
   dbranching config get database.host
   dbranching config get database.port
   ```

4. **Verify password environment variable:**
   ```bash
   echo $DB_PASSWORD
   # Should show your password, not be empty
   ```

5. **Test network connectivity:**
   ```bash
   telnet database-host 5432
   nc -zv database-host 5432
   ```

#### Issue: "Authentication failed"

**Symptoms:**
```
Error: Database connection error: Authentication failed for user 'username'
```

**Solutions:**

1. **Check username:**
   ```bash
   dbranching config get database.username
   ```

2. **Verify password:**
   ```bash
   # Check environment variable name
   dbranching config get database.password_env
   
   # Check if variable is set
   echo $DB_PASSWORD
   ```

3. **Test authentication manually:**
   ```bash
   # PostgreSQL
   psql -h localhost -p 5432 -U username -d database -W
   
   # MySQL
   mysql -h localhost -P 3306 -u username -p database
   ```

4. **Check database permissions:**
   ```sql
   -- PostgreSQL
   SELECT * FROM pg_user WHERE usename = 'username';
   
   -- MySQL
   SELECT User, Host FROM mysql.user WHERE User = 'username';
   ```

#### Issue: "Database does not exist"

**Symptoms:**
```
Error: Database connection error: Database 'myapp' does not exist
```

**Solutions:**

1. **List available databases:**
   ```bash
   # PostgreSQL
   psql -h localhost -p 5432 -U username -l
   
   # MySQL
   mysql -h localhost -P 3306 -u username -p -e "SHOW DATABASES;"
   ```

2. **Create database if needed:**
   ```sql
   -- PostgreSQL
   CREATE DATABASE myapp;
   
   -- MySQL
   CREATE DATABASE myapp;
   ```

3. **Update configuration:**
   ```yaml
   database:
     database: correct_database_name
   ```

### Storage Problems

#### Issue: "Permission denied on storage directory"

**Symptoms:**
```
Error: Storage error: Permission denied: /home/user/.dbranching/snapshots
```

**Solutions:**

1. **Create directory:**
   ```bash
   mkdir -p ~/.dbranching/snapshots
   ```

2. **Fix permissions:**
   ```bash
   chmod 755 ~/.dbranching/snapshots
   chown $USER:$USER ~/.dbranching/snapshots
   ```

3. **Check parent directory permissions:**
   ```bash
   ls -la ~/.dbranching/
   chmod 755 ~/.dbranching/
   ```

#### Issue: "Storage directory not found"

**Symptoms:**
```
Error: Storage error: Directory does not exist: /nonexistent/path
```

**Solutions:**

1. **Check configured path:**
   ```bash
   dbranching config get storage.directory
   ```

2. **Create directory:**
   ```bash
   mkdir -p /path/to/storage/directory
   ```

3. **Update configuration:**
   ```yaml
   storage:
     directory: /correct/path/to/storage
   ```

#### Issue: "No space left on device"

**Symptoms:**
```
Error: Storage error: No space left on device
```

**Solutions:**

1. **Check disk space:**
   ```bash
   df -h ~/.dbranching/snapshots
   du -sh ~/.dbranching/snapshots/*
   ```

2. **Clean old snapshots:**
   ```bash
   # List snapshots by size
   dbranching snapshot list --format=json | jq -r '.[] | "\(.size) \(.name)"' | sort -hr
   
   # Remove old snapshots (not yet implemented - manual cleanup)
   rm ~/.dbranching/snapshots/old-snapshot-*
   ```

3. **Adjust retention policy:**
   ```yaml
   storage:
     retention_days: 7  # Reduce from 30 days
   ```

4. **Use better compression:**
   ```yaml
   storage:
     compression: lzma  # Better compression than gzip
   ```

### Snapshot Operations

#### Issue: "Snapshot creation failed"

**Symptoms:**
```
Error: Snapshot error: Failed to create snapshot 'mysnap'
```

**Solutions:**

1. **Check database connection:**
   ```bash
   dbranching status --verbose
   ```

2. **Test with dry-run:**
   ```bash
   dbranching --dry-run snapshot create test
   ```

3. **Check storage space:**
   ```bash
   df -h ~/.dbranching/snapshots
   ```

4. **Try with verbose output:**
   ```bash
   dbranching --verbose snapshot create debug-snapshot
   ```

#### Issue: "Snapshot not found for restore"

**Symptoms:**
```
Error: Snapshot error: Snapshot 'nonexistent' not found
```

**Solutions:**

1. **List available snapshots:**
   ```bash
   dbranching snapshot list
   ```

2. **Check snapshot name spelling:**
   ```bash
   # Case-sensitive
   dbranching snapshot list | grep -i "partial-name"
   ```

3. **Check storage directory:**
   ```bash
   ls -la ~/.dbranching/snapshots/
   ```

#### Issue: "Snapshot restore failed"

**Symptoms:**
```
Error: Snapshot error: Failed to restore snapshot 'mysnap'
```

**Solutions:**

1. **Check snapshot integrity:**
   ```bash
   # Verify files exist and are readable
   ls -la ~/.dbranching/snapshots/mysnap*
   ```

2. **Test database connection:**
   ```bash
   dbranching status --verbose
   ```

3. **Try with force flag:**
   ```bash
   dbranching snapshot restore mysnap --force
   ```

4. **Check database permissions:**
   - User needs DROP/CREATE permissions for restore operations

### Logging Issues

#### Issue: "Log file permission denied"

**Symptoms:**
```
Error: Configuration error: Cannot write to log file: Permission denied
```

**Solutions:**

1. **Create log directory:**
   ```bash
   mkdir -p ~/.dbranching/logs
   ```

2. **Fix permissions:**
   ```bash
   chmod 755 ~/.dbranching/logs
   touch ~/.dbranching/logs/dbranching.log
   chmod 644 ~/.dbranching/logs/dbranching.log
   ```

3. **Use different log location:**
   ```yaml
   logging:
     file: ./dbranching.log  # Current directory
     # or
     file: null              # Console only
   ```

### Environment Variable Issues

#### Issue: "Environment variable not found"

**Symptoms:**
```
Error: Environment variable 'DB_PASSWORD' not set
```

**Solutions:**

1. **Set environment variable:**
   ```bash
   export DB_PASSWORD='your_password'
   ```

2. **Make persistent in shell profile:**
   ```bash
   echo 'export DB_PASSWORD="your_password"' >> ~/.bashrc
   source ~/.bashrc
   ```

3. **Use .env file (future feature):**
   ```bash
   # Create .env file
   echo 'DB_PASSWORD=your_password' > .env
   ```

4. **Verify variable is set:**
   ```bash
   env | grep DB_PASSWORD
   printenv DB_PASSWORD
   ```

## Installation Problems

### Python Version Issues

#### Issue: "Python 3.10+ required"

**Solutions:**

1. **Check Python version:**
   ```bash
   python --version
   python3 --version
   ```

2. **Install Python 3.10+:**
   ```bash
   # Ubuntu/Debian
   sudo apt install python3.10
   
   # macOS
   brew install python@3.10
   
   # Or use pyenv
   pyenv install 3.10.12
   pyenv local 3.10.12
   ```

### Poetry Issues

#### Issue: "Poetry not found"

**Solutions:**

1. **Install Poetry:**
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. **Add to PATH:**
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   ```

3. **Use full path:**
   ```bash
   ~/.local/bin/poetry install
   ```

#### Issue: "Poetry dependencies conflict"

**Solutions:**

1. **Clear Poetry cache:**
   ```bash
   poetry cache clear pypi --all
   ```

2. **Update lock file:**
   ```bash
   poetry lock --no-update
   poetry install
   ```

3. **Recreate virtual environment:**
   ```bash
   poetry env remove python
   poetry install
   ```

### Database Driver Issues

#### Issue: "No module named 'psycopg2'"

**Solutions:**

1. **Install PostgreSQL driver:**
   ```bash
   # System packages first
   sudo apt install libpq-dev python3-dev  # Ubuntu/Debian
   brew install postgresql                  # macOS
   
   # Then Python package
   poetry add psycopg2-binary
   # or
   pip install psycopg2-binary
   ```

#### Issue: "No module named 'MySQLdb'"

**Solutions:**

1. **Install MySQL driver:**
   ```bash
   # System packages first
   sudo apt install default-libmysqlclient-dev python3-dev  # Ubuntu/Debian
   brew install mysql                                        # macOS
   
   # Then Python package
   poetry add PyMySQL
   # or
   pip install PyMySQL
   ```

## Performance Issues

### Slow Snapshot Creation

**Symptoms:**
- Snapshot creation takes very long
- High CPU or memory usage during snapshots

**Solutions:**

1. **Use faster compression:**
   ```yaml
   storage:
     compression: gzip  # Instead of lzma
   ```

2. **Optimize database connection:**
   ```yaml
   database:
     connection_timeout: 30
     # Add connection pooling (future feature)
   ```

3. **Monitor resource usage:**
   ```bash
   # During snapshot creation
   top -p $(pgrep -f dbranching)
   iostat 1
   ```

### Large Storage Usage

**Solutions:**

1. **Check compression effectiveness:**
   ```bash
   # Compare compressed vs uncompressed sizes
   ls -lh ~/.dbranching/snapshots/
   ```

2. **Optimize compression settings:**
   ```yaml
   storage:
     compression: lzma  # Best compression
   ```

3. **Implement retention policy:**
   ```yaml
   storage:
     retention_days: 14  # Shorter retention
   ```

## Debugging Mode

### Enable Debug Logging

```bash
# Temporary debug mode
export DBRANCHING_LOG_LEVEL=DEBUG
dbranching status

# Or in configuration
dbranching --verbose status
```

### Configuration Debug

```yaml
logging:
  level: DEBUG
  format: structured
  file: debug.log
```

### Trace Database Operations

```bash
# Enable SQL tracing (future feature)
export DBRANCHING_TRACE_SQL=1
dbranching --verbose snapshot create debug-trace
```

## Getting Additional Help

### Collect Diagnostic Information

When reporting issues, include:

1. **System information:**
   ```bash
   uname -a
   python --version
   dbranching --version
   ```

2. **Configuration:**
   ```bash
   dbranching config list --format=yaml
   ```

3. **Status:**
   ```bash
   dbranching status --verbose
   ```

4. **Error messages:**
   ```bash
   dbranching --verbose <failing-command> 2>&1
   ```

5. **Log files:**
   ```bash
   tail -50 ~/.dbranching/logs/dbranching.log
   ```

### Community Support

- **GitHub Issues**: [Report bugs and get help](https://github.com/your-org/dbranching/issues)
- **Discussions**: [Ask questions](https://github.com/your-org/dbranching/discussions)
- **Documentation**: [Full documentation](../README.md)

### Professional Support

For production deployments and enterprise support:
- Contact the maintainers through GitHub
- Consider professional support options
- Review enterprise deployment guides

## Prevention and Best Practices

### Regular Health Checks

```bash
# Weekly health check script
#!/bin/bash
set -e

echo "=== DBranching Health Check ==="
dbranching status --verbose
dbranching config list > /dev/null
du -sh ~/.dbranching/snapshots/
echo "Health check completed successfully"
```

### Monitoring Setup

```bash
# Add to crontab for monitoring
0 9 * * * /path/to/health-check.sh || echo "DBranching health check failed" | mail -s "Alert: DBranching Issue" admin@example.com
```

### Backup Configuration

```bash
# Backup configuration and metadata
tar czf dbranching-backup-$(date +%Y%m%d).tar.gz \
  dbranching.yaml \
  ~/.dbranching/config.yaml \
  ~/.dbranching/logs/ \
  --exclude='~/.dbranching/snapshots/'
```

This troubleshooting guide should help you resolve most common issues. If you encounter problems not covered here, please check the GitHub issues or create a new issue with detailed information about your problem.