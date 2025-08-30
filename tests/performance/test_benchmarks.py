"""Performance benchmarks for dbranching operations."""

import asyncio
import time
import tempfile
import statistics
from pathlib import Path
from typing import List, Dict, Any

import pytest

from dbranching.config import DatabaseBranchingConfig
from dbranching.database.factory import DatabaseFactory
from dbranching.snapshot.engine import SnapshotEngine


@pytest.mark.performance
class TestDatabaseOperationsBenchmarks:
    """Benchmarks for database operations."""

    @pytest.mark.asyncio
    async def test_connection_benchmark(self, sqlite_config):
        """Benchmark database connection establishment."""
        factory = DatabaseFactory()
        times = []
        
        for _ in range(10):
            adapter = factory.create(sqlite_config)
            
            start_time = time.perf_counter()
            await adapter.connect()
            await adapter.disconnect()
            end_time = time.perf_counter()
            
            times.append(end_time - start_time)
        
        avg_time = statistics.mean(times)
        median_time = statistics.median(times)
        std_dev = statistics.stdev(times) if len(times) > 1 else 0
        
        print(f"\nConnection Benchmark Results:")
        print(f"Average time: {avg_time:.4f}s")
        print(f"Median time: {median_time:.4f}s")
        print(f"Std deviation: {std_dev:.4f}s")
        print(f"Min time: {min(times):.4f}s")
        print(f"Max time: {max(times):.4f}s")
        
        # Assertions for reasonable performance
        assert avg_time < 0.1  # Should connect in under 100ms on average
        assert max(times) < 0.5  # No connection should take more than 500ms

    @pytest.mark.asyncio
    async def test_bulk_insert_benchmark(self, sqlite_adapter):
        """Benchmark bulk insert operations."""
        await sqlite_adapter.execute("""
            CREATE TABLE benchmark_inserts (
                id INTEGER PRIMARY KEY,
                name TEXT,
                value INTEGER,
                data TEXT
            )
        """)
        
        # Test different batch sizes
        batch_sizes = [100, 500, 1000]
        results = {}
        
        for batch_size in batch_sizes:
            # Prepare data
            data = []
            for i in range(batch_size):
                data.extend([
                    f"name_{i}",
                    i,
                    f"data_{i}" * 10  # Make it somewhat larger
                ])
            
            placeholders = ",".join(["(?, ?, ?)"] * batch_size)
            query = f"INSERT INTO benchmark_inserts (name, value, data) VALUES {placeholders}"
            
            # Clear table
            await sqlite_adapter.execute("DELETE FROM benchmark_inserts")
            
            # Benchmark insertion
            start_time = time.perf_counter()
            await sqlite_adapter.execute(query, data)
            end_time = time.perf_counter()
            
            insert_time = end_time - start_time
            results[batch_size] = {
                'time': insert_time,
                'rate': batch_size / insert_time
            }
            
            print(f"\nBatch size {batch_size}: {insert_time:.4f}s ({results[batch_size]['rate']:.0f} records/sec)")
        
        # Verify performance scales reasonably
        assert results[1000]['rate'] > results[100]['rate']  # Larger batches should be more efficient

    @pytest.mark.asyncio
    async def test_query_performance_benchmark(self, sqlite_adapter):
        """Benchmark query performance with different data sizes."""
        await sqlite_adapter.execute("""
            CREATE TABLE benchmark_queries (
                id INTEGER PRIMARY KEY,
                category TEXT,
                value INTEGER,
                description TEXT
            )
        """)
        
        # Insert test data
        test_sizes = [1000, 5000, 10000]
        
        for size in test_sizes:
            # Clear and populate
            await sqlite_adapter.execute("DELETE FROM benchmark_queries")
            
            # Insert in batches
            batch_size = 500
            for batch_start in range(0, size, batch_size):
                batch_data = []
                for i in range(batch_start, min(batch_start + batch_size, size)):
                    batch_data.extend([
                        f"category_{i % 10}",  # 10 categories
                        i,
                        f"Description for record {i}"
                    ])
                
                placeholders = ",".join(["(?, ?, ?)"] * (len(batch_data) // 3))
                await sqlite_adapter.execute(
                    f"INSERT INTO benchmark_queries (category, value, description) VALUES {placeholders}",
                    batch_data
                )
            
            # Benchmark different query types
            queries = {
                'simple_select': "SELECT COUNT(*) FROM benchmark_queries",
                'filtered_select': "SELECT * FROM benchmark_queries WHERE category = 'category_5'",
                'aggregation': "SELECT category, COUNT(*), AVG(value) FROM benchmark_queries GROUP BY category",
                'range_query': f"SELECT * FROM benchmark_queries WHERE value BETWEEN {size//4} AND {size//2}"
            }
            
            print(f"\nQuery benchmarks for {size} records:")
            
            for query_name, query in queries.items():
                start_time = time.perf_counter()
                result = await sqlite_adapter.fetch_all(query)
                end_time = time.perf_counter()
                
                query_time = end_time - start_time
                print(f"  {query_name}: {query_time:.4f}s ({len(result)} results)")
                
                # Basic performance assertions
                assert query_time < 1.0  # No query should take more than 1 second


@pytest.mark.performance
class TestSnapshotBenchmarks:
    """Benchmarks for snapshot operations."""

    @pytest.mark.asyncio
    async def test_snapshot_creation_benchmark(self, temp_dir: Path):
        """Benchmark snapshot creation with different data sizes."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "benchmark.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            await adapter.execute("""
                CREATE TABLE snapshot_benchmark (
                    id INTEGER PRIMARY KEY,
                    data TEXT,
                    metadata TEXT
                )
            """)
            
            snapshot_engine = SnapshotEngine(config, adapter)
            data_sizes = [1000, 2500, 5000]
            
            for size in data_sizes:
                # Clear and populate with test data
                await adapter.execute("DELETE FROM snapshot_benchmark")
                
                batch_size = 500
                for batch_start in range(0, size, batch_size):
                    batch_data = []
                    for i in range(batch_start, min(batch_start + batch_size, size)):
                        batch_data.extend([
                            f"Data record {i} with some content " * 5,
                            f"Metadata for record {i}"
                        ])
                    
                    placeholders = ",".join(["(?, ?)"] * (len(batch_data) // 2))
                    await adapter.execute(
                        f"INSERT INTO snapshot_benchmark (data, metadata) VALUES {placeholders}",
                        batch_data
                    )
                
                # Benchmark snapshot creation
                snapshot_name = f"benchmark_snapshot_{size}"
                
                start_time = time.perf_counter()
                metadata = await snapshot_engine.create_snapshot(
                    name=snapshot_name,
                    description=f"Benchmark snapshot with {size} records",
                    tags=["benchmark"]
                )
                end_time = time.perf_counter()
                
                creation_time = end_time - start_time
                print(f"\nSnapshot creation for {size} records: {creation_time:.4f}s")
                
                # Basic performance assertions
                assert creation_time < 10.0  # Should complete within 10 seconds
                assert metadata.name == snapshot_name
                
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_snapshot_restoration_benchmark(self, temp_dir: Path):
        """Benchmark snapshot restoration performance."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "restore_benchmark.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Create test table and data
            await adapter.execute("""
                CREATE TABLE restore_benchmark (
                    id INTEGER PRIMARY KEY,
                    original_data TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert original data
            original_size = 3000
            batch_size = 500
            
            for batch_start in range(0, original_size, batch_size):
                batch_data = []
                for i in range(batch_start, min(batch_start + batch_size, original_size)):
                    batch_data.append(f"Original data {i} " * 8)
                
                placeholders = ",".join(["(?)"] * len(batch_data))
                await adapter.execute(
                    f"INSERT INTO restore_benchmark (original_data) VALUES {placeholders}",
                    batch_data
                )
            
            # Create snapshot
            snapshot_engine = SnapshotEngine(config, adapter)
            snapshot_name = "restore_benchmark_snapshot"
            
            await snapshot_engine.create_snapshot(
                name=snapshot_name,
                description="Benchmark snapshot for restoration testing",
                tags=["benchmark", "restore"]
            )
            
            # Modify data significantly
            await adapter.execute("""
                UPDATE restore_benchmark 
                SET original_data = 'Modified data ' || id 
                WHERE id <= ?
            """, (original_size // 2,))
            
            await adapter.execute("""
                INSERT INTO restore_benchmark (original_data) 
                SELECT 'Additional data ' || (id + ?) 
                FROM restore_benchmark 
                WHERE id <= ?
            """, (original_size, original_size // 4))
            
            # Benchmark restoration
            start_time = time.perf_counter()
            await snapshot_engine.restore_snapshot(snapshot_name)
            end_time = time.perf_counter()
            
            restoration_time = end_time - start_time
            print(f"\nSnapshot restoration time: {restoration_time:.4f}s")
            
            # Verify restoration worked
            count_result = await adapter.fetch_one("SELECT COUNT(*) as count FROM restore_benchmark")
            assert count_result["count"] == original_size
            
            # Performance assertion
            assert restoration_time < 15.0  # Should restore within 15 seconds
            
        finally:
            await adapter.disconnect()


@pytest.mark.performance
class TestMemoryUsageBenchmarks:
    """Benchmarks for memory usage patterns."""

    @pytest.mark.asyncio
    async def test_memory_usage_during_operations(self, temp_dir: Path):
        """Test memory usage patterns during various operations."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "memory_test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        adapter = factory.create(config.database)
        
        await adapter.connect()
        try:
            # Baseline memory
            baseline_memory = process.memory_info().rss / 1024 / 1024  # MB
            print(f"\nBaseline memory usage: {baseline_memory:.2f} MB")
            
            # Create table
            await adapter.execute("""
                CREATE TABLE memory_test (
                    id INTEGER PRIMARY KEY,
                    large_data TEXT
                )
            """)
            
            # Test memory during large inserts
            large_data_size = 5000
            large_data = "x" * 1000  # 1KB per record
            
            pre_insert_memory = process.memory_info().rss / 1024 / 1024
            
            batch_size = 500
            for batch_start in range(0, large_data_size, batch_size):
                batch_data = [large_data] * min(batch_size, large_data_size - batch_start)
                placeholders = ",".join(["(?)"] * len(batch_data))
                await adapter.execute(
                    f"INSERT INTO memory_test (large_data) VALUES {placeholders}",
                    batch_data
                )
            
            post_insert_memory = process.memory_info().rss / 1024 / 1024
            insert_memory_delta = post_insert_memory - pre_insert_memory
            
            print(f"Memory after large insert: {post_insert_memory:.2f} MB (+{insert_memory_delta:.2f} MB)")
            
            # Test memory during snapshot creation
            snapshot_engine = SnapshotEngine(config, adapter)
            
            pre_snapshot_memory = process.memory_info().rss / 1024 / 1024
            
            await snapshot_engine.create_snapshot(
                name="memory_test_snapshot",
                description="Testing memory usage",
                tags=["memory", "test"]
            )
            
            post_snapshot_memory = process.memory_info().rss / 1024 / 1024
            snapshot_memory_delta = post_snapshot_memory - pre_snapshot_memory
            
            print(f"Memory after snapshot: {post_snapshot_memory:.2f} MB (+{snapshot_memory_delta:.2f} MB)")
            
            # Memory usage should be reasonable
            total_memory_increase = post_snapshot_memory - baseline_memory
            assert total_memory_increase < 100  # Should not use more than 100MB additional
            
        finally:
            await adapter.disconnect()


@pytest.mark.performance
class TestConcurrencyBenchmarks:
    """Benchmarks for concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_read_performance(self, temp_dir: Path):
        """Benchmark concurrent read operations."""
        config_data = {
            "database": {"type": "sqlite", "database": str(temp_dir / "concurrent_test.db")},
            "storage": {"directory": str(temp_dir / "snapshots")},
        }
        
        config = DatabaseBranchingConfig(**config_data)
        factory = DatabaseFactory()
        
        # Set up test data with single connection
        setup_adapter = factory.create(config.database)
        await setup_adapter.connect()
        
        try:
            await setup_adapter.execute("""
                CREATE TABLE concurrent_reads (
                    id INTEGER PRIMARY KEY,
                    category INTEGER,
                    data TEXT
                )
            """)
            
            # Insert test data
            test_data = []
            for i in range(2000):
                test_data.extend([i % 10, f"Data for record {i}"])
            
            placeholders = ",".join(["(?, ?)"] * (len(test_data) // 2))
            await setup_adapter.execute(
                f"INSERT INTO concurrent_reads (category, data) VALUES {placeholders}",
                test_data
            )
            
        finally:
            await setup_adapter.disconnect()
        
        # Test concurrent reads
        async def concurrent_reader(reader_id: int, query_count: int):
            """Perform concurrent reads."""
            adapter = factory.create(config.database)
            await adapter.connect()
            
            try:
                start_time = time.perf_counter()
                
                for i in range(query_count):
                    category = i % 10
                    await adapter.fetch_all(
                        "SELECT * FROM concurrent_reads WHERE category = ? LIMIT 50",
                        (category,)
                    )
                
                end_time = time.perf_counter()
                return end_time - start_time
                
            finally:
                await adapter.disconnect()
        
        # Run concurrent readers
        num_readers = 5
        queries_per_reader = 50
        
        start_time = time.perf_counter()
        
        tasks = [
            asyncio.create_task(concurrent_reader(i, queries_per_reader))
            for i in range(num_readers)
        ]
        
        reader_times = await asyncio.gather(*tasks)
        
        end_time = time.perf_counter()
        total_time = end_time - start_time
        
        total_queries = num_readers * queries_per_reader
        queries_per_second = total_queries / total_time
        
        print(f"\nConcurrent read benchmark:")
        print(f"Total queries: {total_queries}")
        print(f"Total time: {total_time:.4f}s")
        print(f"Queries per second: {queries_per_second:.2f}")
        print(f"Average reader time: {statistics.mean(reader_times):.4f}s")
        
        # Performance assertions
        assert queries_per_second > 100  # Should handle at least 100 queries/second
        assert max(reader_times) < 5.0   # No reader should take more than 5 seconds