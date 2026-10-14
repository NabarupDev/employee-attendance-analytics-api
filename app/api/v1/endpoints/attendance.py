"""API endpoints for employee attendance operations."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Header, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.client import get_database
from app.schemas.attendance import (
    AttendanceRecordResponse,
    PunchInRequest,
    PunchOutRequest,
    RegularizeAttendanceRequest,
)
from app.schemas.common import ApiResponse
from app.schemas.correction import AuditEntryResponse
from app.services.attendance_service import AttendanceService
from app.services.correction_service import CorrectionService

router = APIRouter(prefix="/attendance", tags=["Attendance"])


@router.get(
    "",
    response_model=ApiResponse[List[AttendanceRecordResponse]],
    summary="List Attendance Records",
    description="Retrieve attendance logs across employees with optional filters (employee_id, emp_code, department, date range).",
)
async def list_all_attendance(
    employee_id: Optional[str] = Query(None, description="Filter by employee_id or emp_code"),
    emp_code: Optional[str] = Query(None, description="Alias filter for employee code"),
    department: Optional[str] = Query(None, description="Filter by department"),
    date: Optional[str] = Query(None, description="Exact date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    start_date: Optional[str] = Query(None, description="Range start date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, description="Range end date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    status: Optional[str] = Query(None, description="Filter by attendance status"),
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[AttendanceRecordResponse]]:
    """List attendance records matching query criteria."""
    service = AttendanceService(db)
    target_emp = employee_id or emp_code
    records = await service.get_all_attendance(
        employee_id=target_emp,
        department=department,
        date=date,
        start_date=start_date,
        end_date=end_date,
        status=status,
        limit=limit,
        skip=skip,
    )
    return ApiResponse(
        message=f"Found {len(records)} attendance record(s).",
        data=records,
    )


@router.patch(
    "/records/{employee_id}/{date}/regularize",
    response_model=ApiResponse[AttendanceRecordResponse],
    summary="Regularize Attendance Record",
    description="Directly regularize an employee's attendance record for a date (works with employee_id or emp_code).",
)
@router.post(
    "/records/{employee_id}/{date}/regularize",
    response_model=ApiResponse[AttendanceRecordResponse],
    include_in_schema=False,
)
async def regularize_attendance_record(
    employee_id: str,
    date: str,
    request: RegularizeAttendanceRequest,
    x_actor_id: Optional[str] = Header(None, alias="X-Actor-ID", description="Authorizing manager/admin ID"),
    x_role: Optional[str] = Header(None, alias="X-Role", description="Authorizing role"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[AttendanceRecordResponse]:
    """Process direct attendance regularization."""
    service = AttendanceService(db)
    record = await service.regularize_attendance(
        employee_id=employee_id,
        date=date,
        request=request,
        actor_id=x_actor_id,
        role=x_role,
    )
    return ApiResponse(
        message="Attendance regularized successfully.",
        data=record,
    )


@router.post(
    "/regularize",
    response_model=ApiResponse[AttendanceRecordResponse],
    summary="Regularize Attendance Record Direct",
    include_in_schema=False,
)
@router.patch(
    "/regularize",
    response_model=ApiResponse[AttendanceRecordResponse],
    include_in_schema=False,
)
async def regularize_attendance_direct(
    request: RegularizeAttendanceRequest,
    x_actor_id: Optional[str] = Header(None, alias="X-Actor-ID", description="Authorizing manager/admin ID"),
    x_role: Optional[str] = Header(None, alias="X-Role", description="Authorizing role"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[AttendanceRecordResponse]:
    """Process direct attendance regularization from request body."""
    emp_id = request.employee_id
    rec_date = request.date
    if not emp_id or not rec_date:
        from app.core.exceptions import InvalidTimestampError
        raise InvalidTimestampError("Both employee_id (or emp_code) and date must be specified.")
    service = AttendanceService(db)
    record = await service.regularize_attendance(
        employee_id=emp_id,
        date=rec_date,
        request=request,
        actor_id=x_actor_id,
        role=x_role,
    )
    return ApiResponse(
        message="Attendance regularized successfully.",
        data=record,
    )



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
    "/records/{employee_id}",
    response_model=ApiResponse[List[AttendanceRecordResponse]],
    include_in_schema=False,
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
    "/records/{employee_id}/{date}",
    response_model=ApiResponse[AttendanceRecordResponse],
    include_in_schema=False,
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
