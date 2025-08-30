#!/usr/bin/env python3
"""Test runner script with various test execution modes."""

import argparse
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Optional


def run_command(cmd: List[str], description: str) -> int:
    """Run a command and return its exit code."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="DBranching test runner")
    parser.add_argument(
        "--mode",
        choices=["unit", "integration", "performance", "all", "fast", "slow"],
        default="all",
        help="Test mode to run"
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run with coverage reporting"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of parallel workers for tests"
    )
    parser.add_argument(
        "--database",
        choices=["sqlite", "mysql", "postgresql", "all"],
        default="sqlite",
        help="Database type to test against"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run benchmark tests and generate reports"
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Start Docker test databases"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up test artifacts and Docker containers"
    )
    
    args = parser.parse_args()
    
    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    exit_code = 0
    
    try:
        # Cleanup if requested
        if args.cleanup:
            cleanup_exit_code = cleanup_test_environment()
            if cleanup_exit_code != 0:
                exit_code = cleanup_exit_code
                
        # Start Docker containers if requested
        if args.docker:
            docker_exit_code = start_docker_databases()
            if docker_exit_code != 0:
                print("Warning: Docker database setup failed")
        
        # Build base pytest command
        pytest_cmd = ["python", "-m", "pytest"]
        
        # Add verbosity
        if args.verbose:
            pytest_cmd.extend(["-v", "-s"])
        
        # Add coverage
        if args.coverage:
            pytest_cmd.extend([
                "--cov=dbranching",
                "--cov-report=term-missing",
                "--cov-report=html",
                "--cov-report=xml"
            ])
        
        # Add parallel execution
        if args.parallel > 1:
            pytest_cmd.extend(["-n", str(args.parallel)])
        
        # Add benchmark support
        if args.benchmark:
            pytest_cmd.extend(["--benchmark-only", "--benchmark-json=benchmark_results.json"])
        
        # Select test mode
        if args.mode == "unit":
            pytest_cmd.extend(["-m", "unit"])
            test_exit_code = run_command(pytest_cmd, "Unit Tests")
            
        elif args.mode == "integration":
            pytest_cmd.extend(["-m", "integration"])
            test_exit_code = run_command(pytest_cmd, "Integration Tests")
            
        elif args.mode == "performance":
            pytest_cmd.extend(["-m", "performance"])
            test_exit_code = run_command(pytest_cmd, "Performance Tests")
            
        elif args.mode == "fast":
            pytest_cmd.extend(["-m", "not slow and not performance"])
            test_exit_code = run_command(pytest_cmd, "Fast Tests")
            
        elif args.mode == "slow":
            pytest_cmd.extend(["-m", "slow or performance"])
            test_exit_code = run_command(pytest_cmd, "Slow Tests")
            
        elif args.mode == "all":
            # Run unit tests first
            unit_cmd = pytest_cmd + ["-m", "unit"]
            unit_exit_code = run_command(unit_cmd, "Unit Tests")
            
            # Run integration tests
            if unit_exit_code == 0:
                integration_cmd = pytest_cmd + ["-m", "integration"]
                integration_exit_code = run_command(integration_cmd, "Integration Tests")
                
                # Run performance tests if requested
                if integration_exit_code == 0 and args.benchmark:
                    perf_cmd = pytest_cmd + ["-m", "performance", "--benchmark-only"]
                    perf_exit_code = run_command(perf_cmd, "Performance Tests")
                    test_exit_code = perf_exit_code
                else:
                    test_exit_code = integration_exit_code
            else:
                test_exit_code = unit_exit_code
        
        if test_exit_code != 0:
            exit_code = test_exit_code
        
        # Run linting and type checking
        if args.mode in ["all", "fast"] and test_exit_code == 0:
            quality_exit_code = run_quality_checks()
            if quality_exit_code != 0:
                exit_code = quality_exit_code
        
        # Generate test report
        if args.coverage or args.benchmark:
            generate_test_report(args.coverage, args.benchmark)
    
    except KeyboardInterrupt:
        print("\nTest execution interrupted by user")
        exit_code = 130
    
    except Exception as e:
        print(f"\nTest execution failed with error: {e}")
        exit_code = 1
    
    finally:
        # Cleanup Docker containers if we started them
        if args.docker and not args.cleanup:
            stop_docker_databases()
    
    return exit_code


def start_docker_databases() -> int:
    """Start Docker test databases."""
    cmd = ["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d"]
    return run_command(cmd, "Starting Docker test databases")


def stop_docker_databases() -> int:
    """Stop Docker test databases."""
    cmd = ["docker", "compose", "-f", "docker-compose.test.yml", "down"]
    return run_command(cmd, "Stopping Docker test databases")


def cleanup_test_environment() -> int:
    """Clean up test environment."""
    cleanup_commands = [
        (["docker", "compose", "-f", "docker-compose.test.yml", "down", "-v"], "Stopping Docker containers"),
        (["rm", "-rf", "htmlcov/"], "Removing HTML coverage reports"),
        (["rm", "-f", "coverage.xml"], "Removing XML coverage report"),
        (["rm", "-f", ".coverage"], "Removing coverage data"),
        (["rm", "-rf", ".pytest_cache/"], "Removing pytest cache"),
        (["rm", "-f", "benchmark_results.json"], "Removing benchmark results"),
        (["find", ".", "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"], "Removing Python cache"),
    ]
    
    overall_exit_code = 0
    for cmd, description in cleanup_commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 and "docker" not in cmd[0]:  # Ignore Docker errors
                print(f"Warning: {description} failed: {result.stderr}")
                overall_exit_code = max(overall_exit_code, result.returncode)
        except FileNotFoundError:
            pass  # Command not found, skip
    
    return overall_exit_code


def run_quality_checks() -> int:
    """Run code quality checks."""
    quality_commands = [
        (["python", "-m", "black", "--check", "src/", "tests/"], "Black formatting check"),
        (["python", "-m", "isort", "--check-only", "src/", "tests/"], "Import sorting check"),
        (["python", "-m", "flake8", "src/", "tests/"], "Flake8 linting"),
        (["python", "-m", "mypy", "src/dbranching"], "MyPy type checking"),
    ]
    
    overall_exit_code = 0
    for cmd, description in quality_commands:
        exit_code = run_command(cmd, description)
        if exit_code != 0:
            overall_exit_code = exit_code
    
    return overall_exit_code


def generate_test_report(coverage: bool, benchmark: bool) -> None:
    """Generate test report."""
    print(f"\n{'='*60}")
    print("TEST EXECUTION SUMMARY")
    print(f"{'='*60}")
    
    if coverage and Path("htmlcov/index.html").exists():
        print(f"Coverage report: file://{Path.cwd()}/htmlcov/index.html")
    
    if benchmark and Path("benchmark_results.json").exists():
        print(f"Benchmark results: {Path.cwd()}/benchmark_results.json")
    
    if Path(".coverage").exists():
        # Try to get coverage summary
        try:
            result = subprocess.run(
                ["python", "-m", "coverage", "report", "--show-missing"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print("\nCoverage Summary:")
                print(result.stdout)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())