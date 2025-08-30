#!/usr/bin/env python3
"""Installation verification script for dbranching."""

import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Optional
import platform


def run_command(cmd: List[str]) -> Tuple[int, str, str]:
    """Run a command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except FileNotFoundError:
        return 1, "", f"Command not found: {cmd[0]}"


def check_python_version() -> bool:
    """Check if Python version meets requirements."""
    version = sys.version_info
    if version.major == 3 and version.minor >= 8:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"✗ Python {version.major}.{version.minor}.{version.micro} (requires 3.8+)")
        return False


def check_package_import() -> bool:
    """Test package import."""
    try:
        import dbranching
        print(f"✓ Package import successful")
        
        # Check version if available
        if hasattr(dbranching, '__version__'):
            print(f"  Version: {dbranching.__version__}")
        return True
    except ImportError as e:
        print(f"✗ Package import failed: {e}")
        return False


def check_cli_commands() -> bool:
    """Test CLI command availability."""
    commands = ['dbranching', 'dbbranch']
    all_ok = True
    
    for cmd in commands:
        code, stdout, stderr = run_command([cmd, '--version'])
        if code == 0:
            version = stdout.strip() if stdout else "unknown"
            print(f"✓ {cmd} command available (version: {version})")
        else:
            print(f"✗ {cmd} command failed: {stderr}")
            all_ok = False
    
    return all_ok


def check_help_commands() -> bool:
    """Test CLI help commands."""
    commands_to_test = [
        (['dbranching', '--help'], 'main help'),
        (['dbranching', 'init', '--help'], 'init help'),
        (['dbranching', 'status', '--help'], 'status help'),
        (['dbbranch', '--help'], 'dbbranch alias help'),
    ]
    
    all_ok = True
    for cmd, description in commands_to_test:
        code, stdout, stderr = run_command(cmd)
        if code == 0 and 'Usage:' in stdout:
            print(f"✓ {description}")
        else:
            print(f"✗ {description} failed")
            all_ok = False
    
    return all_ok


def check_database_extras() -> None:
    """Check availability of database driver extras."""
    drivers = {
        'postgresql': ['asyncpg', 'psycopg2'],
        'mysql': ['aiomysql', 'pymysql'], 
        'sqlite': ['aiosqlite']
    }
    
    print("\nDatabase driver availability:")
    for db_type, modules in drivers.items():
        available = []
        for module in modules:
            try:
                __import__(module)
                available.append(module)
            except ImportError:
                pass
        
        if available:
            print(f"  ✓ {db_type}: {', '.join(available)}")
        else:
            print(f"  ○ {db_type}: not installed (optional)")


def check_system_info() -> None:
    """Display system information."""
    print(f"\nSystem information:")
    print(f"  Platform: {platform.platform()}")
    print(f"  Architecture: {platform.machine()}")
    print(f"  Python executable: {sys.executable}")
    print(f"  Python path: {sys.path[0] if sys.path else 'unknown'}")


def main() -> int:
    """Main verification function."""
    print("DBranching Installation Verification")
    print("=" * 40)
    
    checks = [
        ("Python version", check_python_version),
        ("Package import", check_package_import),
        ("CLI commands", check_cli_commands),
        ("Help commands", check_help_commands),
    ]
    
    passed = 0
    total = len(checks)
    
    for name, check_func in checks:
        print(f"\nChecking {name}...")
        if check_func():
            passed += 1
    
    # Additional information
    check_database_extras()
    check_system_info()
    
    print(f"\nVerification Results: {passed}/{total} checks passed")
    
    if passed == total:
        print("🎉 Installation verification successful!")
        return 0
    else:
        print("❌ Installation verification failed!")
        print("\nTroubleshooting:")
        print("1. Ensure dbranching is installed: pip install dbranching")
        print("2. Check Python version: python --version (requires 3.8+)")
        print("3. Verify PATH includes Python scripts directory")
        print("4. Try installing with database extras: pip install dbranching[all-databases]")
        return 1


if __name__ == "__main__":
    sys.exit(main())