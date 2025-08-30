#!/usr/bin/env python3
"""
Example demonstrating database adapter usage.

This example shows how to use the database abstraction layer to:
1. Connect to a PostgreSQL database
2. Get database information
3. Create snapshots
4. Restore snapshots
5. Validate snapshots

To run this example:
1. Make sure you have a PostgreSQL database available
2. Update the connection configuration below
3. Run: python examples/database_usage.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

# Add the src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dbranching.config import DatabaseConfig
from dbranching.database import PostgreSQLAdapter, SnapshotOptions, RestoreOptions
from dbranching.database.models import CompressionType, SnapshotFormat, ProgressCallback


class SimpleProgressCallback(ProgressCallback):
    """Simple progress callback that prints updates."""

    async def update(
        self,
        current: int,
        total: int,
        message: str = "",
        stage: str = "",
    ) -> None:
        """Print progress updates."""
        percentage = (current / total) * 100 if total > 0 else 0
        print(f"[{stage.upper()}] {percentage:.1f}% - {message}")


async def main():
    """Main example function."""
    print("=== Database Adapter Example ===\n")

    # Configure database connection
    # NOTE: Update these settings for your database
    config = DatabaseConfig(
        driver="postgresql",
        host="localhost",
        port=5432,
        database="test_db",
        username="postgres",
        password="your_password",  # Consider using environment variables
        ssl_mode="prefer",
    )

    # Create PostgreSQL adapter
    adapter = PostgreSQLAdapter(config)

    try:
        # Test connection
        print("1. Testing database connection...")
        connection_test = await adapter.test_connection()
        print(f"   Connection test: {'✓ Success' if connection_test else '✗ Failed'}")

        if not connection_test:
            print("   Cannot connect to database. Please check your configuration.")
            return

        # Connect and get database info
        print("\n2. Connecting to database and getting information...")
        async with adapter:  # This will auto-connect and disconnect
            db_info = await adapter.get_database_info()
            print(f"   Database: {db_info.name}")
            print(f"   Version: {db_info.version}")
            print(f"   Size: {db_info.size_bytes / (1024 * 1024):.1f} MB")
            print(f"   Tables: {db_info.table_count}")
            print(f"   Schemas: {db_info.schema_count}")
            print(f"   Extensions: {', '.join(db_info.extensions[:5])}...")

            # List schemas and tables
            print(f"\n3. Listing database schemas and tables...")
            schemas = await adapter.list_schemas()
            print(f"   Schemas: {', '.join(schemas)}")

            tables = await adapter.list_tables()
            print(f"   Tables: {', '.join(tables[:10])}...")  # Show first 10

            # Create a snapshot
            print(f"\n4. Creating database snapshot...")
            snapshot_path = Path("/tmp/example_snapshot.dump")
            snapshot_options = SnapshotOptions(
                format=SnapshotFormat.CUSTOM,
                compression=CompressionType.GZIP,
                compression_level=6,
                parallel_jobs=2,
                verbose=True,
            )

            progress_callback = SimpleProgressCallback()

            try:
                snapshot_result = await adapter.create_snapshot(
                    snapshot_path, snapshot_options, progress_callback
                )

                if snapshot_result.success:
                    print(f"   ✓ Snapshot created successfully!")
                    print(f"   Path: {snapshot_result.snapshot_path}")
                    print(f"   Size: {snapshot_result.size_bytes / (1024 * 1024):.1f} MB")
                    print(f"   Duration: {snapshot_result.duration_seconds:.1f} seconds")
                    if snapshot_result.compression_ratio:
                        print(f"   Compression ratio: {snapshot_result.compression_ratio:.1f}x")
                else:
                    print(f"   ✗ Snapshot failed: {snapshot_result.error_message}")
                    return

            except Exception as e:
                print(f"   ✗ Snapshot failed with exception: {e}")
                return

            # Validate the snapshot
            print(f"\n5. Validating snapshot...")
            validation_result = await adapter.validate_snapshot(snapshot_path)

            if validation_result.valid:
                print(f"   ✓ Snapshot is valid!")
                print(f"   Format valid: {validation_result.format_valid}")
                print(f"   Compatible: {validation_result.compatible}")
                print(f"   Database version: {validation_result.database_version}")
                print(f"   Estimated restore time: {validation_result.estimated_restore_time:.1f}s")
                if validation_result.warnings:
                    print(f"   Warnings: {', '.join(validation_result.warnings)}")
            else:
                print(f"   ✗ Snapshot validation failed: {validation_result.error_message}")

            # Demonstrate size estimation
            print(f"\n6. Demonstrating snapshot size estimation...")
            estimated_size = await adapter.estimate_snapshot_size()
            print(f"   Full database estimate: {estimated_size / (1024 * 1024):.1f} MB")

            schema_only_options = SnapshotOptions(
                schema_only=True,
                compression=CompressionType.GZIP
            )
            schema_size = await adapter.estimate_snapshot_size(schema_only_options)
            print(f"   Schema-only estimate: {schema_size / (1024 * 1024):.2f} MB")

            # Get supported formats
            print(f"\n7. Supported snapshot formats...")
            formats = await adapter.get_supported_formats()
            print(f"   Formats: {', '.join(formats)}")

            # Cleanup example snapshot
            print(f"\n8. Cleaning up...")
            if snapshot_path.exists():
                snapshot_path.unlink()
                print(f"   ✓ Removed example snapshot file")

        print(f"\n=== Example completed successfully! ===")

    except Exception as e:
        print(f"\n✗ Example failed with error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Ensure cleanup
        await adapter.disconnect()


if __name__ == "__main__":
    # Run the async example
    asyncio.run(main())