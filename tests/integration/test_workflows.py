"""Integration tests for complete dbranching workflows."""

import tempfile
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from dbranching.config import DatabaseBranchingConfig, DatabaseConfig
from dbranching.database.factory import DatabaseFactory
from dbranching.snapshot.engine import SnapshotEngine


@pytest.mark.integration
class TestCompleteWorkflows:
    """Test complete end-to-end workflows."""

    @pytest.mark.asyncio
    async def test_sqlite_snapshot_workflow(self, temp_dir: Path):
        """Test complete snapshot workflow with SQLite."""
        # Create configuration
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        
        # Create database adapter
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Create some test data
            await adapter.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE
                )
            """)
            
            await adapter.execute("""
                INSERT INTO users (name, email) VALUES 
                ('John Doe', 'john@example.com'),
                ('Jane Smith', 'jane@example.com')
            """)
            
            # Verify initial data
            users = await adapter.fetch_all("SELECT * FROM users ORDER BY id")
            assert len(users) == 2
            assert users[0]["name"] == "John Doe"
            
            # Create snapshot engine
            snapshot_engine = SnapshotEngine(config, adapter)
            
            # Create snapshot
            snapshot_name = "test-snapshot-1"
            metadata = await snapshot_engine.create_snapshot(
                name=snapshot_name,
                description="Test snapshot for workflow",
                tags=["test", "workflow"]
            )
            
            assert metadata.name == snapshot_name
            assert "test" in metadata.tags
            
            # Modify data after snapshot
            await adapter.execute("""
                INSERT INTO users (name, email) VALUES 
                ('Bob Wilson', 'bob@example.com')
            """)
            
            await adapter.execute("""
                UPDATE users SET email = 'john.doe@example.com' 
                WHERE name = 'John Doe'
            """)
            
            # Verify modified data
            users = await adapter.fetch_all("SELECT * FROM users ORDER BY id")
            assert len(users) == 3
            assert users[0]["email"] == "john.doe@example.com"
            
            # Restore snapshot
            await snapshot_engine.restore_snapshot(snapshot_name)
            
            # Verify restoration
            users = await adapter.fetch_all("SELECT * FROM users ORDER BY id")
            assert len(users) == 2  # Back to original count
            assert users[0]["email"] == "john@example.com"  # Original email
            
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_configuration_workflow(self, temp_dir: Path):
        """Test configuration loading and validation workflow."""
        config_file = temp_dir / "dbranching.yaml"
        
        # Test with minimal config
        minimal_config = {
            "database": {"type": "sqlite", "database": ":memory:"}
        }
        
        with config_file.open("w") as f:
            yaml.dump(minimal_config, f)
        
        config = DatabaseBranchingConfig.from_file(config_file)
        assert config.database.type == "sqlite"
        assert config.storage.directory.name == "snapshots"  # Default value
        
        # Test with complete config
        complete_config = {
            "database": {
                "type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "database": "testdb",
                "username": "testuser",
                "password": "testpass",
            },
            "storage": {
                "directory": str(temp_dir / "custom_snapshots"),
                "compression": "bzip2",
            },
            "logging": {"level": "DEBUG"},
        }
        
        with config_file.open("w") as f:
            yaml.dump(complete_config, f)
        
        config = DatabaseBranchingConfig.from_file(config_file)
        assert config.database.type == "postgresql"
        assert config.database.host == "localhost"
        assert config.storage.compression == "bzip2"
        assert config.logging.level == "DEBUG"

    @pytest.mark.asyncio
    async def test_error_recovery_workflow(self, temp_dir: Path):
        """Test error recovery in various workflow scenarios."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Test recovery from invalid SQL
            with pytest.raises(Exception):
                await adapter.execute("INVALID SQL STATEMENT")
            
            # Adapter should still be functional
            await adapter.execute("SELECT 1")
            
            # Test recovery from transaction failure
            await adapter.execute("""
                CREATE TABLE test_recovery (
                    id INTEGER PRIMARY KEY,
                    value TEXT UNIQUE
                )
            """)
            
            # Insert initial value
            await adapter.execute(
                "INSERT INTO test_recovery (value) VALUES (?)", ("initial",)
            )
            
            # Test transaction rollback on constraint violation
            try:
                async with adapter.transaction():
                    await adapter.execute(
                        "INSERT INTO test_recovery (value) VALUES (?)", ("unique1",)
                    )
                    # This should cause rollback
                    await adapter.execute(
                        "INSERT INTO test_recovery (value) VALUES (?)", ("unique1",)
                    )
            except Exception:
                pass  # Expected
            
            # Verify rollback worked
            rows = await adapter.fetch_all("SELECT value FROM test_recovery")
            assert len(rows) == 1
            assert rows[0]["value"] == "initial"
            
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_multi_snapshot_workflow(self, temp_dir: Path):
        """Test workflow with multiple snapshots."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Create test table
            await adapter.execute("""
                CREATE TABLE versions (
                    id INTEGER PRIMARY KEY,
                    version TEXT,
                    data TEXT
                )
            """)
            
            snapshot_engine = SnapshotEngine(config, adapter)
            snapshots_created = []
            
            # Create multiple snapshots with different data
            for i in range(3):
                version = f"v1.{i}"
                
                # Insert version-specific data
                await adapter.execute(
                    "INSERT INTO versions (version, data) VALUES (?, ?)",
                    (version, f"Data for {version}")
                )
                
                # Create snapshot
                snapshot_name = f"version-{version.replace('.', '-')}"
                metadata = await snapshot_engine.create_snapshot(
                    name=snapshot_name,
                    description=f"Snapshot for {version}",
                    tags=[version, "workflow-test"]
                )
                
                snapshots_created.append((snapshot_name, version))
            
            # Verify all snapshots were created
            assert len(snapshots_created) == 3
            
            # Current data should have all versions
            rows = await adapter.fetch_all("SELECT version FROM versions ORDER BY id")
            assert len(rows) == 3
            
            # Restore to first snapshot
            first_snapshot, first_version = snapshots_created[0]
            await snapshot_engine.restore_snapshot(first_snapshot)
            
            # Should only have first version data
            rows = await adapter.fetch_all("SELECT version FROM versions")
            assert len(rows) == 1
            assert rows[0]["version"] == first_version
            
            # Restore to second snapshot
            second_snapshot, second_version = snapshots_created[1]
            await snapshot_engine.restore_snapshot(second_snapshot)
            
            # Should have first two versions
            rows = await adapter.fetch_all("SELECT version FROM versions ORDER BY id")
            assert len(rows) == 2
            assert rows[0]["version"] == first_version
            assert rows[1]["version"] == second_version
            
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_concurrent_operations_workflow(self, temp_dir: Path):
        """Test workflow with concurrent database operations."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        
        # Create multiple adapters for concurrent testing
        adapters = []
        for i in range(3):
            adapter = factory.create(config.database)
            await adapter.connect()
            adapters.append(adapter)
        
        try:
            # Create table with first adapter
            await adapters[0].execute("""
                CREATE TABLE concurrent_test (
                    id INTEGER PRIMARY KEY,
                    worker_id INTEGER,
                    operation_id INTEGER
                )
            """)
            
            # Define concurrent operations
            async def worker_operations(worker_id: int, adapter):
                """Perform operations for a specific worker."""
                for op_id in range(5):
                    await adapter.execute(
                        "INSERT INTO concurrent_test (worker_id, operation_id) VALUES (?, ?)",
                        (worker_id, op_id)
                    )
                    # Small delay to interleave operations
                    await asyncio.sleep(0.01)
            
            # Run concurrent operations
            tasks = []
            for i, adapter in enumerate(adapters):
                task = asyncio.create_task(worker_operations(i, adapter))
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            
            # Verify all operations completed
            rows = await adapters[0].fetch_all(
                "SELECT worker_id, COUNT(*) as count FROM concurrent_test GROUP BY worker_id ORDER BY worker_id"
            )
            
            assert len(rows) == 3  # Three workers
            for row in rows:
                assert row["count"] == 5  # Each worker performed 5 operations
            
        finally:
            for adapter in adapters:
                await adapter.disconnect()


