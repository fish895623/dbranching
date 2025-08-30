# Release Process

This document outlines the release process for dbranching.

## Pre-Release Checklist

### Code Quality
- [ ] All tests pass across supported Python versions (3.8-3.12)
- [ ] Code coverage meets minimum threshold (>90%)
- [ ] Type checking passes with mypy
- [ ] Linting passes with flake8, black, isort
- [ ] Security scanning passes (bandit, safety, semgrep)

### Documentation
- [ ] CHANGELOG.md updated with all changes
- [ ] README.md installation instructions verified
- [ ] All new features documented
- [ ] API documentation updated (if applicable)

### Testing
- [ ] Manual testing on supported platforms (Windows, macOS, Linux)
- [ ] Installation testing with pip install
- [ ] Database compatibility testing (PostgreSQL, MySQL, SQLite)
- [ ] CLI commands tested manually
- [ ] Docker image builds and runs correctly

## Version Management

### Semantic Versioning

We follow [Semantic Versioning](https://semver.org/) (semver):

- **Major version** (X.0.0): Breaking changes
- **Minor version** (0.X.0): New features, backward compatible
- **Patch version** (0.0.X): Bug fixes, backward compatible

### Version Bumping

1. **Update version in pyproject.toml:**
   ```toml
   [tool.poetry]
   version = "X.Y.Z"
   ```

2. **Update version in src/dbranching/__init__.py:**
   ```python
   __version__ = "X.Y.Z"
   ```

3. **Update CHANGELOG.md:**
   - Move items from [Unreleased] to new version section
   - Add release date
   - Create new [Unreleased] section

## Release Steps

### 1. Prepare Release Branch

```bash
# Checkout main branch and pull latest
git checkout main
git pull origin main

# Create release branch
git checkout -b release/vX.Y.Z
```

### 2. Update Version and Documentation

```bash
# Update version numbers (see Version Management above)
# Update CHANGELOG.md
# Commit changes
git add .
git commit -m "chore: prepare release vX.Y.Z"
```

### 3. Final Testing

```bash
# Run full test suite
poetry run pytest tests/ -v

# Run security checks  
poetry run bandit -r src/
poetry run safety check

# Build and test package
poetry build
poetry run twine check dist/*

# Test installation from built wheel
pip install dist/dbranching-X.Y.Z-py3-none-any.whl
dbranching --version
dbbranch --version
```

### 4. Create Release PR

```bash
# Push release branch
git push origin release/vX.Y.Z

# Create PR to main branch
# Title: "Release vX.Y.Z"
# Include release notes in description
```

### 5. Merge and Tag

After PR is approved and merged:

```bash
# Checkout main and pull
git checkout main
git pull origin main

# Create and push tag
git tag -a vX.Y.Z -m "Release version X.Y.Z"
git push origin vX.Y.Z
```

### 6. Automated Release

The tag push triggers automated GitHub Actions:

1. **Build and Test**: Full test suite across all platforms
2. **Security Scan**: Comprehensive security analysis  
3. **PyPI Publishing**: Automated upload to PyPI
4. **Docker Image**: Multi-architecture container build
5. **GitHub Release**: Automated release notes generation

### 7. Verify Release

```bash
# Test PyPI installation
pip install --upgrade dbranching==X.Y.Z
dbranching --version

# Test Docker image
docker run --rm fish895623/dbranching:X.Y.Z --version

# Verify GitHub release created
# Check release notes accuracy
```

## Post-Release

### 1. Update Development Dependencies

```bash
# Bump to next development version
# Update pyproject.toml version to X.Y.(Z+1)-dev
# Update __init__.py version

git add .
git commit -m "chore: bump version to X.Y.(Z+1)-dev"
git push origin main
```

### 2. Monitor Release

- Watch for PyPI download metrics
- Monitor GitHub issues for release-related problems
- Check Docker Hub pull statistics
- Review security scan results

### 3. Communicate Release

- Update project README if needed
- Announce on relevant channels (if applicable)
- Close milestone in issue tracker
- Update project status badges

## Emergency Hotfix Process

For critical bugs requiring immediate release:

### 1. Create Hotfix Branch

```bash
# Branch from main (or specific release tag)
git checkout main  # or vX.Y.Z tag
git checkout -b hotfix/vX.Y.(Z+1)
```

### 2. Make Minimal Fix

- Fix only the critical issue
- Add test to prevent regression
- Update CHANGELOG.md

### 3. Test and Release

```bash
# Minimal testing focused on the fix
poetry run pytest tests/ -k "test_specific_issue"

# Follow normal release process
# Increment patch version only
```

### 4. Backport if Needed

- Consider if fix needs backporting to older versions
- Create separate hotfix branches for supported versions

## Release Automation

### GitHub Actions Workflows

1. **CI Pipeline** (`.github/workflows/ci.yml`):
   - Runs on every push and PR
   - Cross-platform testing
   - Security scanning
   - Build verification

2. **Release Pipeline** (`.github/workflows/release.yml`):
   - Triggered by version tags (vX.Y.Z)
   - Comprehensive testing
   - PyPI publishing with trusted publishing
   - Docker image creation
   - GitHub release generation

### PyPI Configuration

- Uses GitHub's trusted publishing (no API tokens needed)
- Publishes both wheel and source distributions
- Includes all metadata and classifiers

### Docker Configuration

- Multi-architecture builds (amd64, arm64)
- Publishes to Docker Hub with version tags
- Includes latest tag for newest stable release

## Troubleshooting Releases

### Failed PyPI Upload

1. Check trusted publishing configuration
2. Verify package metadata with `twine check`
3. Ensure version not already published
4. Check for PyPI service issues

### Failed Docker Build  

1. Verify Dockerfile syntax
2. Check base image availability
3. Test build locally with same args
4. Review Docker Hub service status

### Failed Tests

1. Review test failure logs
2. Test locally with same environment
3. Check for flaky tests
4. Verify database service health

### Version Conflicts

1. Check all version references updated
2. Verify git tags are correct
3. Ensure CHANGELOG.md is accurate
4. Review packaging metadata

## Security Considerations

- Never commit API tokens or secrets
- Use trusted publishing for PyPI
- Sign git tags for releases
- Monitor security advisories for dependencies
- Keep security scanning tools updated