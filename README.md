# DBranching

Database branching and snapshot management tool for development workflows.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)

## Overview

DBranching enables database versioning and snapshot management similar to Git branches but for database state. Create, restore, and manage database snapshots to support development workflows, testing, and rollback scenarios.

## Features

- **Database Snapshots**: Create and restore database snapshots with metadata
- **Multi-Database Support**: PostgreSQL, MySQL, and SQLite support
- **Flexible Storage**: Configurable storage with compression options
- **Configuration Management**: YAML/JSON configuration with environment variable overrides
- **CLI Interface**: Comprehensive command-line interface with contextual help
- **Logging**: Structured logging with multiple output formats

## Quick Start

### Installation

```bash
# Install via Poetry (recommended for development)
poetry install

# Or install from source
pip install -e .
```

### Initialize

```bash
# Initialize dbranching in your project
dbranching init

# This creates a default dbranching.yaml config file
```

### Basic Usage

```bash
# Show current status
dbranching status

# View configuration
dbranching config list

# Create a snapshot
dbranching snapshot create dev-feature --description "Feature development state"

# List snapshots
dbranching snapshot list

# Restore a snapshot
dbranching snapshot restore dev-feature
```

## Installation

### Requirements

- Python 3.10+
- Database drivers for your target database:
  - PostgreSQL: `psycopg2-binary` or `asyncpg`
  - MySQL: `PyMySQL` or `mysql-connector-python`
  - SQLite: Built-in (no additional dependencies)

### Install from Source

```bash
# Clone the repository
git clone https://github.com/your-org/dbranching.git
cd dbranching

# Install with Poetry
poetry install

# Or install with pip
pip install -e .
```

### Development Installation

```bash
# Install with development dependencies
poetry install --with dev

# Run tests
poetry run pytest

# Run type checking
poetry run mypy src/

# Format code
poetry run black src/ tests/
poetry run isort src/ tests/
```

## Configuration

### Configuration File

DBranching looks for configuration files in the following order:

1. `dbranching.yaml` (current directory)
2. `dbranching.yml` (current directory)
3. `dbranching.json` (current directory)
4. `~/.dbranching/config.yaml`
5. `~/.dbranching/config.yml`
6. `~/.dbranching/config.json`

### Configuration Schema

```yaml
database:
  type: postgresql          # postgresql, mysql, or sqlite
  host: localhost
  port: 5432
  database: myapp
  username: user
  password_env: DB_PASSWORD # Environment variable for password

storage:
  directory: ~/.dbranching/snapshots
  compression: gzip         # none, gzip, bzip2, or lzma
  retention_days: 30

logging:
  level: INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: structured       # structured, simple, or json
  file: ~/.dbranching/logs/dbranching.log
```

### Environment Variables

Override configuration with environment variables using the `DBRANCHING_` prefix:

```bash
export DBRANCHING_DATABASE_HOST=production.db.example.com
export DBRANCHING_DATABASE_PORT=5432
export DBRANCHING_LOG_LEVEL=DEBUG
export DB_PASSWORD=your_secure_password
```

## Commands

### Global Options

- `--config-file, -c`: Path to configuration file
- `--verbose, -v`: Enable verbose output
- `--dry-run`: Show what would be done without executing
- `--help`: Show help message

### Initialize

```bash
dbranching init [OPTIONS]

# Initialize with default configuration
dbranching init

# Force reinitialize existing setup
dbranching init --force
```

### Configuration Management

```bash
# List current configuration
dbranching config list
dbranching config list --format=yaml
dbranching config list --format=json

# Get specific configuration value
dbranching config get database.host
dbranching config get logging.level

# Set configuration value (not yet implemented)
dbranching config set database.host localhost
```

### Snapshot Management

```bash
# Create snapshot
dbranching snapshot create <name> [OPTIONS]
dbranching snapshot create dev-feature
dbranching snapshot create v1.0 --description "Release version"
dbranching snapshot create test --tags "testing,feature-x"

# List snapshots
dbranching snapshot list [OPTIONS]
dbranching snapshot list --filter "dev*"
dbranching snapshot list --format json

# Restore snapshot
dbranching snapshot restore <name> [OPTIONS]
dbranching snapshot restore dev-feature
dbranching snapshot restore v1.0 --force
dbranching snapshot restore test --confirm
```

### Status Information

```bash
# Show basic status
dbranching status

# Show detailed status
dbranching status --verbose
```

## Examples

### Development Workflow

```bash
# 1. Initialize project
dbranching init

# 2. Create baseline snapshot
dbranching snapshot create main --description "Production baseline"

# 3. Start feature development
# ... make database changes ...

# 4. Create feature snapshot
dbranching snapshot create feature/user-auth --description "User authentication feature"

# 5. Test and iterate
dbranching snapshot restore main  # Reset to baseline
dbranching snapshot restore feature/user-auth  # Back to feature state

# 6. List all snapshots
dbranching snapshot list
```

