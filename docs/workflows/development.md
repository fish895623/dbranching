# Development Workflow

Best practices for using DBranching in development workflows to manage database state, enable safe experimentation, and support collaborative development.

## Overview

DBranching enables database versioning similar to Git branches, allowing developers to:
- Save database states before making changes
- Experiment safely with database modifications
- Switch between different feature states
- Collaborate without database conflicts
- Reset to known-good states quickly

## Basic Development Workflow

### 1. Setup Phase

```bash
# Initialize DBranching in your project
dbranching init

# Configure for your database
# Edit dbranching.yaml with your database settings

# Set database password
export DB_PASSWORD='your_development_password'

# Verify setup
dbranching status --verbose
```

### 2. Create Baseline Snapshot

Before starting any development work:

```bash
# Create a baseline snapshot of clean database
dbranching snapshot create main-baseline \
  --description "Clean main branch database state" \
  --tags "baseline,main"
```

### 3. Feature Development Cycle

For each feature or bug fix:

```bash
# 1. Start from clean baseline
dbranching snapshot restore main-baseline

# 2. Create feature branch snapshot (optional)
dbranching snapshot create feature/user-authentication-start \
  --description "Starting point for user auth feature"

# 3. Develop feature (modify database as needed)
# - Add/modify tables
# - Insert test data
# - Run migrations
# - Test changes

# 4. Save feature state
dbranching snapshot create feature/user-authentication-complete \
  --description "User authentication feature complete" \
  --tags "feature,auth,ready-for-review"

# 5. Test feature
# - Run automated tests
# - Manual testing
# - Performance testing

# 6. Create final snapshot if needed
dbranching snapshot create feature/user-authentication-tested \
  --description "User auth feature - all tests passing" \
  --tags "feature,auth,tested"
```

## Advanced Development Patterns

### A/B Feature Comparison

Compare different implementations of the same feature:

```bash
# Create baseline
dbranching snapshot create feature-comparison-baseline

# Implement approach A
# ... make changes ...
dbranching snapshot create feature/search-algorithm-a \
  --description "Search feature - algorithm A implementation"

# Reset and implement approach B
dbranching snapshot restore feature-comparison-baseline
# ... make different changes ...
dbranching snapshot create feature/search-algorithm-b \
  --description "Search feature - algorithm B implementation"

# Compare performance
dbranching snapshot restore feature/search-algorithm-a
# ... run performance tests ...

dbranching snapshot restore feature/search-algorithm-b
# ... run performance tests ...
```

### Database Schema Evolution

Manage database migrations and schema changes:

```bash
# Before running migrations
dbranching snapshot create before-migration-v2.1 \
  --description "Database state before v2.1 migration" \
  --tags "migration,v2.1,backup"

# Run migrations
python manage.py migrate
# or
npm run migrate
# or
flyway migrate

# After successful migration
dbranching snapshot create after-migration-v2.1 \
  --description "Database state after v2.1 migration" \
  --tags "migration,v2.1,complete"

# If migration fails, rollback
dbranching snapshot restore before-migration-v2.1

# Fix migration and try again
# ... fix migration scripts ...
dbranching snapshot restore before-migration-v2.1
# ... run migration again ...
```

### Collaborative Development

Coordinate database changes between team members:

```bash
# Team lead creates shared baseline
dbranching snapshot create team-sprint-start \
  --description "Sprint 23 starting database state" \
  --tags "sprint-23,baseline,shared"

# Export snapshot for team sharing (future feature)
# dbranching snapshot export team-sprint-start

# Each developer starts from same baseline
dbranching snapshot restore team-sprint-start

# Developer A works on feature
dbranching snapshot create feature/payment-integration \
  --description "Payment system integration" \
  --tags "sprint-23,payments,alice"

# Developer B works on different feature
dbranching snapshot restore team-sprint-start
dbranching snapshot create feature/user-profiles \
  --description "Enhanced user profiles" \
  --tags "sprint-23,profiles,bob"
```

## Integration Testing Workflow

### Multi-Feature Integration

Test multiple features together:

```bash
# Start with baseline
dbranching snapshot restore main-baseline

# Apply feature A changes
# ... restore feature A snapshot or apply changes ...

# Apply feature B changes  
# ... restore feature B snapshot or apply changes ...

# Create integration snapshot
dbranching snapshot create integration/features-a-b \
  --description "Integration of feature A and feature B" \
  --tags "integration,feature-a,feature-b"

# Run integration tests
npm test -- --integration
# or
pytest tests/integration/

# If tests pass
dbranching snapshot create integration/features-a-b-tested \
  --description "Features A+B integration - tests passing" \
  --tags "integration,tested,ready-for-staging"
```

