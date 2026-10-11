"""Pydantic schemas for attendance and punch operations."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class AttendanceStatus(str, Enum):
    """Attendance daily status enumeration."""

    IN_PROGRESS = "IN_PROGRESS"
    PRESENT = "PRESENT"
    HALF_DAY = "HALF_DAY"
    ABSENT = "ABSENT"


def validate_timezone_aware_timestamp(v: Any) -> Optional[datetime]:
    """
    Validate that timestamp includes explicit timezone information
    and is not unreasonably in the future.
    """
    if v is None:
        return None

    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception as exc:
            raise ValueError(f"Invalid ISO 8601 datetime format: {exc}") from exc
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError(
                "Timestamp must include explicit timezone information (e.g., ISO 8601 UTC with 'Z' or '+00:00'). "
                "Naive datetime strings are not permitted."
            )
        v = dt

    if isinstance(v, datetime):
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            # When retrieved from BSON/MongoDB, datetime objects are naive UTC
            v = v.replace(tzinfo=timezone.utc)

        utc_val = v.astimezone(timezone.utc)
        now_utc = datetime.now(timezone.utc)

        # Allow up to 60 seconds clock skew
        if (utc_val - now_utc).total_seconds() > 60:
            raise ValueError("Timestamp cannot be set in the future.")

        return utc_val

    return v


class PunchInRequest(BaseModel):
    """Request payload for employee punch-in."""

    employee_id: str = Field(..., min_length=2, max_length=50, description="Employee identifier (e.g. EMP-1001)")
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional punch timestamp. Must be timezone-aware (e.g. 2026-10-12T09:00:00Z). Defaults to current UTC time.",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def check_timestamp(cls, v: Any) -> Optional[datetime]:
        return validate_timezone_aware_timestamp(v)


class PunchOutRequest(BaseModel):
    """Request payload for employee punch-out."""

    employee_id: str = Field(..., min_length=2, max_length=50, description="Employee identifier (e.g. EMP-1001)")
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Optional punch timestamp. Must be timezone-aware. Defaults to current UTC time.",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def check_timestamp(cls, v: Any) -> Optional[datetime]:
        return validate_timezone_aware_timestamp(v)


class PunchSessionResponse(BaseModel):
    """Individual punch-in / punch-out interval representation."""

    session_id: str
    punch_in: datetime
    punch_out: Optional[datetime] = None
    duration_minutes: Optional[int] = None


class AttendanceRecordResponse(BaseModel):
    """Full attendance record response schema."""

    id: str
    employee_id: str
    department: str
    date: str
    punches: List[PunchSessionResponse]
    has_active_session: bool
    total_work_minutes: int
    total_work_hours: float
    status: AttendanceStatus
    is_corrected: bool
    created_at: datetime
    updated_at: datetime


class AttendanceQueryFilter(BaseModel):
    """Query parameters for fetching attendance records."""

    date: Optional[str] = Field(default=None, description="Exact date in YYYY-MM-DD format")
    start_date: Optional[str] = Field(default=None, description="Start date in YYYY-MM-DD format")
    end_date: Optional[str] = Field(default=None, description="End date in YYYY-MM-DD format")
