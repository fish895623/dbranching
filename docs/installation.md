# Installation Guide

This guide provides detailed installation instructions for DBranching across different platforms and deployment scenarios.

## Quick Installation

### Prerequisites

- Python 3.10 or higher
- Poetry (recommended) or pip
- Database drivers for your target database

### Install via Poetry (Recommended)

```bash
# Clone the repository
git clone https://github.com/your-org/dbranching.git
cd dbranching

# Install with Poetry
poetry install

# Activate the virtual environment  
poetry shell

# Verify installation
dbranching --help
```

### Install via pip

```bash
# Install from source
git clone https://github.com/your-org/dbranching.git
cd dbranching
pip install -e .

# Or install from PyPI (when available)
pip install dbranching
```

## Platform-Specific Instructions

### Linux (Ubuntu/Debian)

```bash
# Install Python 3.10+ if not available
sudo apt update
sudo apt install python3.10 python3.10-venv python3-pip

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add Poetry to PATH
export PATH="$HOME/.local/bin:$PATH"

# Install DBranching
git clone https://github.com/your-org/dbranching.git
cd dbranching
poetry install
```

### Linux (CentOS/RHEL/Fedora)

```bash
# Install Python 3.10+ if not available
sudo dnf install python3.10 python3-pip

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add Poetry to PATH
export PATH="$HOME/.local/bin:$PATH"

# Install DBranching
git clone https://github.com/your-org/dbranching.git
cd dbranching
poetry install
```

### macOS

```bash
# Install Python 3.10+ via Homebrew
brew install python@3.10

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add Poetry to PATH
export PATH="$HOME/.local/bin:$PATH"

# Install DBranching
git clone https://github.com/your-org/dbranching.git
cd dbranching
poetry install
```

### Windows

#### Using PowerShell

```powershell
# Install Python 3.10+ from python.org or Microsoft Store
# Download and install Poetry from https://python-poetry.org/docs/#installation

# Clone and install
git clone https://github.com/your-org/dbranching.git
cd dbranching
poetry install
```

#### Using Windows Subsystem for Linux (WSL)

```bash
# Follow Linux instructions inside WSL
# This is often easier than native Windows installation
```

## Database Drivers

DBranching requires specific database drivers depending on your database type.

### PostgreSQL

```bash
# Using Poetry
poetry add psycopg2-binary

# Or for async support
poetry add asyncpg

# Using pip
pip install psycopg2-binary
# or
pip install asyncpg
```

### MySQL

```bash
# Using Poetry
poetry add PyMySQL
# or
poetry add mysql-connector-python

# Using pip
pip install PyMySQL
# or
pip install mysql-connector-python
```

### SQLite

SQLite support is built into Python - no additional drivers needed.

## Development Installation

For contributors and developers who want to work on DBranching itself:

```bash
# Clone the repository
git clone https://github.com/your-org/dbranching.git
cd dbranching

# Install with development dependencies
poetry install --with dev

# Install pre-commit hooks
poetry run pre-commit install

# Run tests to verify setup
poetry run pytest

# Run type checking
poetry run mypy src/

# Run linting
poetry run flake8 src/ tests/
```

### Development Dependencies

The development installation includes:

- **pytest**: Testing framework
- **pytest-cov**: Coverage reporting
- **mypy**: Static type checking
- **black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **pre-commit**: Git hooks

## Docker Installation

### Using Docker Compose

Create a `docker-compose.yml` file:

```yaml
version: '3.8'
services:
  dbranching:
    build: .
    volumes:
      - ./config:/config
      - ./snapshots:/snapshots
    environment:
      - DBRANCHING_DATABASE_HOST=postgres
      - DBRANCHING_DATABASE_PORT=5432
      - DBRANCHING_DATABASE_NAME=myapp
      - DBRANCHING_DATABASE_USERNAME=user
      - DB_PASSWORD=password
    depends_on:
      - postgres

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Run with:

```bash
docker-compose up -d
docker-compose exec dbranching dbranching init
```

### Standalone Docker

```bash
# Build the image
docker build -t dbranching .

# Run with mounted volumes
docker run -it --rm \
  -v $(pwd)/config:/config \
  -v $(pwd)/snapshots:/snapshots \
  -e DBRANCHING_DATABASE_HOST=host.docker.internal \
  -e DB_PASSWORD=your_password \
  dbranching dbranching --help
