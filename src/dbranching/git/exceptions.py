"""Git integration specific exceptions."""

from ..exceptions import DBranchingError


class GitIntegrationError(DBranchingError):
    """Base exception for Git integration errors."""

    def __init__(self, message: str, git_operation: str = None) -> None:
        self.git_operation = git_operation
        if git_operation:
            message = f"Git {git_operation} error: {message}"
        super().__init__(message, exit_code=10)


class HookInstallationError(GitIntegrationError):
    """Raised when Git hook installation fails."""

    def __init__(self, message: str, hook_type: str = None) -> None:
        self.hook_type = hook_type
        super().__init__(message, f"hook installation ({hook_type})" if hook_type else "hook installation")


class HookExecutionError(GitIntegrationError):
    """Raised when Git hook execution fails but shouldn't block Git operations."""

    def __init__(self, message: str, hook_type: str = None) -> None:
        self.hook_type = hook_type
        super().__init__(message, f"hook execution ({hook_type})" if hook_type else "hook execution")
        # Hook execution errors should not block Git operations
        self.exit_code = 0


class BranchDetectionError(GitIntegrationError):
    """Raised when branch detection fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "branch detection")


class GitRepositoryError(GitIntegrationError):
    """Raised when Git repository access fails."""

    def __init__(self, message: str, repo_path: str = None) -> None:
        self.repo_path = repo_path
        if repo_path:
            message = f"Git repository error ({repo_path}): {message}"
        super().__init__(message, "repository access")