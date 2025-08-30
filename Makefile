# DBranching Makefile
# Provides convenient commands for development and testing

.PHONY: help install test test-unit test-integration test-performance test-all test-fast test-slow
.PHONY: coverage lint format type-check quality docker-up docker-down clean benchmark
.PHONY: install-dev update-deps build docs serve-docs

# Default target
help:
	@echo "DBranching Development Commands"
	@echo "=============================="
	@echo ""
	@echo "Setup & Installation:"
	@echo "  install          Install production dependencies"
	@echo "  install-dev      Install development dependencies"
	@echo "  update-deps      Update all dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  test             Run all tests with coverage"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  test-performance Run performance tests only"
	@echo "  test-fast        Run fast tests (exclude slow/performance)"
	@echo "  test-slow        Run slow tests (include performance)"
	@echo "  coverage         Generate coverage report and open HTML"
	@echo "  benchmark        Run performance benchmarks"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint             Run all linters"
	@echo "  format           Format code with black and isort"
	@echo "  type-check       Run mypy type checking"
	@echo "  quality          Run all quality checks"
	@echo ""
	@echo "Docker:"
	@echo "  docker-up        Start test databases"
	@echo "  docker-down      Stop test databases"
	@echo ""
	@echo "Utilities:"
	@echo "  clean            Clean up generated files and caches"
	@echo "  build            Build package"
	@echo "  docs             Build documentation"
	@echo "  serve-docs       Serve documentation locally"

# Installation commands
install:
	poetry install --only=main

install-dev:
	poetry install

update-deps:
	poetry update

# Testing commands
test: clean
	@echo "Running all tests with coverage..."
	poetry run python scripts/test_runner.py --mode=all --coverage --verbose

test-unit:
	@echo "Running unit tests..."
	poetry run python scripts/test_runner.py --mode=unit --coverage --verbose

test-integration:
	@echo "Running integration tests..."
	poetry run python scripts/test_runner.py --mode=integration --verbose --docker

test-performance:
	@echo "Running performance tests..."
	poetry run python scripts/test_runner.py --mode=performance --verbose --benchmark

test-fast:
	@echo "Running fast tests..."
	poetry run python scripts/test_runner.py --mode=fast --coverage --parallel=4

test-slow:
	@echo "Running slow tests..."
	poetry run python scripts/test_runner.py --mode=slow --verbose

coverage:
	@echo "Generating coverage report..."
	poetry run python scripts/test_runner.py --mode=all --coverage
	@if [ -f htmlcov/index.html ]; then \
		echo "Opening coverage report..."; \
		python -m webbrowser htmlcov/index.html; \
	fi

benchmark:
	@echo "Running performance benchmarks..."
	poetry run python scripts/test_runner.py --mode=performance --benchmark --docker

# Code quality commands
lint:
	@echo "Running flake8 linter..."
	poetry run flake8 src/ tests/

format:
	@echo "Formatting code with black and isort..."
	poetry run black src/ tests/ scripts/
	poetry run isort src/ tests/ scripts/

type-check:
	@echo "Running mypy type checking..."
	poetry run mypy src/dbranching

quality: format lint type-check
	@echo "All quality checks completed."

# Docker commands
docker-up:
	@echo "Starting test databases..."
	docker compose -f docker-compose.test.yml up -d
	@echo "Waiting for databases to be ready..."
	sleep 10

docker-down:
	@echo "Stopping test databases..."
	docker compose -f docker-compose.test.yml down

docker-clean: docker-down
	@echo "Cleaning up Docker volumes..."
	docker compose -f docker-compose.test.yml down -v
	docker system prune -f

# Utility commands
clean:
	@echo "Cleaning up generated files..."
	rm -rf htmlcov/
	rm -f coverage.xml .coverage
	rm -rf .pytest_cache/
	rm -f benchmark_results.json
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

build:
	@echo "Building package..."
	poetry build

docs:
	@echo "Building documentation..."
	@if [ -d "docs/" ]; then \
		cd docs && make html; \
	else \
		echo "Documentation directory not found"; \
	fi

serve-docs:
	@echo "Serving documentation locally..."
	@if [ -d "docs/_build/html" ]; then \
		cd docs/_build/html && python -m http.server 8000; \
	else \
		echo "Documentation not built. Run 'make docs' first."; \
	fi

# Database-specific testing
test-sqlite:
	@echo "Running tests with SQLite..."
	poetry run python scripts/test_runner.py --database=sqlite --coverage

test-mysql: docker-up
	@echo "Running tests with MySQL..."
	poetry run python scripts/test_runner.py --database=mysql --coverage
	$(MAKE) docker-down

test-postgresql: docker-up
	@echo "Running tests with PostgreSQL..."
	poetry run python scripts/test_runner.py --database=postgresql --coverage
	$(MAKE) docker-down

test-all-databases: docker-up
	@echo "Running tests with all databases..."
	poetry run python scripts/test_runner.py --database=all --coverage
	$(MAKE) docker-down

# Continuous integration commands
ci-test: clean docker-up
	@echo "Running CI test suite..."
	poetry run python scripts/test_runner.py --mode=all --coverage --parallel=2
	$(MAKE) docker-down

ci-quality:
	@echo "Running CI quality checks..."
	poetry run black --check src/ tests/
	poetry run isort --check-only src/ tests/
	poetry run flake8 src/ tests/
	poetry run mypy src/dbranching

# Development workflow commands
dev-setup: install-dev docker-up
	@echo "Development environment setup complete!"

dev-teardown: docker-down clean
	@echo "Development environment cleaned up!"

# Quick development test
quick-test:
	@echo "Running quick development tests..."
	poetry run pytest tests/unit/ -x --tb=short

# Watch mode for tests (requires pytest-watch)
watch:
	@echo "Starting test watch mode..."
	poetry run ptw tests/ -- --tb=short

# Profile tests
profile-tests:
	@echo "Profiling test execution..."
	poetry run pytest --profile tests/