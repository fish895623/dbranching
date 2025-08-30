"""Compression system for snapshot operations."""

import asyncio
import gzip
import hashlib
import logging
import time
from pathlib import Path
from typing import Optional, Tuple, BinaryIO
import io

from ..exceptions import SnapshotError, StorageError
from .models import CompressionType, CompressionMetrics

logger = logging.getLogger(__name__)

# Chunk size for streaming operations (8MB)
CHUNK_SIZE = 8 * 1024 * 1024


class CompressionEngine:
    """High-performance compression engine with integrity verification."""
    
    def __init__(self):
        """Initialize compression engine."""
        self._supported_types = {
            CompressionType.NONE,
            CompressionType.GZIP,
        }
        # Future: Add LZ4 and ZSTD support
    
    async def compress_file(
        self,
        input_path: Path,
        output_path: Path,
        compression_type: CompressionType = CompressionType.GZIP,
        compression_level: int = 6,
        verify_integrity: bool = True
    ) -> CompressionMetrics:
        """
        Compress file with streaming for memory efficiency.
        
        Args:
            input_path: Path to input file
            output_path: Path to output compressed file
            compression_type: Type of compression to use
            compression_level: Compression level (1-9)
            verify_integrity: Whether to verify integrity after compression
            
        Returns:
            CompressionMetrics with performance data
            
        Raises:
            SnapshotError: If compression fails
            StorageError: If file I/O fails
        """
        if compression_type not in self._supported_types:
            raise SnapshotError(f"Unsupported compression type: {compression_type}")
        
        if not input_path.exists():
            raise StorageError(f"Input file not found: {input_path}")
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        start_time = time.time()
        original_size = input_path.stat().st_size
        
        try:
            if compression_type == CompressionType.NONE:
                # No compression - just copy
                await self._copy_file_async(input_path, output_path)
                compressed_size = original_size
                
            elif compression_type == CompressionType.GZIP:
                compressed_size = await self._compress_gzip_async(
                    input_path, output_path, compression_level
                )
            else:
                raise SnapshotError(f"Compression type {compression_type} not yet implemented")
            
            compression_time = time.time() - start_time
            compression_ratio = original_size / compressed_size if compressed_size > 0 else 0
            compression_speed = (original_size / (1024 * 1024)) / compression_time if compression_time > 0 else 0
            
            metrics = CompressionMetrics(
                original_size_bytes=original_size,
                compressed_size_bytes=compressed_size,
                compression_ratio=compression_ratio,
                compression_time_seconds=compression_time,
                compression_speed_mbps=compression_speed
            )
            
            # Verify integrity if requested
            if verify_integrity:
                await self._verify_compressed_file_integrity(
                    input_path, output_path, compression_type
                )
            
            logger.info(f"Compressed {input_path.name}: {original_size} -> {compressed_size} bytes "
                       f"({compression_ratio:.2f}x, {compression_speed:.1f} MB/s)")
            
            return metrics
            
        except Exception as e:
            # Clean up partial output file on error
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup partial compressed file: {cleanup_error}")
            
            if isinstance(e, (SnapshotError, StorageError)):
                raise
            else:
                raise SnapshotError(f"Compression failed: {str(e)}")
    
    async def decompress_file(
        self,
        input_path: Path,
        output_path: Path,
        compression_type: CompressionType,
        verify_integrity: bool = True
    ) -> CompressionMetrics:
        """
        Decompress file with streaming for memory efficiency.
        
        Args:
            input_path: Path to compressed input file
            output_path: Path to decompressed output file
            compression_type: Type of compression used
            verify_integrity: Whether to verify integrity after decompression
            
        Returns:
            CompressionMetrics with performance data
            
        Raises:
            SnapshotError: If decompression fails
            StorageError: If file I/O fails
        """
        if compression_type not in self._supported_types:
            raise SnapshotError(f"Unsupported compression type: {compression_type}")
        
        if not input_path.exists():
            raise StorageError(f"Compressed file not found: {input_path}")
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        start_time = time.time()
        compressed_size = input_path.stat().st_size
        
        try:
            if compression_type == CompressionType.NONE:
                # No compression - just copy
                await self._copy_file_async(input_path, output_path)
                original_size = compressed_size
                
            elif compression_type == CompressionType.GZIP:
                original_size = await self._decompress_gzip_async(input_path, output_path)
            else:
                raise SnapshotError(f"Compression type {compression_type} not yet implemented")
            
            decompression_time = time.time() - start_time
            compression_ratio = original_size / compressed_size if compressed_size > 0 else 0
            decompression_speed = (original_size / (1024 * 1024)) / decompression_time if decompression_time > 0 else 0
            
            metrics = CompressionMetrics(
                original_size_bytes=original_size,
                compressed_size_bytes=compressed_size,
                compression_ratio=compression_ratio,
                compression_time_seconds=decompression_time,
                compression_speed_mbps=decompression_speed
            )
            
            logger.info(f"Decompressed {input_path.name}: {compressed_size} -> {original_size} bytes "
                       f"({compression_ratio:.2f}x, {decompression_speed:.1f} MB/s)")
            
            return metrics
            
        except Exception as e:
            # Clean up partial output file on error
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup partial decompressed file: {cleanup_error}")
            
            if isinstance(e, (SnapshotError, StorageError)):
                raise
            else:
                raise SnapshotError(f"Decompression failed: {str(e)}")
    
    async def _copy_file_async(self, input_path: Path, output_path: Path) -> None:
        """Copy file asynchronously using thread pool."""
        import shutil
        await asyncio.get_event_loop().run_in_executor(
            None, shutil.copy2, input_path, output_path
        )
    
    async def _compress_gzip_async(
        self,
        input_path: Path,
        output_path: Path,
        compression_level: int
    ) -> int:
        """Compress file using gzip with streaming."""
        compressed_size = 0
        
        def _compress_sync():
            nonlocal compressed_size
            with open(input_path, 'rb') as input_file:
                with gzip.open(output_path, 'wb', compresslevel=compression_level) as output_file:
                    while True:
                        chunk = input_file.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        output_file.write(chunk)
                        compressed_size += len(chunk)
            
            # Get actual compressed file size
            compressed_size = output_path.stat().st_size
            return compressed_size
        
        # Run compression in thread to avoid blocking
        compressed_size = await asyncio.get_event_loop().run_in_executor(None, _compress_sync)
        return compressed_size
    
    async def _decompress_gzip_async(self, input_path: Path, output_path: Path) -> int:
        """Decompress gzip file with streaming."""
        original_size = 0
        
        def _decompress_sync():
            nonlocal original_size
            with gzip.open(input_path, 'rb') as input_file:
                with open(output_path, 'wb') as output_file:
                    while True:
                        chunk = input_file.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        output_file.write(chunk)
                        original_size += len(chunk)
            return original_size
        
        # Run decompression in thread to avoid blocking
        original_size = await asyncio.get_event_loop().run_in_executor(None, _decompress_sync)
        return original_size
    
    async def _verify_compressed_file_integrity(
        self,
        original_path: Path,
        compressed_path: Path,
        compression_type: CompressionType
    ) -> None:
        """Verify integrity of compressed file by decompressing and comparing checksums."""
        logger.debug(f"Verifying integrity of compressed file: {compressed_path}")
        
        # Calculate checksum of original file
        original_checksum = await self._calculate_file_checksum(original_path)
        
        # Create temporary file for decompression test
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        
        try:
            # Decompress to temporary file
            await self.decompress_file(
                compressed_path, temp_path, compression_type, verify_integrity=False
            )
            
            # Calculate checksum of decompressed file
            decompressed_checksum = await self._calculate_file_checksum(temp_path)
            
            # Compare checksums
            if original_checksum != decompressed_checksum:
                raise SnapshotError(
                    f"Integrity verification failed: original checksum {original_checksum} "
                    f"!= decompressed checksum {decompressed_checksum}"
                )
            
            logger.debug("Compressed file integrity verified successfully")
            
        finally:
            # Clean up temporary file
            if temp_path.exists():
                temp_path.unlink()
    
    async def _calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file."""
        def _calculate_sync():
            hash_sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                while chunk := f.read(CHUNK_SIZE):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        
        return await asyncio.get_event_loop().run_in_executor(None, _calculate_sync)
    
    async def get_compression_info(self, file_path: Path) -> dict:
        """Get information about compressed file."""
        if not file_path.exists():
            raise StorageError(f"File not found: {file_path}")
        
        info = {
            "size_bytes": file_path.stat().st_size,
            "checksum": await self._calculate_file_checksum(file_path),
        }
        
        # Try to detect compression type from file extension or magic bytes
        if file_path.suffix.lower() == '.gz':
            info["compression_type"] = CompressionType.GZIP
            info["is_compressed"] = True
            
            # Try to get original size from gzip header (last 4 bytes)
            try:
                def _get_gzip_original_size():
                    with open(file_path, 'rb') as f:
                        f.seek(-4, 2)  # Go to last 4 bytes
                        return int.from_bytes(f.read(4), 'little')
                
                original_size = await asyncio.get_event_loop().run_in_executor(
                    None, _get_gzip_original_size
                )
                info["original_size_bytes"] = original_size
                info["compression_ratio"] = original_size / info["size_bytes"]
                
            except Exception as e:
                logger.debug(f"Could not read gzip original size: {e}")
                
        else:
            info["compression_type"] = CompressionType.NONE
            info["is_compressed"] = False
            info["original_size_bytes"] = info["size_bytes"]
            info["compression_ratio"] = 1.0
        
        return info
    
    def get_supported_types(self) -> set[CompressionType]:
        """Get set of supported compression types."""
        return self._supported_types.copy()
    
    def estimate_compressed_size(
        self,
        original_size: int,
        compression_type: CompressionType,
        data_type_hint: Optional[str] = None
    ) -> int:
        """
        Estimate compressed size based on compression type and data characteristics.
        
        Args:
            original_size: Original file size in bytes
            compression_type: Type of compression
            data_type_hint: Hint about data type for better estimation
            
        Returns:
            Estimated compressed size in bytes
        """
        if compression_type == CompressionType.NONE:
            return original_size
        
        # Compression ratio estimates based on typical database dumps
        compression_ratios = {
            CompressionType.GZIP: 0.3,  # ~70% compression
        }
        
        # Adjust based on data type hints
        ratio_adjustments = {
            "schema": 0.8,  # Schema compresses very well (text-heavy)
            "data": 1.0,    # Data compression varies
            "binary": 1.2,  # Binary data compresses less
        }
        
        base_ratio = compression_ratios.get(compression_type, 1.0)
        adjustment = ratio_adjustments.get(data_type_hint, 1.0)
        
        estimated_size = int(original_size * base_ratio * adjustment)
        
        # Ensure minimum size (compressed files have overhead)
        return max(estimated_size, 1024)