### Database Dependency Testing

Test with different database states:

```bash
# Create snapshots with different data volumes
dbranching snapshot create test-data-small \
  --description "Small dataset for unit tests" \
  --tags "testing,small-data"

dbranching snapshot create test-data-medium \
  --description "Medium dataset for integration tests" \
  --tags "testing,medium-data"

dbranching snapshot create test-data-large \
  --description "Large dataset for performance tests" \
  --tags "testing,large-data,performance"

# Run tests with different data volumes
for size in small medium large; do
  dbranching snapshot restore test-data-$size
  echo "Testing with $size dataset..."
  npm test -- --suite $size
done
```

## Debugging Workflows

### Bug Investigation

Isolate and debug database-related issues:

```bash
# Create snapshot at bug occurrence
dbranching snapshot create bug/user-login-issue \
  --description "Database state when user login bug occurred" \
  --tags "bug,login,investigation"

# Try various debugging approaches
dbranching snapshot restore bug/user-login-issue

# Examine data
dbranching snapshot restore bug/user-login-issue
# ... run queries to investigate ...

# Test potential fixes
# ... modify data to test hypothesis ...
dbranching snapshot create bug/user-login-potential-fix-1 \
  --description "Testing potential fix for login bug"

# If fix doesn't work, try another approach
dbranching snapshot restore bug/user-login-issue
# ... try different fix ...
```

### Performance Debugging

Debug performance issues with consistent data:

```bash
# Create snapshot for performance testing
dbranching snapshot create perf/baseline-large-dataset \
  --description "Large dataset for performance testing" \
  --tags "performance,baseline,large-data"

# Test different query optimizations
dbranching snapshot restore perf/baseline-large-dataset
# ... run performance test with current queries ...
# ... record results ...

dbranching snapshot restore perf/baseline-large-dataset
# ... apply query optimization ...
# ... run performance test again ...
# ... compare results ...
```

## Development Environment Management

### Multiple Database Versions

Work with different database versions:

```bash
# PostgreSQL 13 environment
export DBRANCHING_DATABASE_HOST=postgres13-dev
dbranching snapshot create postgres13-baseline \
  --description "Baseline for PostgreSQL 13 development"

# PostgreSQL 14 environment  
export DBRANCHING_DATABASE_HOST=postgres14-dev
dbranching snapshot create postgres14-baseline \
  --description "Baseline for PostgreSQL 14 development"

# Test compatibility
dbranching --config-file pg13.yaml snapshot restore postgres13-baseline
# ... run tests ...

dbranching --config-file pg14.yaml snapshot restore postgres14-baseline
# ... run tests ...
```

### Environment-Specific Configurations

```bash
# Development environment
dbranching --config-file dev.yaml snapshot create dev-feature-complete

# Staging environment  
dbranching --config-file staging.yaml snapshot restore staging-baseline
dbranching --config-file staging.yaml snapshot create staging-pre-deploy

# Production-like environment
dbranching --config-file prod-like.yaml snapshot restore prod-baseline
dbranching --config-file prod-like.yaml snapshot create prod-like-tested
```

## Best Practices

### Naming Conventions

Use consistent naming patterns:

```bash
# Environment prefixes
dbranching snapshot create dev-feature-auth-complete
dbranching snapshot create staging-release-v2.1
dbranching snapshot create prod-hotfix-login-bug

# Feature categories
dbranching snapshot create feature/user-management
dbranching snapshot create bugfix/payment-processing
dbranching snapshot create hotfix/security-patch

# Time-based snapshots
dbranching snapshot create daily-$(date +%Y%m%d)
dbranching snapshot create weekly-$(date +%Y-W%U)
```

### Tagging Strategy

Use tags for organization and filtering:

```bash
# Feature tags
--tags "feature,authentication,backend"
--tags "frontend,ui,user-experience"

# Status tags
--tags "ready-for-review,tested"
--tags "work-in-progress,experimental"

# Environment tags
--tags "development,local"
--tags "staging,integration-testing"

# Priority tags
--tags "critical,hotfix"
--tags "nice-to-have,future"
```

### Cleanup Strategy

Keep snapshots organized:

```bash
# List snapshots by age
dbranching snapshot list --format=json | \
  jq -r '.[] | "\(.created) \(.name)"' | sort

# Regular cleanup (manual until automated cleanup is implemented)
# Remove old development snapshots
for snap in $(dbranching snapshot list --format=simple | grep "dev-temp"); do
  # Manual removal (future: dbranching snapshot delete $snap)
  echo "Consider removing old snapshot: $snap"
done

# Keep important snapshots tagged
dbranching snapshot create important-milestone \
  --tags "keep,milestone,important"
```

## Automation Scripts

### Daily Development Setup

```bash
#!/bin/bash
# daily-dev-setup.sh

set -e

echo "=== Daily Development Setup ==="

# Ensure we have a fresh baseline
if ! dbranching snapshot list --format=simple | grep -q "main-baseline"; then
    echo "Creating main baseline..."
    dbranching snapshot create main-baseline \
      --description "Main branch baseline - $(date +%Y-%m-%d)"
fi

# Start from clean state
echo "Restoring to baseline..."
dbranching snapshot restore main-baseline --force

echo "Development environment ready!"
dbranching status
```

### Feature Completion Script

```bash
#!/bin/bash
# feature-complete.sh

FEATURE_NAME=$1
if [ -z "$FEATURE_NAME" ]; then
    echo "Usage: $0 <feature-name>"
    exit 1
fi

set -e

# Create completion snapshot
dbranching snapshot create "feature/$FEATURE_NAME-complete" \
  --description "Feature $FEATURE_NAME development complete" \
  --tags "feature,complete,ready-for-review"

# Run tests
echo "Running tests..."
npm test

# Create tested snapshot
dbranching snapshot create "feature/$FEATURE_NAME-tested" \
  --description "Feature $FEATURE_NAME - all tests passing" \
  --tags "feature,tested,ready-for-merge"

echo "Feature $FEATURE_NAME is ready for code review!"
```

### Integration Test Script

```bash
#!/bin/bash
# integration-test.sh

set -e

FEATURES=("user-auth" "payment-system" "notifications")
BASELINE="main-baseline"

echo "=== Integration Testing ==="

# Start from baseline
dbranching snapshot restore $BASELINE --force

# Apply each feature
for feature in "${FEATURES[@]}"; do
    echo "Integrating feature: $feature"
    # This would restore the feature snapshot or apply changes
    # dbranching snapshot restore "feature/$feature-tested"
    
    # Run incremental tests
    echo "Testing after $feature integration..."
    npm test -- --suite incremental
done

# Create integration snapshot
INTEGRATION_NAME="integration-$(date +%Y%m%d)-$(echo "${FEATURES[@]}" | tr ' ' '-')"
dbranching snapshot create "$INTEGRATION_NAME" \
  --description "Integration of: $(echo "${FEATURES[@]}" | tr ' ' ', ')" \
  --tags "integration,$(date +%Y%m%d),tested"

echo "Integration testing complete: $INTEGRATION_NAME"
```

## Troubleshooting Development Issues

### Common Development Problems

**Problem: Lost database state during development**
```bash
# Solution: Check recent snapshots
dbranching snapshot list | head -5

# Restore to most recent relevant snapshot
dbranching snapshot restore feature/my-work-latest
```

**Problem: Need to test feature with clean data**
```bash
# Solution: Create and use a clean data snapshot
dbranching snapshot create clean-test-data \
  --description "Clean dataset for testing"

# Before each test
dbranching snapshot restore clean-test-data
```

**Problem: Conflicting database changes between developers**
```bash
# Solution: Use separate feature snapshots
dbranching snapshot create feature/developer-a-work
dbranching snapshot create feature/developer-b-work

# Merge testing
dbranching snapshot restore main-baseline
# Apply A's changes, then B's changes, resolve conflicts
```

### Development Debugging

Enable debug mode for development issues:

```bash
# Enable verbose logging
export DBRANCHING_LOG_LEVEL=DEBUG
dbranching --verbose snapshot create debug-snapshot

# Check status thoroughly
dbranching status --verbose

# Test configuration
dbranching config list --format=yaml
```

## Conclusion

DBranching provides powerful database state management for development workflows. Key benefits:

- **Safe experimentation** - Try changes without fear
- **Easy rollback** - Return to known-good states instantly
- **Better collaboration** - Team members work with consistent data
- **Debugging support** - Reproduce issues with exact database states
- **Testing reliability** - Consistent test data between runs

Start with simple snapshot creation and restoration, then gradually adopt more advanced patterns as your team becomes comfortable with database state management.