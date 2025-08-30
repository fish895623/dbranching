"""Tests for database models."""

import pytest
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError

from dbranching.database.models import (
    CompressionType,
    DatabaseInfo,
    ProgressCallback,
    RestoreOptions,
    RestoreResult,
    SnapshotFormat,
    SnapshotOptions,
    SnapshotResult,
    ValidationResult,
)


class TestSnapshotOptions:
    """Test SnapshotOptions model."""
    
    def test_default_values(self):
        """Test default values for SnapshotOptions."""
        options = SnapshotOptions()
        
        assert options.format == SnapshotFormat.CUSTOM
        assert options.compression == CompressionType.GZIP
        assert options.compression_level == 6
        assert options.parallel_jobs == 1
        assert options.include_schemas is None
        assert options.exclude_schemas is None
        assert options.include_tables is None
        assert options.exclude_tables is None
        assert options.data_only is False
        assert options.schema_only is False
        assert options.include_large_objects is True
        assert options.verbose is False
    
    def test_compression_level_validation(self):
        """Test compression level validation."""
        # Valid compression levels
        for level in range(10):
            options = SnapshotOptions(compression_level=level)
            assert options.compression_level == level
        
        # Invalid compression levels
        with pytest.raises(ValidationError):
            SnapshotOptions(compression_level=-1)
        
        with pytest.raises(ValidationError):
            SnapshotOptions(compression_level=10)
    
    def test_parallel_jobs_validation(self):
        """Test parallel jobs validation."""
        # Valid parallel jobs
        for jobs in range(1, 17):
            options = SnapshotOptions(parallel_jobs=jobs)
            assert options.parallel_jobs == jobs
        
        # Invalid parallel jobs
        with pytest.raises(ValidationError):
            SnapshotOptions(parallel_jobs=0)
        
        with pytest.raises(ValidationError):
            SnapshotOptions(parallel_jobs=17)
    
    def test_schema_filtering(self):
        """Test schema filtering options."""
        options = SnapshotOptions(
            include_schemas={"public", "test"},
            exclude_schemas={"temp"}
        )
        
        assert options.include_schemas == {"public", "test"}
        assert options.exclude_schemas == {"temp"}
    
    def test_table_filtering(self):
        """Test table filtering options."""
        options = SnapshotOptions(
            include_tables={"users", "orders"},
            exclude_tables={"logs"}
        )
        
        assert options.include_tables == {"users", "orders"}
        assert options.exclude_tables == {"logs"}


class TestRestoreOptions:
    """Test RestoreOptions model."""
    
    def test_default_values(self):
        """Test default values for RestoreOptions."""
        options = RestoreOptions()
        
        assert options.parallel_jobs == 1
        assert options.clean is False
        assert options.create is False
        assert options.if_exists == "fail"
        assert options.disable_triggers is False
        assert options.single_transaction is False
        assert options.no_owner is False
        assert options.no_privileges is False
        assert options.include_schemas is None
        assert options.exclude_schemas is None
        assert options.include_tables is None
        assert options.exclude_tables is None
        assert options.verbose is False
    
    def test_if_exists_validation(self):
        """Test if_exists validation."""
        valid_values = ["fail", "replace", "append"]
        
        for value in valid_values:
            options = RestoreOptions(if_exists=value)
            assert options.if_exists == value
        
        with pytest.raises(ValidationError):
            RestoreOptions(if_exists="invalid")


class TestSnapshotResult:
    """Test SnapshotResult model."""
    
    def test_successful_result(self):
        """Test successful snapshot result."""
        result = SnapshotResult(
            success=True,
            snapshot_path=Path("/tmp/test.dump"),
            size_bytes=1024 * 1024,
            duration_seconds=30.5,
            database_size_bytes=10 * 1024 * 1024,
            tables_included=5,
            schemas_included=1,
            compressed_size_bytes=512 * 1024,
            compression_ratio=2.0
        )
        
        assert result.success is True
        assert result.snapshot_path == Path("/tmp/test.dump")
        assert result.size_bytes == 1024 * 1024
        assert result.compressed_size_bytes == 512 * 1024
        assert result.compression_ratio == 2.0
        assert result.error_message is None
        assert result.warnings == []
    
    def test_failed_result(self):
        """Test failed snapshot result."""
        result = SnapshotResult(
            success=False,
            snapshot_path=Path("/tmp/test.dump"),
            size_bytes=0,
            duration_seconds=5.0,
            database_size_bytes=0,
            tables_included=0,
            schemas_included=0,
            error_message="Database connection failed"
        )
        
        assert result.success is False
        assert result.error_message == "Database connection failed"
    
    def test_str_representation(self):
        """Test string representation of results."""
        # Successful result
        success_result = SnapshotResult(
            success=True,
            snapshot_path=Path("/tmp/test.dump"),
            size_bytes=1024 * 1024,
            duration_seconds=30.5,
            database_size_bytes=10 * 1024 * 1024,
            tables_included=5,
            schemas_included=1
        )
        str_repr = str(success_result)
        assert "Snapshot successful" in str_repr
        assert "/tmp/test.dump" in str_repr
        assert "1.0 MB" in str_repr
        assert "30.5s" in str_repr
        
        # Failed result
        failed_result = SnapshotResult(
            success=False,
            snapshot_path=Path("/tmp/test.dump"),
            size_bytes=0,
            duration_seconds=5.0,
            database_size_bytes=0,
            tables_included=0,
            schemas_included=0,
            error_message="Connection failed"
        )
        str_repr = str(failed_result)
        assert "Snapshot failed" in str_repr
        assert "Connection failed" in str_repr


