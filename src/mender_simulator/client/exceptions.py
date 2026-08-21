"""Custom exceptions for Mender client."""


class AuthenticationError(Exception):
    """Raised when authentication token is invalid or expired (401)."""

    pass


class DeviceNotAcceptedError(Exception):
    """Raised when device auth is rejected because it is not yet
    accepted/preauthorized."""

    pass


class RequestTimeoutError(Exception):
    """Raised when a request to the Mender server times out or the connection fails."""

    def __init__(self, message: str, endpoint: str = ""):
        super().__init__(message)
        self.endpoint = endpoint


class RateLimitError(Exception):
    """Raised when the server returns 429 Too Many Requests."""

    def __init__(self, message: str, retry_after: int = 60, endpoint: str = ""):
        super().__init__(message)
        self.retry_after = retry_after
        self.endpoint = endpoint