```

## System Service Installation

### Linux systemd Service

Create `/etc/systemd/system/dbranching.service`:

```ini
[Unit]
Description=DBranching Database Snapshot Service
After=network.target postgresql.service

[Service]
Type=oneshot
User=dbranching
Group=dbranching
WorkingDirectory=/opt/dbranching
Environment=PATH=/opt/dbranching/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=DB_PASSWORD=your_secure_password
ExecStart=/opt/dbranching/.venv/bin/dbranching snapshot create auto-$(date +%Y%m%d-%H%M%S)
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable dbranching.service
sudo systemctl start dbranching.service
```

### Cron Job Setup

Add to crontab for regular snapshots:

```bash
# Edit crontab
crontab -e

# Add entry for daily snapshots at 2 AM
0 2 * * * /usr/local/bin/dbranching snapshot create daily-$(date +\%Y\%m\%d) >/var/log/dbranching.log 2>&1
```

## Configuration

After installation, initialize DBranching:

```bash
# Create default configuration
dbranching init

# Edit configuration file
nano dbranching.yaml

# Set database password
export DB_PASSWORD='your_secure_password'

# Test configuration
dbranching status --verbose
```

## Troubleshooting Installation

### Common Issues

#### Python Version Conflicts

```bash
# Check Python version
python3 --version

# Use specific Python version with Poetry
poetry env use python3.10
```

#### Permission Issues

```bash
# Fix Poetry installation permissions
chmod +x ~/.local/bin/poetry

# Fix dbranching directory permissions
sudo chown -R $USER:$USER ~/.dbranching/
```

#### Database Driver Issues

```bash
# PostgreSQL on Ubuntu/Debian
sudo apt install libpq-dev python3-dev

# MySQL on Ubuntu/Debian  
sudo apt install default-libmysqlclient-dev python3-dev

# Then reinstall drivers
poetry install --extras database
```

#### Poetry Not Found

```bash
# Add Poetry to PATH permanently
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Or use the full path
~/.local/bin/poetry install
```

### Verification Steps

After installation, verify everything works:

```bash
# 1. Check dbranching is available
dbranching --version

# 2. Test configuration
dbranching init
dbranching config list

# 3. Test database connection
dbranching status --verbose

# 4. Run development tests (if installed with --dev)
poetry run pytest -v
```

### Getting Help

If you encounter installation issues:

1. Check the [troubleshooting guide](troubleshooting.md)
2. Search existing [GitHub Issues](https://github.com/your-org/dbranching/issues)
3. Create a new issue with:
   - Your operating system and version
   - Python version
   - Complete error message
   - Installation method used

## Upgrading

### From Source

```bash
# Pull latest changes
git pull origin main

# Reinstall
poetry install

# Update configuration if needed
dbranching init --force
```

### From PyPI (when available)

```bash
# Upgrade to latest version
pip install --upgrade dbranching

# Or with Poetry
poetry update dbranching
```

### Migration Notes

When upgrading between major versions, check the [changelog](CHANGELOG.md) for breaking changes and migration instructions.

## Uninstalling

### Remove Python Package

```bash
# If installed with Poetry
poetry uninstall

# If installed with pip
pip uninstall dbranching
```

### Remove Configuration and Data

```bash
# Remove user configuration and snapshots
rm -rf ~/.dbranching/

# Remove project configuration
rm -f dbranching.yaml dbranching.yml dbranching.json
```

### Remove System Services

```bash
# Remove systemd service
sudo systemctl stop dbranching.service
sudo systemctl disable dbranching.service
sudo rm /etc/systemd/system/dbranching.service

# Remove cron jobs
crontab -e
# Delete dbranching lines
```

## Next Steps

After successful installation:

1. Read the [Quick Start Guide](../README.md#quick-start)
2. Configure your database connection
3. Create your first snapshot
4. Explore the [workflow examples](workflows/)

## Support

- **Documentation**: [README](../README.md) and [docs](/)
- **Issues**: [GitHub Issues](https://github.com/your-org/dbranching/issues)  
- **Discussions**: [GitHub Discussions](https://github.com/your-org/dbranching/discussions)