### Configuration Examples

#### PostgreSQL with Custom Settings

```yaml
database:
  type: postgresql
  host: localhost
  port: 5432
  database: myapp_dev
  username: developer
  password_env: DEV_DB_PASSWORD

storage:
  directory: ./db-snapshots
  compression: lzma
  retention_days: 7

logging:
  level: DEBUG
  format: json
  file: ./logs/dbranching.log
```

#### SQLite for Local Development

```yaml
database:
  type: sqlite
  database: ./dev.db
  # host, port, username not needed for SQLite

storage:
  directory: ./snapshots
  compression: gzip
  retention_days: 14

logging:
  level: INFO
  format: simple
  file: null  # Log to console only
```

#### MySQL Production Setup

```yaml
database:
  type: mysql
  host: mysql.production.com
  port: 3306
  database: production_app
  username: app_user
  password_env: MYSQL_PASSWORD

storage:
  directory: /var/backups/dbranching
  compression: bzip2
  retention_days: 90

logging:
  level: WARNING
  format: structured
  file: /var/log/dbranching/app.log
```

## Error Handling

DBranching provides detailed error messages with appropriate exit codes:

- **Exit Code 1**: General application error
- **Exit Code 2**: Configuration error
- **Exit Code 3**: Database connection error
- **Exit Code 4**: Snapshot operation error
- **Exit Code 5**: Validation error
- **Exit Code 6**: Storage error

### Common Issues

#### Database Connection Failed

```bash
# Check configuration
dbranching config get database.host
dbranching config get database.port

# Test with verbose output
dbranching status --verbose

# Verify password environment variable
echo $DB_PASSWORD
```

#### Permission Denied on Storage Directory

```bash
# Check storage configuration
dbranching config get storage.directory

# Create directory with correct permissions
mkdir -p ~/.dbranching/snapshots
chmod 755 ~/.dbranching/snapshots
```

#### Configuration File Not Found

```bash
# Initialize creates default configuration
dbranching init

# Or specify custom config file
dbranching --config-file /path/to/config.yaml status
```

## Development

### Project Structure

```
src/dbranching/
├── __init__.py          # Package initialization and exports
├── cli.py              # Main CLI interface and commands
├── config.py           # Configuration management
└── exceptions.py       # Custom exceptions

tests/
├── test_cli.py         # CLI command tests
├── test_config.py      # Configuration tests
└── test_exceptions.py  # Exception tests
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=dbranching --cov-report=html

# Run specific test file
poetry run pytest tests/test_config.py

# Run with verbose output
poetry run pytest -v
```

### Code Quality

```bash
# Type checking
poetry run mypy src/

# Code formatting
poetry run black src/ tests/
poetry run isort src/ tests/

# Linting
poetry run flake8 src/ tests/
```

### Adding Database Support

To add support for a new database type:

1. Add the database type to `DatabaseConfig.type` enum in `config.py`
2. Update validation in `DatabaseConfig.validate_database_type`
3. Implement database-specific operations (not yet implemented)
4. Add tests for the new database type
5. Update documentation

## Troubleshooting

### Enable Debug Logging

```bash
# Set debug level in config file
dbranching config list | grep level

# Or use environment variable
export DBRANCHING_LOG_LEVEL=DEBUG
dbranching status
```

### Validate Configuration

```bash
# Check configuration file syntax
dbranching config list --format=yaml

# Test database connection
dbranching status --verbose
```

### Clean Installation

```bash
# Remove configuration and data
rm -rf ~/.dbranching/

# Remove local config
rm -f dbranching.yaml dbranching.yml dbranching.json

# Reinitialize
dbranching init
```

## Security Considerations

- **Passwords**: Always use environment variables for database passwords
- **File Permissions**: Ensure configuration files have appropriate permissions (600)
- **Network Security**: Use encrypted connections for remote databases
- **Backup Security**: Secure snapshot storage directories appropriately

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests for new functionality
5. Run tests and linting (`poetry run pytest && poetry run mypy src/`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write comprehensive tests
- Update documentation for new features
- Use semantic commit messages

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/your-org/dbranching/issues)
- **Documentation**: This README and inline help (`dbranching --help`)
- **Development**: See [Contributing](#contributing) section

## Roadmap

- [ ] Database snapshot creation and restoration
- [ ] Support for additional database types
- [ ] Snapshot metadata and tagging
- [ ] Automated snapshot cleanup
- [ ] Integration with CI/CD pipelines
- [ ] Web interface for snapshot management
- [ ] Incremental snapshots
- [ ] Snapshot compression optimization
- [ ] Database migration integration
- [ ] Team collaboration features