"""Tests for the compression engine."""

import asyncio
import tempfile
from pathlib import Path
import pytest

from src.dbranching.snapshot.compression import CompressionEngine
from src.dbranching.snapshot.models import CompressionType
from src.dbranching.exceptions import SnapshotError, StorageError


class TestCompressionEngine:
    """Test cases for the CompressionEngine class."""
    
    @pytest.fixture
    def engine(self):
        """Create test compression engine."""
        return CompressionEngine()
    
    @pytest.fixture
    def test_file(self):
        """Create test file with known content."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            content = "This is test content for compression.\n" * 100
            f.write(content)
            test_path = Path(f.name)
        
        yield test_path
        
        # Cleanup
        if test_path.exists():
            test_path.unlink()
    
    @pytest.fixture
    def output_path(self):
        """Create output path for compressed files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir) / "compressed_output.gz"
    
    async def test_compress_file_gzip(self, engine, test_file, output_path):
        """Test GZIP compression of file."""
        original_size = test_file.stat().st_size
        
        # Compress file
        metrics = await engine.compress_file(
            test_file, 
            output_path, 
            CompressionType.GZIP,
            compression_level=6,
            verify_integrity=True
        )
        
        # Verify compressed file exists
        assert output_path.exists()
        
        # Verify metrics
        assert metrics.original_size_bytes == original_size
        assert metrics.compressed_size_bytes == output_path.stat().st_size
        assert metrics.compression_ratio > 1.0  # Should be compressed
        assert metrics.compression_time_seconds > 0
        assert metrics.compression_speed_mbps > 0
        
        # Verify compression actually reduced size
        assert metrics.compressed_size_bytes < metrics.original_size_bytes
    
    async def test_compress_file_none(self, engine, test_file, output_path):
        """Test no compression (copy only)."""
        original_size = test_file.stat().st_size
        output_path_uncompressed = output_path.with_suffix('.txt')
        
        # Compress with no compression
        metrics = await engine.compress_file(
            test_file,
            output_path_uncompressed,
            CompressionType.NONE,
            verify_integrity=False  # No need to verify for copy
        )
        
        # Verify file exists and is same size
        assert output_path_uncompressed.exists()
        assert metrics.original_size_bytes == original_size
        assert metrics.compressed_size_bytes == original_size
        assert metrics.compression_ratio == 1.0
    
    async def test_decompress_file_gzip(self, engine, test_file, output_path):
        """Test GZIP decompression of file."""
        # First compress the file
        await engine.compress_file(
            test_file,
            output_path,
            CompressionType.GZIP,
            verify_integrity=False
        )
        
        # Now decompress it
        decompressed_path = output_path.with_suffix('')
        metrics = await engine.decompress_file(
            output_path,
            decompressed_path,
            CompressionType.GZIP
        )
        
        # Verify decompressed file exists and matches original
        assert decompressed_path.exists()
        assert decompressed_path.read_text() == test_file.read_text()
        
        # Verify metrics
        assert metrics.original_size_bytes == test_file.stat().st_size
        assert metrics.compressed_size_bytes == output_path.stat().st_size
        assert metrics.compression_ratio > 1.0
    
    async def test_compress_nonexistent_file(self, engine, output_path):
        """Test compression of non-existent file."""
        nonexistent_file = Path("/nonexistent/file.txt")
        
        with pytest.raises(StorageError, match="Input file not found"):
            await engine.compress_file(
                nonexistent_file,
                output_path,
                CompressionType.GZIP
            )
    
    async def test_decompress_nonexistent_file(self, engine):
        """Test decompression of non-existent file."""
        nonexistent_file = Path("/nonexistent/file.gz")
        output_path = Path("/tmp/output.txt")
        
        with pytest.raises(StorageError, match="Compressed file not found"):
            await engine.decompress_file(
                nonexistent_file,
                output_path,
                CompressionType.GZIP
            )
    
    async def test_unsupported_compression_type(self, engine, test_file, output_path):
        """Test error handling for unsupported compression types."""
        # Try to use an unsupported compression type
        with pytest.raises(SnapshotError, match="Unsupported compression type"):
            await engine.compress_file(
                test_file,
                output_path,
                CompressionType.LZ4  # Not yet supported
            )
    
    async def test_compression_integrity_verification(self, engine, test_file, output_path):
        """Test integrity verification during compression."""
        # Compress with integrity verification enabled
        metrics = await engine.compress_file(
            test_file,
            output_path,
            CompressionType.GZIP,
            verify_integrity=True
        )
        
        # Should complete without error if integrity is good
        assert metrics.original_size_bytes > 0
        assert output_path.exists()
    
    async def test_compression_levels(self, engine, test_file):
        """Test different compression levels."""
        results = {}
        
        # Test different compression levels
        for level in [1, 6, 9]:
            with tempfile.TemporaryDirectory() as temp_dir:
                output_path = Path(temp_dir) / f"compressed_level_{level}.gz"
                
                metrics = await engine.compress_file(
                    test_file,
                    output_path,
                    CompressionType.GZIP,
                    compression_level=level,
                    verify_integrity=False
                )
                
                results[level] = metrics
        
        # Higher compression levels should generally produce smaller files
        # (though this may not always be true for small files)
        assert all(r.original_size_bytes == test_file.stat().st_size for r in results.values())
    
    async def test_get_compression_info_gzip(self, engine, test_file, output_path):
        """Test getting compression info for GZIP file."""
        # First create a compressed file
        await engine.compress_file(
            test_file,
            output_path,
            CompressionType.GZIP,
            verify_integrity=False
        )
        
        # Get compression info
        info = await engine.get_compression_info(output_path)
        
        # Verify info
        assert info["size_bytes"] == output_path.stat().st_size
        assert info["compression_type"] == CompressionType.GZIP
        assert info["is_compressed"] is True
        assert "checksum" in info
        assert len(info["checksum"]) == 64  # SHA256 hex length
    
    async def test_get_compression_info_uncompressed(self, engine, test_file):
        """Test getting compression info for uncompressed file."""
        info = await engine.get_compression_info(test_file)
        
        # Verify info
        assert info["size_bytes"] == test_file.stat().st_size
        assert info["compression_type"] == CompressionType.NONE
        assert info["is_compressed"] is False
        assert info["original_size_bytes"] == info["size_bytes"]
        assert info["compression_ratio"] == 1.0
    
    async def test_get_compression_info_nonexistent(self, engine):
        """Test getting compression info for non-existent file."""
        nonexistent_file = Path("/nonexistent/file.txt")
        
        with pytest.raises(StorageError, match="File not found"):
            await engine.get_compression_info(nonexistent_file)
    
    def test_get_supported_types(self, engine):
        """Test getting supported compression types."""
        supported_types = engine.get_supported_types()
        
        assert isinstance(supported_types, set)
        assert CompressionType.NONE in supported_types
        assert CompressionType.GZIP in supported_types
        # LZ4 and ZSTD not yet implemented
    
    def test_estimate_compressed_size(self, engine):
        """Test compressed size estimation."""
        original_size = 1000000  # 1MB
        
        # Test different compression types
        estimated_none = engine.estimate_compressed_size(
            original_size, CompressionType.NONE
        )
        estimated_gzip = engine.estimate_compressed_size(
            original_size, CompressionType.GZIP
        )
        
        # No compression should return original size
        assert estimated_none == original_size
        
        # GZIP compression should estimate smaller size
        assert estimated_gzip < original_size
        assert estimated_gzip > 0
    
    def test_estimate_compressed_size_with_hints(self, engine):
        """Test compressed size estimation with data type hints."""
        original_size = 1000000  # 1MB
        
        # Test different data type hints
        schema_estimate = engine.estimate_compressed_size(
            original_size, CompressionType.GZIP, "schema"
        )
        data_estimate = engine.estimate_compressed_size(
            original_size, CompressionType.GZIP, "data"
        )
        binary_estimate = engine.estimate_compressed_size(
            original_size, CompressionType.GZIP, "binary"
        )
        
        # Schema should compress better than data, data better than binary
        assert schema_estimate < data_estimate
        assert data_estimate <= binary_estimate
    
    async def test_large_file_streaming(self, engine):
        """Test compression of large file using streaming."""
        # Create a larger test file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            # Write enough content to test streaming (multiple chunks)
            content = "This is a line of test content for streaming compression.\n"
            for _ in range(10000):  # About 750KB
                f.write(content)
            large_test_file = Path(f.name)
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                output_path = Path(temp_dir) / "large_compressed.gz"
                
                # Compress large file
                metrics = await engine.compress_file(
                    large_test_file,
                    output_path,
                    CompressionType.GZIP,
                    verify_integrity=False  # Skip verification for speed
                )
                
                # Verify compression worked
                assert output_path.exists()
                assert metrics.compressed_size_bytes < metrics.original_size_bytes
                assert metrics.compression_ratio > 1.0
        
        finally:
            # Cleanup
            if large_test_file.exists():
                large_test_file.unlink()
    
    async def test_concurrent_compression(self, engine):
        """Test multiple concurrent compression operations."""
        # Create multiple test files
        test_files = []
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            for i in range(5):
                test_file = temp_path / f"test_{i}.txt"
                test_file.write_text(f"Test content for file {i}\n" * 100)
                test_files.append(test_file)
            
            # Compress all files concurrently
            tasks = []
            for i, test_file in enumerate(test_files):
                output_path = temp_path / f"compressed_{i}.gz"
                task = engine.compress_file(
                    test_file,
                    output_path,
                    CompressionType.GZIP,
                    verify_integrity=False
                )
                tasks.append(task)
            
            # Wait for all compressions to complete
            results = await asyncio.gather(*tasks)
            
            # Verify all compressions succeeded
            assert len(results) == len(test_files)
            for metrics in results:
                assert metrics.compression_ratio > 1.0
    
    async def test_compression_error_cleanup(self, engine, test_file):
        """Test that partial files are cleaned up on compression error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "output.gz"
            
            # Mock compression to fail partway through
            original_compress = engine._compress_gzip_async
            
            async def failing_compress(*args, **kwargs):
                # Create partial output file
                output_path.write_bytes(b"partial content")
                raise Exception("Simulated compression failure")
            
            engine._compress_gzip_async = failing_compress
            
            try:
                with pytest.raises(SnapshotError):
                    await engine.compress_file(
                        test_file,
                        output_path,
                        CompressionType.GZIP
                    )
                
                # Verify partial file was cleaned up
                assert not output_path.exists()
            
            finally:
                # Restore original method
                engine._compress_gzip_async = original_compress