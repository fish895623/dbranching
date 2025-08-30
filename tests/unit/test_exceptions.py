"""Tests for dbranching exceptions."""


from dbranching.exceptions import (
    ConfigurationError,
    DatabaseConnectionError,
    DBranchingError,
    SnapshotError,
    StorageError,
    ValidationError,
)


class TestDBranchingError:
    """Test base exception class."""

    def test_basic_exception(self) -> None:
        """Test basic exception creation."""
        error = DBranchingError("test message")
        assert str(error) == "test message"
        assert error.message == "test message"
        assert error.exit_code == 1

    def test_custom_exit_code(self) -> None:
        """Test exception with custom exit code."""
        error = DBranchingError("test message", exit_code=42)
        assert error.exit_code == 42


class TestConfigurationError:
    """Test configuration error class."""

    def test_basic_config_error(self) -> None:
        """Test basic configuration error."""
        error = ConfigurationError("invalid setting")
        assert "invalid setting" in str(error)
        assert error.exit_code == 2
        assert error.config_path is None

    def test_config_error_with_path(self) -> None:
        """Test configuration error with config path."""
        error = ConfigurationError(
            "invalid setting", config_path="/path/to/config.yaml"
        )
        assert "/path/to/config.yaml" in str(error)
        assert "invalid setting" in str(error)
        assert error.config_path == "/path/to/config.yaml"


class TestDatabaseConnectionError:
    """Test database connection error class."""

    def test_basic_db_error(self) -> None:
        """Test basic database connection error."""
        error = DatabaseConnectionError("connection failed")
        assert "connection failed" in str(error)
        assert error.exit_code == 3
        assert error.database_url is None

    def test_db_error_with_url(self) -> None:
        """Test database error with connection URL."""
        error = DatabaseConnectionError(
            "connection failed", "postgresql://localhost:5432/test"
        )
        assert "postgresql://localhost:5432/test" in str(error)
        assert "connection failed" in str(error)
        assert error.database_url == "postgresql://localhost:5432/test"


class TestSnapshotError:
    """Test snapshot error class."""

    def test_basic_snapshot_error(self) -> None:
        """Test basic snapshot error."""
        error = SnapshotError("snapshot failed")
        assert "snapshot failed" in str(error)
        assert error.exit_code == 4
        assert error.snapshot_name is None

    def test_snapshot_error_with_name(self) -> None:
        """Test snapshot error with snapshot name."""
        error = SnapshotError("not found", snapshot_name="dev-feature")
        assert "dev-feature" in str(error)
        assert "not found" in str(error)
        assert error.snapshot_name == "dev-feature"


class TestValidationError:
    """Test validation error class."""

    def test_basic_validation_error(self) -> None:
        """Test basic validation error."""
        error = ValidationError("invalid value")
        assert "invalid value" in str(error)
        assert error.exit_code == 5
        assert error.field is None

    def test_validation_error_with_field(self) -> None:
        """Test validation error with field name."""
        error = ValidationError("must be positive", field="port")
        assert "port" in str(error)
        assert "must be positive" in str(error)
        assert error.field == "port"


class TestStorageError:
    """Test storage error class."""

    def test_basic_storage_error(self) -> None:
        """Test basic storage error."""
        error = StorageError("disk full")
        assert "disk full" in str(error)
        assert error.exit_code == 6
        assert error.path is None

    def test_storage_error_with_path(self) -> None:
        """Test storage error with path."""
        error = StorageError("permission denied", path="/var/snapshots")
        assert "/var/snapshots" in str(error)
        assert "permission denied" in str(error)
        assert error.path == "/var/snapshots"
