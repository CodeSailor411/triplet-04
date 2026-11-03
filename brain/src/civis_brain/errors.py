class BrainError(Exception):
    """Safe public error code. Never put raw partner exceptions or secrets in messages."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
