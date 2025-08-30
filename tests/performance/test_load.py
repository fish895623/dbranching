"""Load testing for dbranching under various stress conditions."""

import asyncio
import time
import tempfile
import random
import statistics
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import pytest

from dbranching.config import DatabaseBranchingConfig
from dbranching.database.factory import DatabaseFactory
from dbranching.snapshot.engine import SnapshotEngine


@pytest.mark.performance
class TestHighVolumeOperations:
    """Test system behavior under high volume operations."""

    @pytest.mark.asyncio
    async def test_high_volume_inserts(self, temp_dir: Path):
        """Test system performance with high volume insert operations."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "high_volume.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Create table optimized for bulk inserts
            await adapter.execute("""
                CREATE TABLE high_volume_test (
                    id INTEGER PRIMARY KEY,
                    batch_id INTEGER,
                    sequence_num INTEGER,
                    payload TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Test parameters
            total_records = 50000
            batch_size = 1000
            num_batches = total_records // batch_size
            
            print(f"\nHigh volume insert test: {total_records} records in {num_batches} batches")
            
            start_time = time.perf_counter()
            records_inserted = 0
            
            for batch_num in range(num_batches):
                batch_data = []
                for seq in range(batch_size):
                    batch_data.extend([
                        batch_num,
                        seq,
                        f"Payload data for batch {batch_num}, sequence {seq} " * 3
                    ])
                
                placeholders = ",".join(["(?, ?, ?)"] * batch_size)
                await adapter.execute(
                    f"INSERT INTO high_volume_test (batch_id, sequence_num, payload) VALUES {placeholders}",
                    batch_data
                )
                
                records_inserted += batch_size
                
                # Progress reporting
                if batch_num % 10 == 0:
                    elapsed = time.perf_counter() - start_time
                    rate = records_inserted / elapsed if elapsed > 0 else 0
                    print(f"  Inserted {records_inserted} records ({rate:.0f} records/sec)")
            
            end_time = time.perf_counter()
            total_time = end_time - start_time
            final_rate = total_records / total_time
            
            print(f"\nHigh volume insert completed:")
            print(f"Total time: {total_time:.2f}s")
            print(f"Final rate: {final_rate:.0f} records/sec")
            print(f"Records inserted: {records_inserted}")
            
            # Verify all records were inserted
            count_result = await adapter.fetch_one("SELECT COUNT(*) as count FROM high_volume_test")
            assert count_result["count"] == total_records
            
            # Performance assertions
            assert final_rate > 1000  # Should handle at least 1000 records/sec
            assert total_time < 300    # Should complete within 5 minutes
            
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_stress_snapshot_operations(self, temp_dir: Path):
        """Test snapshot operations under stress conditions."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "stress_test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Create multiple tables with data
            tables = ["users", "orders", "products", "logs"]
            
            for table in tables:
                await adapter.execute(f"""
                    CREATE TABLE {table} (
                        id INTEGER PRIMARY KEY,
                        name TEXT,
                        data TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Insert data into each table
                records_per_table = 5000
                batch_size = 500
                
                for batch_start in range(0, records_per_table, batch_size):
                    batch_data = []
                    for i in range(batch_start, min(batch_start + batch_size, records_per_table)):
                        batch_data.extend([
                            f"{table}_item_{i}",
                            f"Data for {table} item {i} " * 5
                        ])
                    
                    placeholders = ",".join(["(?, ?)"] * (len(batch_data) // 2))
                    await adapter.execute(
                        f"INSERT INTO {table} (name, data) VALUES {placeholders}",
                        batch_data
                    )
            
            print(f"\nStress test setup complete: {len(tables)} tables with {records_per_table} records each")
            
            # Test rapid snapshot creation
            snapshot_engine = SnapshotEngine(config, adapter)
            num_snapshots = 10
            
            snapshot_times = []
            
            for i in range(num_snapshots):
                snapshot_name = f"stress_test_snapshot_{i}"
                
                start_time = time.perf_counter()
                metadata = await snapshot_engine.create_snapshot(
                    name=snapshot_name,
                    description=f"Stress test snapshot {i}",
                    tags=["stress", "test", f"iteration_{i}"]
                )
                end_time = time.perf_counter()
                
                snapshot_time = end_time - start_time
                snapshot_times.append(snapshot_time)
                
                print(f"  Snapshot {i+1}/{num_snapshots}: {snapshot_time:.2f}s")
                
                # Modify some data between snapshots
                table = random.choice(tables)
                await adapter.execute(
                    f"UPDATE {table} SET data = data || ' [modified in iteration {i}]' WHERE id <= 100"
                )
            
            avg_snapshot_time = statistics.mean(snapshot_times)
            max_snapshot_time = max(snapshot_times)
            
            print(f"\nSnapshot stress test results:")
            print(f"Average snapshot time: {avg_snapshot_time:.2f}s")
            print(f"Maximum snapshot time: {max_snapshot_time:.2f}s")
            print(f"Total snapshots created: {num_snapshots}")
            
            # Test random snapshot restoration
            restoration_times = []
            
            for i in range(5):  # Test 5 random restorations
                snapshot_to_restore = f"stress_test_snapshot_{random.randint(0, num_snapshots-1)}"
                
                start_time = time.perf_counter()
                await snapshot_engine.restore_snapshot(snapshot_to_restore)
                end_time = time.perf_counter()
                
                restoration_time = end_time - start_time
                restoration_times.append(restoration_time)
                
                print(f"  Restored {snapshot_to_restore}: {restoration_time:.2f}s")
            
            avg_restoration_time = statistics.mean(restoration_times)
            
            print(f"Average restoration time: {avg_restoration_time:.2f}s")
            
            # Performance assertions
            assert avg_snapshot_time < 30.0  # Average snapshot should take less than 30s
            assert max_snapshot_time < 60.0  # No snapshot should take more than 60s
            assert avg_restoration_time < 30.0  # Average restoration should take less than 30s
            
        finally:
            await adapter.disconnect()


@pytest.mark.performance
class TestConcurrentLoadTests:
    """Test system behavior under concurrent load."""

    @pytest.mark.asyncio
    async def test_concurrent_database_operations(self, temp_dir: Path):
        """Test concurrent database operations with multiple connections."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "concurrent_load.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        
        # Setup with single connection
        setup_adapter = factory.create(config.database)
        await setup_adapter.connect()
        
        try:
            await setup_adapter.execute("""
                CREATE TABLE concurrent_load_test (
                    id INTEGER PRIMARY KEY,
                    worker_id INTEGER,
                    operation_type TEXT,
                    data TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
        finally:
            await setup_adapter.disconnect()
        
        async def worker_operations(worker_id: int, operations_count: int):
            """Perform mixed operations for a worker."""
            adapter = factory.create(config.database)
            await adapter.connect()
            
            try:
                operation_times = []
                
                for op_num in range(operations_count):
                    start_time = time.perf_counter()
                    
                    # Mix of operations
                    if op_num % 10 == 0:
                        # Read operation
                        await adapter.fetch_all(
                            "SELECT COUNT(*) FROM concurrent_load_test WHERE worker_id = ?",
                            (worker_id,)
                        )
                        op_type = "read"
                    elif op_num % 5 == 0:
                        # Update operation
                        await adapter.execute(
                            "UPDATE concurrent_load_test SET data = ? WHERE worker_id = ? AND id = (SELECT MAX(id) FROM concurrent_load_test WHERE worker_id = ?)",
                            (f"Updated by worker {worker_id} at op {op_num}", worker_id, worker_id)
                        )
                        op_type = "update"
                    else:
                        # Insert operation
                        await adapter.execute(
                            "INSERT INTO concurrent_load_test (worker_id, operation_type, data) VALUES (?, ?, ?)",
                            (worker_id, "insert", f"Data from worker {worker_id}, operation {op_num}")
                        )
                        op_type = "insert"
                    
                    end_time = time.perf_counter()
                    operation_times.append(end_time - start_time)
                    
                    # Small random delay to add realism
                    await asyncio.sleep(random.uniform(0.001, 0.01))
                
                return {
                    'worker_id': worker_id,
                    'operations': operations_count,
                    'avg_time': statistics.mean(operation_times),
                    'max_time': max(operation_times),
                    'total_time': sum(operation_times)
                }
                
            finally:
                await adapter.disconnect()
        
        # Run concurrent workers
        num_workers = 8
        operations_per_worker = 100
        
        print(f"\nConcurrent load test: {num_workers} workers, {operations_per_worker} operations each")
        
        start_time = time.perf_counter()
        
        tasks = [
            asyncio.create_task(worker_operations(i, operations_per_worker))
            for i in range(num_workers)
        ]
        
        results = await asyncio.gather(*tasks)
        
        end_time = time.perf_counter()
        total_test_time = end_time - start_time
        
        # Analyze results
        total_operations = sum(r['operations'] for r in results)
        avg_operation_times = [r['avg_time'] for r in results]
        max_operation_times = [r['max_time'] for r in results]
        
        overall_avg_time = statistics.mean(avg_operation_times)
        overall_max_time = max(max_operation_times)
        operations_per_second = total_operations / total_test_time
        
        print(f"\nConcurrent load test results:")
        print(f"Total operations: {total_operations}")
        print(f"Total test time: {total_test_time:.2f}s")
        print(f"Operations per second: {operations_per_second:.0f}")
        print(f"Average operation time: {overall_avg_time:.4f}s")
        print(f"Maximum operation time: {overall_max_time:.4f}s")
        
        # Verify data integrity
        verify_adapter = factory.create(config.database)
        await verify_adapter.connect()
        
        try:
            total_records = await verify_adapter.fetch_one(
                "SELECT COUNT(*) as count FROM concurrent_load_test"
            )
            
            worker_counts = await verify_adapter.fetch_all(
                "SELECT worker_id, COUNT(*) as count FROM concurrent_load_test GROUP BY worker_id ORDER BY worker_id"
            )
            
            print(f"\nData integrity verification:")
            print(f"Total records: {total_records['count']}")
            print("Records per worker:")
            for row in worker_counts:
                print(f"  Worker {row['worker_id']}: {row['count']} records")
            
            # Performance and integrity assertions
            assert operations_per_second > 50  # Should handle at least 50 ops/sec
            assert overall_avg_time < 0.1      # Average operation should be under 100ms
            assert overall_max_time < 1.0      # No operation should take more than 1s
            assert len(worker_counts) == num_workers  # All workers should have inserted data
            
        finally:
            await verify_adapter.disconnect()

    @pytest.mark.asyncio
    async def test_memory_pressure_operations(self, temp_dir: Path):
        """Test operations under memory pressure conditions."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "memory_pressure.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Create table for memory-intensive operations
            await adapter.execute("""
                CREATE TABLE memory_pressure_test (
                    id INTEGER PRIMARY KEY,
                    large_data TEXT,
                    metadata TEXT
                )
            """)
            
            # Track memory usage
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            memory_readings = [initial_memory]
            
            print(f"\nMemory pressure test starting at {initial_memory:.2f} MB")
            
            # Create progressively larger batches
            large_data = "x" * 10000  # 10KB per record
            batch_sizes = [500, 1000, 2000, 3000]
            
            for batch_size in batch_sizes:
                print(f"\nTesting batch size: {batch_size}")
                
                # Clear previous data
                await adapter.execute("DELETE FROM memory_pressure_test")
                
                start_time = time.perf_counter()
                
                # Insert large batch
                batch_data = []
                for i in range(batch_size):
                    batch_data.extend([
                        large_data,
                        f"Metadata for record {i}"
                    ])
                
                placeholders = ",".join(["(?, ?)"] * batch_size)
                await adapter.execute(
                    f"INSERT INTO memory_pressure_test (large_data, metadata) VALUES {placeholders}",
                    batch_data
                )
                
                end_time = time.perf_counter()
                batch_time = end_time - start_time
                
                # Check memory after batch
                current_memory = process.memory_info().rss / 1024 / 1024
                memory_readings.append(current_memory)
                memory_increase = current_memory - initial_memory
                
                print(f"  Batch time: {batch_time:.2f}s")
                print(f"  Memory usage: {current_memory:.2f} MB (+{memory_increase:.2f} MB)")
                print(f"  Records/sec: {batch_size / batch_time:.0f}")
                
                # Create snapshot under memory pressure
                snapshot_engine = SnapshotEngine(config, adapter)
                snapshot_name = f"memory_pressure_snapshot_{batch_size}"
                
                snapshot_start = time.perf_counter()
                await snapshot_engine.create_snapshot(
                    name=snapshot_name,
                    description=f"Snapshot under memory pressure with {batch_size} records",
                    tags=["memory", "pressure", f"batch_{batch_size}"]
                )
                snapshot_end = time.perf_counter()
                
                snapshot_time = snapshot_end - snapshot_start
                snapshot_memory = process.memory_info().rss / 1024 / 1024
                memory_readings.append(snapshot_memory)
                
                print(f"  Snapshot time: {snapshot_time:.2f}s")
                print(f"  Memory after snapshot: {snapshot_memory:.2f} MB")
                
                # Performance assertions for this batch
                assert batch_time < 30.0  # Batch should complete within 30 seconds
                assert snapshot_time < 60.0  # Snapshot should complete within 60 seconds
            
            max_memory = max(memory_readings)
            total_memory_increase = max_memory - initial_memory
            
            print(f"\nMemory pressure test summary:")
            print(f"Initial memory: {initial_memory:.2f} MB")
            print(f"Peak memory: {max_memory:.2f} MB")
            print(f"Total memory increase: {total_memory_increase:.2f} MB")
            
            # Memory usage should be reasonable even under pressure
            assert total_memory_increase < 200  # Should not use more than 200MB additional
            
        finally:
            await adapter.disconnect()


@pytest.mark.performance
class TestLongRunningOperations:
    """Test system behavior during long-running operations."""

    @pytest.mark.asyncio
    async def test_extended_operation_stability(self, temp_dir: Path):
        """Test system stability during extended operations."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "long_running.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            await adapter.execute("""
                CREATE TABLE stability_test (
                    id INTEGER PRIMARY KEY,
                    iteration INTEGER,
                    data TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Simulate long-running operations
            iterations = 50
            records_per_iteration = 1000
            
            print(f"\nExtended stability test: {iterations} iterations, {records_per_iteration} records each")
            
            snapshot_engine = SnapshotEngine(config, adapter)
            iteration_times = []
            
            for iteration in range(iterations):
                iteration_start = time.perf_counter()
                
                # Insert data for this iteration
                batch_data = []
                for i in range(records_per_iteration):
                    batch_data.extend([
                        iteration,
                        f"Data for iteration {iteration}, record {i} " * 2
                    ])
                
                placeholders = ",".join(["(?, ?)"] * records_per_iteration)
                await adapter.execute(
                    f"INSERT INTO stability_test (iteration, data) VALUES {placeholders}",
                    batch_data
                )
                
                # Create snapshot every 10 iterations
                if iteration % 10 == 0:
                    await snapshot_engine.create_snapshot(
                        name=f"stability_snapshot_iter_{iteration}",
                        description=f"Stability test snapshot at iteration {iteration}",
                        tags=["stability", f"iteration_{iteration}"]
                    )
                
                iteration_end = time.perf_counter()
                iteration_time = iteration_end - iteration_start
                iteration_times.append(iteration_time)
                
                if iteration % 10 == 0 or iteration == iterations - 1:
                    avg_time = statistics.mean(iteration_times[-10:])  # Last 10 iterations
                    print(f"  Iteration {iteration}: {iteration_time:.2f}s (avg of last 10: {avg_time:.2f}s)")
                
                # Brief pause between iterations
                await asyncio.sleep(0.1)
            
            # Verify data integrity
            final_count = await adapter.fetch_one("SELECT COUNT(*) as count FROM stability_test")
            expected_count = iterations * records_per_iteration
            
            iteration_counts = await adapter.fetch_all(
                "SELECT iteration, COUNT(*) as count FROM stability_test GROUP BY iteration ORDER BY iteration"
            )
            
            print(f"\nStability test completed:")
            print(f"Expected records: {expected_count}")
            print(f"Actual records: {final_count['count']}")
            print(f"Iterations completed: {len(iteration_counts)}")
            print(f"Average iteration time: {statistics.mean(iteration_times):.2f}s")
            
            # Stability assertions
            assert final_count['count'] == expected_count
            assert len(iteration_counts) == iterations
            
            # Performance should remain stable
            early_avg = statistics.mean(iteration_times[:10])
            late_avg = statistics.mean(iteration_times[-10:])
            performance_degradation = (late_avg - early_avg) / early_avg
            
            print(f"Performance degradation: {performance_degradation:.1%}")
            
            # Performance shouldn't degrade significantly
            assert performance_degradation < 0.5  # Less than 50% degradation
            
        finally:
            await adapter.disconnect()