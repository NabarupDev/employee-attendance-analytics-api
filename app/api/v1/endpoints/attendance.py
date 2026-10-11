"""API endpoints for employee attendance operations."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.client import get_database
from app.schemas.attendance import (
    AttendanceRecordResponse,
    PunchInRequest,
    PunchOutRequest,
)
from app.schemas.common import ApiResponse
from app.schemas.correction import AuditEntryResponse
from app.services.attendance_service import AttendanceService
from app.services.correction_service import CorrectionService

router = APIRouter(prefix="/attendance", tags=["Attendance"])


@router.post(
    "/punch-in",
    response_model=ApiResponse[AttendanceRecordResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Record Punch-In",
    description="Record an employee check-in. Rejects if an active session is already open.",
)
async def punch_in(
    request: PunchInRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[AttendanceRecordResponse]:
    """Process employee punch-in event."""
    service = AttendanceService(db)
    record = await service.punch_in(
        employee_id=request.employee_id,
        timestamp=request.timestamp,
    )
    return ApiResponse(
        message="Punch-in recorded successfully.",
        data=record,
    )


@router.post(
    "/punch-out",
    response_model=ApiResponse[AttendanceRecordResponse],
    status_code=status.HTTP_200_OK,
    summary="Record Punch-Out",
    description="Record an employee check-out, calculate session duration, and update daily status.",
)
async def punch_out(
    request: PunchOutRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[AttendanceRecordResponse]:
    """Process employee punch-out event."""
    service = AttendanceService(db)
    record = await service.punch_out(
        employee_id=request.employee_id,
        timestamp=request.timestamp,
    )
    return ApiResponse(
        message="Punch-out recorded successfully.",
        data=record,
    )


@router.get(
    "/{employee_id}",
    response_model=ApiResponse[List[AttendanceRecordResponse]],
    summary="Get Attendance History",
    description="Retrieve attendance logs for an employee with optional date filtering.",
)
async def get_attendance_history(
    employee_id: str,
    date: Optional[str] = Query(None, description="Filter for specific date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    start_date: Optional[str] = Query(None, description="Range start date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, description="Range end date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[AttendanceRecordResponse]]:
    """Retrieve attendance history for employee."""
    service = AttendanceService(db)
    records = await service.get_attendance(
        employee_id=employee_id,
        date=date,
        start_date=start_date,
        end_date=end_date,
    )
    return ApiResponse(
        message=f"Found {len(records)} attendance record(s).",
        data=records,
    )


@router.get(
    "/{employee_id}/daily/{date}",
    response_model=ApiResponse[AttendanceRecordResponse],
    summary="Get Daily Attendance Record",
    description="Retrieve a specific daily attendance record for an employee.",
)
async def get_daily_record(
    employee_id: str,
    date: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[AttendanceRecordResponse]:
    """Retrieve daily attendance record for employee on date."""
    service = AttendanceService(db)
    record = await service.get_daily_record(employee_id=employee_id, date=date)
    return ApiResponse(data=record)


@router.get(
    "/{employee_id}/audit-trail",
    response_model=ApiResponse[List[AuditEntryResponse]],
    summary="Get Attendance Audit Trail",
    description="Retrieve comprehensive historical change audit log for corrected attendance records.",
)
async def get_attendance_audit_trail(
    employee_id: str,
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[AuditEntryResponse]]:
    """Retrieve audit history entries for corrected employee records."""
    correction_service = CorrectionService(db)
    entries = await correction_service.get_audit_trail(employee_id=employee_id, date=date)
    return ApiResponse(
        message=f"Found {len(entries)} audit trail record(s).",
        data=entries,
    )
