"""Custom domain exceptions and structured error responses."""

from typing import Any, Dict, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse

# Handle Starlette 422 status cleanly
HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "INTERNAL_SERVER_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}


class DatabaseConnectionError(AppException):
    """Raised when the database connection cannot be established or verified."""

    def __init__(self, message: str = "Unable to connect to database. Please check connectivity."):
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="DATABASE_UNAVAILABLE",
        )


class EmployeeNotFoundError(AppException):
    """Raised when an employee identifier does not exist in the system."""

    def __init__(self, employee_id: str):
        super().__init__(
            message=f"Employee '{employee_id}' was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="EMPLOYEE_NOT_FOUND",
            details={"employee_id": employee_id},
        )


class AttendanceRecordNotFoundError(AppException):
    """Raised when an attendance record is not found."""

    def __init__(self, message: str = "Attendance record not found."):
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="ATTENDANCE_NOT_FOUND",
        )


class ActiveSessionExistsError(AppException):
    """Raised when an employee attempts to punch in while already having an active session."""

    def __init__(self, message: str = "Employee already has an active punch session. Punch out before punching in again."):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="ACTIVE_SESSION_EXISTS",
        )


class NoActiveSessionError(AppException):
    """Raised when an employee attempts to punch out without an active punch-in session."""

    def __init__(self, message: str = "No active punch session found for employee. Must punch in first."):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="NO_ACTIVE_SESSION",
        )


class InvalidTimestampError(AppException):
    """Raised when provided timestamps violate chronological or future constraints."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=HTTP_422,
            code="INVALID_TIMESTAMP",
        )


class BusinessRuleViolationError(AppException):
    """Raised when an operation violates attendance or correction business rules."""

    def __init__(self, message: str, code: str = "BUSINESS_RULE_VIOLATION"):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code,
        )


class CorrectionNotFoundError(AppException):
    """Raised when a correction request ID cannot be found."""

    def __init__(self, correction_id: str):
        super().__init__(
            message=f"Correction request '{correction_id}' was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="CORRECTION_NOT_FOUND",
            details={"correction_id": correction_id},
        )


class DuplicateCorrectionRequestError(AppException):
    """Raised when a pending correction request already exists for employee and date."""

    def __init__(self, employee_id: str, date: str):
        super().__init__(
            message=f"A pending correction request already exists for employee '{employee_id}' on date '{date}'.",
            status_code=status.HTTP_409_CONFLICT,
            code="DUPLICATE_PENDING_CORRECTION",
            details={"employee_id": employee_id, "date": date},
        )


class CorrectionAlreadyResolvedError(AppException):
    """Raised when trying to modify a correction request that has already been approved or rejected."""

    def __init__(self, status_val: str):
        super().__init__(
            message=f"Correction request has already been finalized ({status_val}) and cannot be modified.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="CORRECTION_ALREADY_RESOLVED",
            details={"current_status": status_val},
        )


class UnauthorizedReviewerError(AppException):
    """Raised when reviewer lacks role privileges or attempts unauthorized review action."""

    def __init__(self, message: str = "Only authorized managers or administrators can review corrections."):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="UNAUTHORIZED_REVIEWER",
        )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom application exceptions cleanly."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions cleanly without exposing sensitive system traces."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected server error occurred. Please contact system administrator.",
        },
    )
