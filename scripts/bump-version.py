#!/usr/bin/env python3
"""Version bumping script for dbranching."""

import argparse
import re
import sys
from pathlib import Path
from typing import Tuple


def get_current_version(pyproject_path: Path) -> str:
    """Extract current version from pyproject.toml."""
    content = pyproject_path.read_text()
    match = re.search(r'version = "([^"]+)"', content)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def parse_version(version: str) -> Tuple[int, int, int]:
    """Parse semantic version string into components."""
    # Remove dev suffix if present
    version = version.split('-dev')[0]
    
    parts = version.split('.')
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {version}")
    
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        raise ValueError(f"Invalid version format: {version}")


def format_version(major: int, minor: int, patch: int, dev: bool = False) -> str:
    """Format version components into string."""
    version = f"{major}.{minor}.{patch}"
    if dev:
        version += "-dev"
    return version


def bump_version(current: str, bump_type: str, dev: bool = False) -> str:
    """Bump version according to type."""
    major, minor, patch = parse_version(current)
    
    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid bump type: {bump_type}")
    
    return format_version(major, minor, patch, dev)


def update_pyproject_toml(path: Path, new_version: str) -> None:
    """Update version in pyproject.toml."""
    content = path.read_text()
    updated = re.sub(
        r'version = "[^"]+"',
        f'version = "{new_version}"',
        content
    )
    path.write_text(updated)
    print(f"Updated {path}: version = \"{new_version}\"")


def update_init_py(path: Path, new_version: str) -> None:
    """Update version in __init__.py."""
    content = path.read_text()
    updated = re.sub(
        r'__version__ = "[^"]+"',
        f'__version__ = "{new_version}"',
        content
    )
    path.write_text(updated)
    print(f"Updated {path}: __version__ = \"{new_version}\"")


def update_changelog(path: Path, new_version: str) -> None:
    """Update CHANGELOG.md with new version section."""
    if not path.exists():
        print(f"Warning: {path} not found, skipping changelog update")
        return
    
    content = path.read_text()
    
    # Find [Unreleased] section
    unreleased_pattern = r'## \[Unreleased\]'
    if not re.search(unreleased_pattern, content):
        print(f"Warning: [Unreleased] section not found in {path}")
        return
    
    # Add new version section after [Unreleased]
    import datetime
    today = datetime.date.today().isoformat()
    new_section = f"""## [Unreleased]

## [{new_version}] - {today}"""
    
    updated = re.sub(
        unreleased_pattern,
        new_section,
        content
    )
    
    path.write_text(updated)
    print(f"Updated {path}: Added version {new_version} section")


def main() -> int:
    """Main version bumping function."""
    parser = argparse.ArgumentParser(
        description="Bump version for dbranching package"
    )
    parser.add_argument(
        "bump_type",
        choices=["major", "minor", "patch"],
        help="Type of version bump"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Add -dev suffix for development version"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )
    
    args = parser.parse_args()
    
    # File paths
    root_dir = Path(__file__).parent.parent
    pyproject_path = root_dir / "pyproject.toml"
    init_path = root_dir / "src" / "dbranching" / "__init__.py"
    changelog_path = root_dir / "CHANGELOG.md"
    
    # Check files exist
    if not pyproject_path.exists():
        print(f"Error: {pyproject_path} not found")
        return 1
    
    if not init_path.exists():
        print(f"Error: {init_path} not found")
        return 1
    
    try:
        # Get current version and calculate new version
        current_version = get_current_version(pyproject_path)
        new_version = bump_version(current_version, args.bump_type, args.dev)
        
        print(f"Current version: {current_version}")
        print(f"New version: {new_version}")
        
        if args.dry_run:
            print("\nDry run - no files would be modified")
            print(f"Would update {pyproject_path}")
            print(f"Would update {init_path}")
            if changelog_path.exists():
                print(f"Would update {changelog_path}")
            return 0
        
        # Update files
        print("\nUpdating files:")
        update_pyproject_toml(pyproject_path, new_version)
        update_init_py(init_path, new_version)
        update_changelog(changelog_path, new_version)
        
        print(f"\nVersion bumped from {current_version} to {new_version}")
        print("\nNext steps:")
        print("1. Review changes: git diff")
        print("2. Update CHANGELOG.md with release notes")
        print("3. Commit changes: git add . && git commit -m 'chore: bump version to {new_version}'")
        if not args.dev:
            print("4. Create tag: git tag -a v{new_version} -m 'Release version {new_version}'")
            print("5. Push: git push origin main && git push origin v{new_version}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())