"""Pydantic validation schemas for attendance correction requests and audit trails."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.schemas.attendance import validate_timezone_aware_timestamp


class CorrectionStatus(str, Enum):
    """Lifecycle status of an attendance correction request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProposedPunchInterval(BaseModel):
    """Proposed punch session interval."""

    punch_in: datetime = Field(..., description="Proposed check-in timestamp (UTC)", examples=["2026-10-13T09:00:00Z"])
    punch_out: datetime = Field(..., description="Proposed check-out timestamp (UTC)", examples=["2026-10-13T17:30:00Z"])

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def check_tz(cls, v: Any) -> datetime:
        return validate_timezone_aware_timestamp(v)

    @model_validator(mode="after")
    def validate_interval(self) -> "ProposedPunchInterval":
        if self.punch_out <= self.punch_in:
            raise ValueError("Proposed punch_out must be strictly after punch_in.")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "punch_in": "2026-10-13T09:00:00Z",
                "punch_out": "2026-10-13T17:30:00Z",
            }
        }
    )


class CorrectionCreateRequest(BaseModel):
    """Request payload to submit an attendance correction request."""

    employee_id: str = Field(
        ...,
        validation_alias=AliasChoices("employee_id", "emp_code"),
        min_length=2,
        max_length=50,
        description="Employee identifier (e.g. EMP-1001 or emp_code)",
        examples=["EMP-1001"],
    )
    attendance_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Target attendance calendar date (YYYY-MM-DD)",
        examples=["2026-10-13"],
    )
    proposed_punches: List[ProposedPunchInterval] = Field(
        ...,
        min_length=1,
        description="List of proposed punch sessions",
    )
    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Mandatory reason justifying the correction (minimum 10 characters)",
        examples=["Biometric badge scanner was down during morning entry."],
    )

    @model_validator(mode="after")
    def validate_non_overlapping_and_matching_dates(self) -> "CorrectionCreateRequest":
        # Validate that proposed punches match the target attendance calendar date
        for p in self.proposed_punches:
            punch_in_date = p.punch_in.strftime("%Y-%m-%d")
            if punch_in_date != self.attendance_date:
                raise ValueError(
                    f"Proposed punch timestamp date ({punch_in_date}) does not match "
                    f"target attendance date ({self.attendance_date})."
                )

        # Sort intervals by punch_in and verify non-overlapping
        sorted_punches = sorted(self.proposed_punches, key=lambda x: x.punch_in)
        for i in range(len(sorted_punches) - 1):
            if sorted_punches[i].punch_out > sorted_punches[i + 1].punch_in:
                raise ValueError("Proposed punch intervals cannot overlap.")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "attendance_date": "2026-10-13",
                "proposed_punches": [
                    {
                        "punch_in": "2026-10-13T09:00:00Z",
                        "punch_out": "2026-10-13T17:30:00Z",
                    }
                ],
                "reason": "Biometric badge scanner was down during morning entry.",
            }
        }
    )


class CorrectionStatusUpdateRequest(BaseModel):
    """Request payload to approve or reject a correction request."""

    status: CorrectionStatus = Field(
        ...,
        description="New status for the correction request (must be APPROVED or REJECTED)",
        examples=["APPROVED"],
    )
    remarks: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional reviewer remarks explaining the approval or rejection",
        examples=["Verified against manual security register."],
    )

    @field_validator("status")
    @classmethod
    def validate_target_status(cls, v: CorrectionStatus) -> CorrectionStatus:
        if v not in (CorrectionStatus.APPROVED, CorrectionStatus.REJECTED):
            raise ValueError("Target status must be either 'APPROVED' or 'REJECTED'.")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "APPROVED",
                "remarks": "Verified against manual security register.",
            }
        }
    )


class CorrectionResponse(BaseModel):
    """Public representation of an attendance correction request."""

    id: str = Field(..., examples=["6accc924376fb1b94b29bb88"])
    employee_id: str = Field(..., examples=["EMP-1001"])
    attendance_date: str = Field(..., examples=["2026-10-13"])
    original_record_snapshot: Optional[Dict[str, Any]] = None
    proposed_punches: List[ProposedPunchInterval]
    reason: str = Field(..., examples=["Biometric badge scanner was down during morning entry."])
    status: CorrectionStatus = Field(..., examples=["PENDING"])
    requested_by: str = Field(..., examples=["EMP-1001"])
    reviewed_by: Optional[str] = Field(None, examples=["MGR-5001"])
    review_remarks: Optional[str] = Field(None, examples=["Verified against manual security register."])
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    @computed_field
    @property
    def emp_code(self) -> str:
        """Alias for employee_id to satisfy contracts expecting emp_code."""
        return self.employee_id

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "6accc924376fb1b94b29bb88",
                "employee_id": "EMP-1001",
                "emp_code": "EMP-1001",
                "attendance_date": "2026-10-13",
                "proposed_punches": [
                    {
                        "punch_in": "2026-10-13T09:00:00Z",
                        "punch_out": "2026-10-13T17:30:00Z",
                    }
                ],
                "reason": "Biometric badge scanner was down during morning entry.",
                "status": "PENDING",
                "requested_by": "EMP-1001",
                "reviewed_by": None,
                "review_remarks": None,
                "created_at": "2026-10-13T18:00:00Z",
                "reviewed_at": None,
            }
        }
    )


class AuditEntryResponse(BaseModel):
    """Audit entry recording historical attendance changes."""

    correction_id: str = Field(..., examples=["6accc924376fb1b94b29bb88"])
    applied_at: datetime
    reviewed_by: str = Field(..., examples=["MGR-5001"])
    reason: str = Field(..., examples=["Biometric badge scanner was down during morning entry."])
    previous_punches: List[Dict[str, Any]]
    new_punches: List[Dict[str, Any]]
    previous_total_minutes: int = Field(..., examples=[240])
    new_total_minutes: int = Field(..., examples=[510])
    previous_status: str = Field(..., examples=["HALF_DAY"])
    new_status: str = Field(..., examples=["PRESENT"])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "correction_id": "6accc924376fb1b94b29bb88",
                "applied_at": "2026-10-13T18:30:00Z",
                "reviewed_by": "MGR-5001",
                "reason": "Biometric badge scanner was down during morning entry.",
                "previous_punches": [],
                "new_punches": [
                    {
                        "session_id": "b3e05a8d-192a-4db3-a9d0-c6e00180fbe8",
                        "punch_in": "2026-10-13T09:00:00Z",
                        "punch_out": "2026-10-13T17:30:00Z",
                        "duration_minutes": 510,
                    }
                ],
                "previous_total_minutes": 240,
                "new_total_minutes": 510,
                "previous_status": "HALF_DAY",
                "new_status": "PRESENT",
            }
        }
    )