class TestRestoreResult:
    """Test RestoreResult model."""
    
    def test_successful_result(self):
        """Test successful restore result."""
        result = RestoreResult(
            success=True,
            snapshot_path=Path("/tmp/test.dump"),
            duration_seconds=45.2,
            tables_restored=10,
            schemas_restored=2,
            rows_processed=50000
        )
        
        assert result.success is True
        assert result.duration_seconds == 45.2
        assert result.tables_restored == 10
        assert result.rows_processed == 50000
        assert result.error_message is None
    
    def test_str_representation(self):
        """Test string representation of restore result."""
        result = RestoreResult(
            success=True,
            snapshot_path=Path("/tmp/test.dump"),
            duration_seconds=45.2,
            tables_restored=10,
            schemas_restored=2
        )
        str_repr = str(result)
        assert "Restore successful" in str_repr
        assert "10 tables" in str_repr
        assert "45.2s" in str_repr


class TestDatabaseInfo:
    """Test DatabaseInfo model."""
    
    def test_basic_info(self):
        """Test basic database info."""
        info = DatabaseInfo(
            name="testdb",
            version="13.8",
            size_bytes=100 * 1024 * 1024,
            table_count=25,
            schema_count=3,
            connection_count=5,
            encoding="UTF8",
            collation="en_US.utf8",
            timezone="UTC"
        )
        
        assert info.name == "testdb"
        assert info.version == "13.8"
        assert info.size_bytes == 100 * 1024 * 1024
        assert info.table_count == 25
        assert info.schema_count == 3
        assert info.encoding == "UTF8"
        assert info.collation == "en_US.utf8"
        assert info.timezone == "UTC"
        assert isinstance(info.collected_at, datetime)
    
    def test_with_metadata(self):
        """Test database info with additional metadata."""
        info = DatabaseInfo(
            name="testdb",
            version="13.8",
            size_bytes=100 * 1024 * 1024,
            table_count=25,
            schema_count=3,
            connection_count=5,
            encoding="UTF8",
            collation="en_US.utf8",
            timezone="UTC",
            schemas=["public", "test", "analytics"],
            extensions=["pg_stat_statements", "uuid-ossp"],
            settings={"max_connections": "100", "shared_buffers": "128MB"},
            metadata={"host": "localhost", "port": 5432}
        )
        
        assert info.schemas == ["public", "test", "analytics"]
        assert "pg_stat_statements" in info.extensions
        assert info.settings["max_connections"] == "100"
        assert info.metadata["host"] == "localhost"


class TestValidationResult:
    """Test ValidationResult model."""
    
    def test_valid_result(self):
        """Test valid snapshot validation result."""
        result = ValidationResult(
            valid=True,
            snapshot_path=Path("/tmp/test.dump"),
            format_valid=True,
            size_bytes=1024 * 1024,
            checksum="abc123",
            database_version="13.8",
            compatible=True,
            schema_count=2,
            table_count=10,
            estimated_restore_time=30.0
        )
        
        assert result.valid is True
        assert result.format_valid is True
        assert result.compatible is True
        assert result.checksum == "abc123"
        assert result.database_version == "13.8"
        assert result.estimated_restore_time == 30.0
        assert result.error_message is None
    
    def test_invalid_result(self):
        """Test invalid snapshot validation result."""
        result = ValidationResult(
            valid=False,
            snapshot_path=Path("/tmp/test.dump"),
            format_valid=False,
            size_bytes=0,
            compatible=False,
            error_message="File corrupted"
        )
        
        assert result.valid is False
        assert result.format_valid is False
        assert result.compatible is False
        assert result.error_message == "File corrupted"
    
    def test_str_representation(self):
        """Test string representation of validation result."""
        # Valid result
        valid_result = ValidationResult(
            valid=True,
            snapshot_path=Path("/tmp/test.dump"),
            format_valid=True,
            size_bytes=1024 * 1024,
            compatible=True
        )
        str_repr = str(valid_result)
        assert "Snapshot valid" in str_repr
        assert "1.0 MB" in str_repr
        
        # Invalid result
        invalid_result = ValidationResult(
            valid=False,
            snapshot_path=Path("/tmp/test.dump"),
            format_valid=False,
            size_bytes=0,
            compatible=False,
            error_message="Invalid format"
        )
        str_repr = str(invalid_result)
        assert "Snapshot invalid" in str_repr
        assert "Invalid format" in str_repr


class TestProgressCallback:
    """Test ProgressCallback class."""
    
    @pytest.mark.asyncio
    async def test_callback_initialization(self):
        """Test progress callback initialization."""
        callback = ProgressCallback()
        assert await callback.is_cancelled() is False
    
    @pytest.mark.asyncio
    async def test_cancel_operation(self):
        """Test cancelling operation."""
        callback = ProgressCallback()
        await callback.cancel()
        assert await callback.is_cancelled() is True
    
    @pytest.mark.asyncio
    async def test_update_method(self):
        """Test update method (default implementation)."""
        callback = ProgressCallback()
        # Should not raise any exceptions
        await callback.update(50, 100, "Testing", "test_stage")