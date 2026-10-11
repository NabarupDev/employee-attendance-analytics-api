"""Pydantic validation schemas for attendance correction requests and audit trails."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.attendance import validate_timezone_aware_timestamp


class CorrectionStatus(str, Enum):
    """Lifecycle status of an attendance correction request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProposedPunchInterval(BaseModel):
    """Proposed punch session interval."""

    punch_in: datetime = Field(..., description="Proposed check-in timestamp (UTC)")
    punch_out: datetime = Field(..., description="Proposed check-out timestamp (UTC)")

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def check_tz(cls, v: Any) -> datetime:
        return validate_timezone_aware_timestamp(v)

    @model_validator(mode="after")
    def validate_interval(self) -> "ProposedPunchInterval":
        if self.punch_out <= self.punch_in:
            raise ValueError("Proposed punch_out must be strictly after punch_in.")
        return self


class CorrectionCreateRequest(BaseModel):
    """Request payload to submit an attendance correction request."""

    employee_id: str = Field(..., min_length=2, max_length=50, description="Employee identifier")
    attendance_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Target attendance calendar date (YYYY-MM-DD)",
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


class CorrectionStatusUpdateRequest(BaseModel):
    """Request payload to approve or reject a correction request."""

    status: CorrectionStatus = Field(
        ...,
        description="New status for the correction request (must be APPROVED or REJECTED)",
    )
    remarks: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional reviewer remarks explaining the approval or rejection",
    )

    @field_validator("status")
    @classmethod
    def validate_target_status(cls, v: CorrectionStatus) -> CorrectionStatus:
        if v not in (CorrectionStatus.APPROVED, CorrectionStatus.REJECTED):
            raise ValueError("Target status must be either 'APPROVED' or 'REJECTED'.")
        return v


class CorrectionResponse(BaseModel):
    """Public representation of an attendance correction request."""

    id: str
    employee_id: str
    attendance_date: str
    original_record_snapshot: Optional[Dict[str, Any]] = None
    proposed_punches: List[ProposedPunchInterval]
    reason: str
    status: CorrectionStatus
    requested_by: str
    reviewed_by: Optional[str] = None
    review_remarks: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


class AuditEntryResponse(BaseModel):
    """Audit entry recording historical attendance changes."""

    correction_id: str
    applied_at: datetime
    reviewed_by: str
    reason: str
    previous_punches: List[Dict[str, Any]]
    new_punches: List[Dict[str, Any]]
    previous_total_minutes: int
    new_total_minutes: int
    previous_status: str
    new_status: str