@pytest.mark.integration
@pytest.mark.performance
class TestPerformanceWorkflows:
    """Test workflows that focus on performance characteristics."""

    @pytest.mark.asyncio
    async def test_large_table_snapshot_workflow(self, temp_dir: Path):
        """Test snapshot workflow with larger tables."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "large_test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Create table with multiple columns
            await adapter.execute("""
                CREATE TABLE large_table (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    email TEXT,
                    data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert a moderate amount of test data
            insert_count = 1000
            batch_size = 100
            
            for batch_start in range(0, insert_count, batch_size):
                values = []
                for i in range(batch_start, min(batch_start + batch_size, insert_count)):
                    values.extend([
                        f"user_{i}",
                        f"user_{i}@example.com",
                        f"Large data string for user {i} " * 10,  # Make it larger
                    ])
                
                placeholders = ",".join(["(?, ?, ?)"] * (len(values) // 3))
                await adapter.execute(
                    f"INSERT INTO large_table (name, email, data) VALUES {placeholders}",
                    values
                )
            
            # Verify data was inserted
            count_result = await adapter.fetch_one("SELECT COUNT(*) as count FROM large_table")
            assert count_result["count"] == insert_count
            
            # Create snapshot (this should handle the larger dataset)
            snapshot_engine = SnapshotEngine(config, adapter)
            metadata = await snapshot_engine.create_snapshot(
                name="large-dataset-snapshot",
                description="Snapshot of large dataset",
                tags=["performance", "large"]
            )
            
            assert metadata.name == "large-dataset-snapshot"
            
            # Modify some data
            await adapter.execute(
                "UPDATE large_table SET email = 'updated@example.com' WHERE id <= 10"
            )
            
            # Restore snapshot
            await snapshot_engine.restore_snapshot("large-dataset-snapshot")
            
            # Verify restoration
            updated_rows = await adapter.fetch_all(
                "SELECT email FROM large_table WHERE id <= 10"
            )
            
            for row in updated_rows:
                assert row["email"].startswith("user_")
                assert row["email"] != "updated@example.com"
            
        finally:
            await adapter.disconnect()