# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- PyPI packaging and distribution system
- Cross-platform support (Windows, macOS, Linux)
- Python 3.8+ compatibility
- Optional database driver dependencies
- Additional CLI entry point (`dbbranch` alias)
- Security scanning with bandit and safety
- Type hint support with py.typed marker
- Automated CI/CD pipeline with GitHub Actions
- Installation verification scripts

### Changed
- Updated dependency version constraints for broader compatibility
- Enhanced Poetry configuration for PyPI publishing
- Improved security and quality tooling

## [0.1.0] - 2025-08-30

### Added
- Initial release
- Database snapshot management for PostgreSQL, MySQL, and SQLite
- CLI interface with comprehensive command set
- Configuration management with YAML/JSON support
- Git hook integration for automated snapshots
- Compression and storage management
- Comprehensive test suite
- Performance benchmarking
- Error handling and logging system

### Features
- Create and restore database snapshots
- Multi-database support with async operations  
- Flexible storage backends with compression
- Git workflow integration
- Structured logging with multiple formats
- Configuration validation and management
- Progress tracking for long operations
- Metadata management for snapshots