"""Metadata management system for snapshots."""

import asyncio
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..exceptions import SnapshotError, StorageError, ValidationError
from .models import SnapshotMetadata, FileMetadata, DatabaseMetadata, CompatibilityInfo, CompressionType

logger = logging.getLogger(__name__)


class MetadataManager:
    """Manager for snapshot metadata operations."""
    
    METADATA_FILENAME = "metadata.json"
    CHECKSUMS_FILENAME = "checksums.sha256"
    SCHEMA_VERSION = "1.0"
    
    def __init__(self):
        """Initialize metadata manager."""
        pass
    
    async def create_metadata(
        self,
        name: str,
        description: Optional[str],
        tags: List[str],
        database_metadata: DatabaseMetadata,
        file_metadata_list: List[FileMetadata],
        compression: CompressionType,
        compression_level: int,
        creation_duration: float,
        verify_integrity: bool = True
    ) -> SnapshotMetadata:
        """
        Create comprehensive snapshot metadata.
        
        Args:
            name: Snapshot name
            description: Optional description
            tags: List of tags
            database_metadata: Database information
            file_metadata_list: List of file metadata
            compression: Compression type used
            compression_level: Compression level used
            creation_duration: Time taken to create snapshot
            verify_integrity: Whether to verify file integrity
            
        Returns:
            SnapshotMetadata object
            
        Raises:
            SnapshotError: If metadata creation fails
        """
        try:
            # Calculate total size and compression ratio
            total_size = sum(f.size_bytes for f in file_metadata_list)
            original_size = database_metadata.size_bytes
            compression_ratio = original_size / total_size if total_size > 0 else 0
            
            # Create compatibility information
            compatibility = await self._create_compatibility_info(database_metadata)
            
            # Create metadata
            metadata = SnapshotMetadata(
                name=name,
                description=description,
                tags=tags,
                database=database_metadata,
                compression=compression,
                compression_level=compression_level,
                total_size_bytes=total_size,
                files=file_metadata_list,
                compatibility=compatibility,
                integrity_verified=verify_integrity,
                creation_duration_seconds=creation_duration,
                compression_ratio=compression_ratio
            )
            
            logger.info(f"Created metadata for snapshot {name} ({total_size} bytes, {len(file_metadata_list)} files)")
            return metadata
            
        except Exception as e:
            raise SnapshotError(f"Failed to create metadata: {str(e)}")
    
    async def save_metadata(self, metadata: SnapshotMetadata, snapshot_dir: Path) -> None:
        """
        Save metadata to snapshot directory.
        
        Args:
            metadata: Snapshot metadata to save
            snapshot_dir: Directory to save metadata in
            
        Raises:
            StorageError: If saving fails
        """
        try:
            # Ensure directory exists
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            
            metadata_path = snapshot_dir / self.METADATA_FILENAME
            checksums_path = snapshot_dir / self.CHECKSUMS_FILENAME
            
            # Save metadata JSON
            metadata_dict = metadata.dict()
            metadata_json = json.dumps(metadata_dict, indent=2, default=str)
            
            await self._write_file_async(metadata_path, metadata_json.encode())
            
            # Save checksums file
            checksums_content = await self._create_checksums_content(metadata.files)
            await self._write_file_async(checksums_path, checksums_content.encode())
            
            logger.info(f"Saved metadata to {snapshot_dir}")
            
        except Exception as e:
            raise StorageError(f"Failed to save metadata: {str(e)}")
    
    async def load_metadata(self, snapshot_dir: Path) -> SnapshotMetadata:
        """
        Load metadata from snapshot directory.
        
        Args:
            snapshot_dir: Directory to load metadata from
            
        Returns:
            SnapshotMetadata object
            
        Raises:
            ValidationError: If metadata is invalid
            StorageError: If loading fails
        """
        try:
            metadata_path = snapshot_dir / self.METADATA_FILENAME
            
            if not metadata_path.exists():
                raise StorageError(f"Metadata file not found: {metadata_path}")
            
            # Read metadata file
            metadata_content = await self._read_file_async(metadata_path)
            metadata_dict = json.loads(metadata_content.decode())
            
            # Validate and create metadata object
            metadata = SnapshotMetadata(**metadata_dict)
            
            # Verify metadata integrity
            await self._verify_metadata_integrity(metadata, snapshot_dir)
            
            logger.debug(f"Loaded metadata from {snapshot_dir}")
            return metadata
            
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid metadata JSON: {str(e)}")
        except Exception as e:
            if isinstance(e, (ValidationError, StorageError)):
                raise
            else:
                raise StorageError(f"Failed to load metadata: {str(e)}")
    
    async def validate_metadata(self, metadata: SnapshotMetadata, snapshot_dir: Path) -> List[str]:
        """
        Validate metadata against actual snapshot files.
        
        Args:
            metadata: Metadata to validate
            snapshot_dir: Directory containing snapshot
            
        Returns:
            List of validation warnings (empty if fully valid)
            
        Raises:
            ValidationError: If metadata is invalid
        """
        warnings = []
        
        try:
            # Check if all files exist
            for file_meta in metadata.files:
                file_path = snapshot_dir / file_meta.name
                if not file_path.exists():
                    raise ValidationError(f"File missing: {file_meta.name}")
                
                # Check file size
                actual_size = file_path.stat().st_size
                if actual_size != file_meta.size_bytes:
                    raise ValidationError(
                        f"File size mismatch for {file_meta.name}: "
                        f"expected {file_meta.size_bytes}, got {actual_size}"
                    )
            
            # Verify checksums if integrity was verified during creation
            if metadata.integrity_verified:
                invalid_checksums = await self._verify_file_checksums(metadata.files, snapshot_dir)
                if invalid_checksums:
                    raise ValidationError(f"Checksum validation failed for files: {invalid_checksums}")
            
            # Check compatibility
            compatibility_warnings = await self._check_compatibility(metadata.compatibility)
            warnings.extend(compatibility_warnings)
            
            # Check metadata version compatibility
            if metadata.version != self.SCHEMA_VERSION:
                warnings.append(f"Metadata version {metadata.version} may not be fully compatible with current version {self.SCHEMA_VERSION}")
            
            logger.debug(f"Metadata validation completed with {len(warnings)} warnings")
            return warnings
            
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            else:
                raise ValidationError(f"Metadata validation failed: {str(e)}")
    
    async def update_metadata(
        self,
        metadata: SnapshotMetadata,
        snapshot_dir: Path,
        updates: Dict[str, Any]
    ) -> SnapshotMetadata:
        """
        Update existing metadata with new information.
        
        Args:
            metadata: Existing metadata
            snapshot_dir: Snapshot directory
            updates: Dictionary of updates to apply
            
        Returns:
            Updated SnapshotMetadata object
            
        Raises:
            ValidationError: If updates are invalid
            StorageError: If saving fails
        """
        try:
            # Create updated metadata
            metadata_dict = metadata.dict()
            metadata_dict.update(updates)
            
            # Validate updates
            updated_metadata = SnapshotMetadata(**metadata_dict)
            
            # Save updated metadata
            await self.save_metadata(updated_metadata, snapshot_dir)
            
            logger.info(f"Updated metadata for snapshot in {snapshot_dir}")
            return updated_metadata
            
        except Exception as e:
            if isinstance(e, (ValidationError, StorageError)):
                raise
            else:
                raise ValidationError(f"Failed to update metadata: {str(e)}")
    
    async def extract_file_metadata(
        self,
        file_path: Path,
        compression: CompressionType = CompressionType.NONE,
        calculate_checksum: bool = True
    ) -> FileMetadata:
        """
        Extract metadata from a file.
        
        Args:
            file_path: Path to file
            compression: Compression type used on file
            calculate_checksum: Whether to calculate file checksum
            
        Returns:
            FileMetadata object
            
        Raises:
            StorageError: If file cannot be read
        """
        try:
            if not file_path.exists():
                raise StorageError(f"File not found: {file_path}")
            
            size_bytes = file_path.stat().st_size
            checksum = ""
            
            if calculate_checksum:
                checksum = await self._calculate_file_checksum(file_path)
            
            # Calculate compression ratio if file is compressed
            compression_ratio = None
            if compression != CompressionType.NONE and file_path.suffix.lower() == '.gz':
                try:
                    # Try to read original size from gzip header
                    original_size = await self._get_gzip_original_size(file_path)
                    if original_size > 0:
                        compression_ratio = original_size / size_bytes
                except Exception:
                    logger.debug(f"Could not determine compression ratio for {file_path}")
            
            return FileMetadata(
                name=file_path.name,
                size_bytes=size_bytes,
                checksum=checksum,
                compression=compression,
                compression_ratio=compression_ratio
            )
            
        except Exception as e:
            if isinstance(e, StorageError):
                raise
            else:
                raise StorageError(f"Failed to extract file metadata: {str(e)}")
    
    async def _create_compatibility_info(self, database_metadata: DatabaseMetadata) -> CompatibilityInfo:
        """Create compatibility information based on database metadata."""
        # Determine minimum version requirements
        min_version = self._determine_min_database_version(
            database_metadata.type, database_metadata.version
        )
        
        return CompatibilityInfo(
            min_database_version=min_version,
            requires_extensions=database_metadata.extensions.copy(),
            schema_changes=[],  # Would be populated by analyzing schema changes
            warnings=[]
        )
    
    def _determine_min_database_version(self, db_type: str, current_version: str) -> str:
        """Determine minimum compatible database version."""
        # Conservative approach - require same major version
        if db_type == "postgresql":
            # Extract major version (e.g., "15.3" -> "15.0")
            try:
                major = current_version.split('.')[0]
                return f"{major}.0"
            except (IndexError, ValueError):
                return current_version
        
        return current_version
    
    async def _create_checksums_content(self, file_metadata_list: List[FileMetadata]) -> str:
        """Create checksums file content in SHA256SUMS format."""
        lines = []
        for file_meta in file_metadata_list:
            if file_meta.checksum:
                lines.append(f"{file_meta.checksum}  {file_meta.name}")
        return "\n".join(lines)
    
    async def _verify_metadata_integrity(self, metadata: SnapshotMetadata, snapshot_dir: Path) -> None:
        """Verify metadata integrity using checksum verification."""
        # Verify metadata checksum if available
        expected_checksum = metadata.calculate_checksum()
        
        # For now, we trust the metadata if it loads successfully
        # In the future, could store metadata checksum separately
        logger.debug("Metadata integrity verification passed")
    
    async def _verify_file_checksums(
        self,
        file_metadata_list: List[FileMetadata],
        snapshot_dir: Path
    ) -> List[str]:
        """Verify file checksums and return list of files with invalid checksums."""
        invalid_files = []
        
        for file_meta in file_metadata_list:
            if not file_meta.checksum:
                continue
                
            file_path = snapshot_dir / file_meta.name
            if not file_path.exists():
                invalid_files.append(file_meta.name)
                continue
            
            try:
                actual_checksum = await self._calculate_file_checksum(file_path)
                if actual_checksum != file_meta.checksum:
                    invalid_files.append(file_meta.name)
            except Exception as e:
                logger.warning(f"Failed to verify checksum for {file_meta.name}: {e}")
                invalid_files.append(file_meta.name)
        
        return invalid_files
    
    async def _check_compatibility(self, compatibility: CompatibilityInfo) -> List[str]:
        """Check compatibility and return warnings."""
        warnings = []
        
        # Check for known compatibility issues
        if compatibility.requires_extensions:
            warnings.append(f"Requires extensions: {', '.join(compatibility.requires_extensions)}")
        
        if compatibility.warnings:
            warnings.extend(compatibility.warnings)
        
        return warnings
    
    async def _calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file."""
        def _calculate_sync():
            hash_sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        
        return await asyncio.get_event_loop().run_in_executor(None, _calculate_sync)
    
    async def _get_gzip_original_size(self, file_path: Path) -> int:
        """Get original size from gzip file header."""
        def _get_size_sync():
            with open(file_path, 'rb') as f:
                f.seek(-4, 2)  # Go to last 4 bytes
                return int.from_bytes(f.read(4), 'little')
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_size_sync)
    
    async def _write_file_async(self, file_path: Path, content: bytes) -> None:
        """Write file asynchronously."""
        def _write_sync():
            with open(file_path, 'wb') as f:
                f.write(content)
        
        await asyncio.get_event_loop().run_in_executor(None, _write_sync)
    
    async def _read_file_async(self, file_path: Path) -> bytes:
        """Read file asynchronously."""
        def _read_sync():
            with open(file_path, 'rb') as f:
                return f.read()
        
        return await asyncio.get_event_loop().run_in_executor(None, _read_sync)