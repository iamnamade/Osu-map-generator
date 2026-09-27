from __future__ import annotations


class LocalApiError(Exception):
    """Readable API-facing error."""

    status_code = 400
    error_code = "BAD_REQUEST"

    def __init__(self, message: str, *, detail=None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = message if detail is None else detail

    def to_response_content(self) -> dict[str, object]:
        return {"detail": self.detail}


class LocalApiValidationError(LocalApiError):
    status_code = 422
    error_code = "INVALID_REQUEST"


class LocalApiMetadataValidationError(LocalApiValidationError):
    error_code = "INVALID_METADATA"

    def __init__(self, message: str, *, fields: dict[str, str]) -> None:
        super().__init__(
            message,
            detail={
                "code": self.error_code,
                "message": message,
                "fields": fields,
            },
        )
        self.fields = fields


class LocalApiNotFoundError(LocalApiError):
    status_code = 404
    error_code = "NOT_FOUND"


class LocalApiConflictError(LocalApiError):
    status_code = 409
    error_code = "CONFLICT"


class LocalApiPayloadTooLargeError(LocalApiError):
    status_code = 413
    error_code = "PAYLOAD_TOO_LARGE"


class LocalApiUnsupportedMediaTypeError(LocalApiError):
    status_code = 415
    error_code = "UNSUPPORTED_MEDIA_TYPE"


class LocalApiCancellationRequested(LocalApiError):
    status_code = 409
    error_code = "CANCELLED"
