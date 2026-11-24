"""One error type for the whole app. Every error body is {"error": ..., "code": ...}."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def body(self) -> dict:
        out = {"error": self.message, "code": self.code}
        if self.details:
            out["details"] = self.details
        return out
