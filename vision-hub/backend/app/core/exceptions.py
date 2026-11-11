"""Application exceptions and their HTTP mapping."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str, *, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.extra = extra or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class UnsupportedFormatError(AppError):
    status_code = 415
    code = "unsupported_format"


class CorruptedVideoError(AppError):
    status_code = 422
    code = "corrupted_video"


class EmptyVideoError(AppError):
    status_code = 422
    code = "empty_video"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class InsufficientDiskSpaceError(AppError):
    status_code = 507
    code = "insufficient_disk_space"


class DuplicateVideoError(AppError):
    status_code = 409
    code = "duplicate_video"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class VideoTooLongError(AppError):
    status_code = 422
    code = "video_too_long"


class ModelWeightsMissingError(AppError):
    status_code = 500
    code = "model_weights_missing"


class ModelLoadError(AppError):
    status_code = 500
    code = "model_load_error"


class PipelineError(AppError):
    """The selected models cannot be combined into a valid pipeline."""

    status_code = 422
    code = "invalid_pipeline"


class ProcessingError(AppError):
    status_code = 500
    code = "processing_error"


class ProcessingCancelled(Exception):
    """Raised inside the processing loop when the user cancels the job."""


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code, **exc.extra},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Check the backend logs.", "code": "internal_error"},
        )
