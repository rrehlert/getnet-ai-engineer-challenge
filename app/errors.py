"""The API's error shape, shared by `app.main` and the Operator routes."""

from fastapi.responses import JSONResponse


def error_response(status: int, code: str, message: str, trace_id: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}, "trace_id": trace_id},
        headers=headers,
    )


class AuthError(Exception):
    """401/403, rendered by the app's handler as `error_response` (401 adds `WWW-Authenticate`)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
