"""Pydantic schemas for attendance and punch operations."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator


class AttendanceStatus(str, Enum):
    """Attendance daily status enumeration."""

    IN_PROGRESS = "IN_PROGRESS"
    PRESENT = "PRESENT"
    HALF_DAY = "HALF_DAY"
    ABSENT = "ABSENT"


def validate_timezone_aware_timestamp(v: Any) -> Optional[datetime]:
    """
    Validate and parse incoming timestamp.
    
    Supports:
    - ISO 8601 strings with timezone offset (e.g. '2026-10-12T09:00:00Z')
    - Epoch milliseconds integer/float (e.g. 1728637200000)
    - Epoch seconds integer/float (e.g. 1728637200)
    - Numeric string representations of epoch timestamps
    - Python datetime instances
    """
    if v is None:
        return None

    # Handle numeric epoch timestamp (int or float)
    if isinstance(v, (int, float)):
        ts = v / 1000.0 if v > 1e11 else float(v)
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception as exc:
            raise ValueError(f"Invalid epoch timestamp: {exc}") from exc

    if isinstance(v, str):
        # Check if string is purely numeric (epoch string)
        if v.isdigit():
            num = float(v)
            ts = num / 1000.0 if num > 1e11 else num
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception as exc:
                raise ValueError(f"Invalid epoch timestamp string: {exc}") from exc

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

    employee_id: str = Field(
        ...,
        validation_alias=AliasChoices("employee_id", "emp_code"),
        min_length=2,
        max_length=50,
        description="Employee identifier (e.g. EMP-1001 or emp_code)",
        examples=["EMP-1001"],
    )
    timestamp: Optional[Any] = Field(
        default=None,
        description="Optional punch timestamp (ISO 8601 or epoch ms). Defaults to current UTC time.",
        examples=["2026-10-14T09:00:00Z"],
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def check_timestamp(cls, v: Any) -> Optional[datetime]:
        return validate_timezone_aware_timestamp(v)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "timestamp": "2026-10-14T09:00:00Z",
            }
        }
    )


class PunchOutRequest(BaseModel):
    """Request payload for employee punch-out."""

    employee_id: str = Field(
        ...,
        validation_alias=AliasChoices("employee_id", "emp_code"),
        min_length=2,
        max_length=50,
        description="Employee identifier (e.g. EMP-1001 or emp_code)",
        examples=["EMP-1001"],
    )
    timestamp: Optional[Any] = Field(
        default=None,
        description="Optional punch timestamp (ISO 8601 or epoch ms). Defaults to current UTC time.",
        examples=["2026-10-14T17:30:00Z"],
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def check_timestamp(cls, v: Any) -> Optional[datetime]:
        return validate_timezone_aware_timestamp(v)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "timestamp": "2026-10-14T17:30:00Z",
            }
        }
    )


class PunchSessionResponse(BaseModel):
    """Individual punch-in / punch-out interval representation."""

    session_id: str = Field(..., examples=["b3e05a8d-192a-4db3-a9d0-c6e00180fbe8"])
    punch_in: datetime = Field(..., examples=["2026-10-14T09:00:00Z"])
    punch_out: Optional[datetime] = Field(None, examples=["2026-10-14T17:30:00Z"])
    duration_minutes: Optional[int] = Field(None, examples=[510])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "session_id": "b3e05a8d-192a-4db3-a9d0-c6e00180fbe8",
                "punch_in": "2026-10-14T09:00:00Z",
                "punch_out": "2026-10-14T17:30:00Z",
                "duration_minutes": 510,
            }
        }
    )


class AttendanceRecordResponse(BaseModel):
    """Full attendance record response schema."""

    id: str = Field(..., examples=["60d5ec49f1b2c82b8c8d2891"])
    employee_id: str = Field(..., examples=["EMP-1001"])
    department: str = Field(..., examples=["Engineering"])
    date: str = Field(..., examples=["2026-10-14"])
    punches: List[PunchSessionResponse]
    has_active_session: bool = Field(False, examples=[False])
    total_work_minutes: int = Field(..., examples=[510])
    total_work_hours: float = Field(..., examples=[8.5])
    status: AttendanceStatus = Field(..., examples=["PRESENT"])
    is_corrected: bool = Field(False, examples=[False])
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def emp_code(self) -> str:
        """Alias for employee_id to satisfy contracts expecting emp_code."""
        return self.employee_id

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "60d5ec49f1b2c82b8c8d2891",
                "employee_id": "EMP-1001",
                "emp_code": "EMP-1001",
                "department": "Engineering",
                "date": "2026-10-14",
                "punches": [
                    {
                        "session_id": "b3e05a8d-192a-4db3-a9d0-c6e00180fbe8",
                        "punch_in": "2026-10-14T09:00:00Z",
                        "punch_out": "2026-10-14T17:30:00Z",
                        "duration_minutes": 510,
                    }
                ],
                "has_active_session": False,
                "total_work_minutes": 510,
                "total_work_hours": 8.5,
                "status": "PRESENT",
                "is_corrected": False,
                "created_at": "2026-10-14T09:00:00Z",
                "updated_at": "2026-10-14T17:30:00Z",
            }
        }
    )


class RegularizeInterval(BaseModel):
    """Punch interval for regularizing attendance."""

    punch_in: Any = Field(..., description="Punch-in timestamp (ISO 8601 or epoch ms)", examples=["2026-10-13T09:00:00Z"])
    punch_out: Any = Field(..., description="Punch-out timestamp (ISO 8601 or epoch ms)", examples=["2026-10-13T17:30:00Z"])

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def check_ts(cls, v: Any) -> datetime:
        res = validate_timezone_aware_timestamp(v)
        if res is None:
            raise ValueError("Punch timestamp is required.")
        return res

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "punch_in": "2026-10-13T09:00:00Z",
                "punch_out": "2026-10-13T17:30:00Z",
            }
        }
    )


class RegularizeAttendanceRequest(BaseModel):
    """Request payload for direct attendance regularization."""

    employee_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("employee_id", "emp_code"),
        description="Employee identifier (if provided in body)",
    )
    date: Optional[str] = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Target attendance calendar date (if provided in body)",
    )
    punch_in: Optional[Any] = Field(default=None, description="Single session check-in timestamp")
    punch_out: Optional[Any] = Field(default=None, description="Single session check-out timestamp")
    punches: Optional[List[RegularizeInterval]] = Field(
        default=None,
        description="Multiple punch sessions to regularize (if applicable)",
    )
    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Reason justifying the regularization",
    )

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def check_optional_ts(cls, v: Any) -> Optional[datetime]:
        return validate_timezone_aware_timestamp(v)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "emp_code": "EMP-1001",
                "date": "2026-10-13",
                "punch_in": "2026-10-13T09:00:00Z",
                "punch_out": "2026-10-13T17:30:00Z",
                "reason": "Biometric card reader failure at entrance turnstile.",
            }
        }
    )


class AttendanceQueryFilter(BaseModel):
    """Query parameters for fetching attendance records."""

    date: Optional[str] = Field(default=None, description="Exact date in YYYY-MM-DD format")
    start_date: Optional[str] = Field(default=None, description="Start date in YYYY-MM-DD format")
    end_date: Optional[str] = Field(default=None, description="End date in YYYY-MM-DD format")
