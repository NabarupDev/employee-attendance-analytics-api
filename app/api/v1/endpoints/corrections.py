"""API endpoints for attendance correction requests and review workflows."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Header, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.client import get_database
from app.schemas.common import ApiResponse
from app.schemas.correction import (
    CorrectionCreateRequest,
    CorrectionResponse,
    CorrectionStatusUpdateRequest,
)
from app.services.correction_service import CorrectionService

router = APIRouter(prefix="/corrections", tags=["Attendance Corrections"])


@router.post(
    "/request",
    response_model=ApiResponse[CorrectionResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Submit Attendance Correction Request",
    description="Submit an attendance correction request with proposed punches and mandatory justification.",
)
async def submit_correction(
    request: CorrectionCreateRequest,
    x_actor_id: Optional[str] = Header(None, alias="X-Actor-ID", description="Identifier of submitting actor"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[CorrectionResponse]:
    """Submit correction request for review."""
    service = CorrectionService(db)
    result = await service.submit_correction(
        data=request,
        actor_id=x_actor_id,
    )
    return ApiResponse(
        message="Attendance correction request submitted successfully.",
        data=result,
    )


@router.get(
    "",
    response_model=ApiResponse[List[CorrectionResponse]],
    summary="List Correction Requests",
    description="Retrieve correction requests filtered by employee ID, status (PENDING, APPROVED, REJECTED), or date.",
)
async def list_corrections(
    employee_id: Optional[str] = Query(None, description="Filter by employee identifier"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, APPROVED, REJECTED)"),
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Filter by attendance date (YYYY-MM-DD)"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[CorrectionResponse]]:
    """List correction requests matching filters."""
    service = CorrectionService(db)
    results = await service.list_corrections(
        employee_id=employee_id,
        status=status,
        date=date,
    )
    return ApiResponse(
        message=f"Found {len(results)} correction request(s).",
        data=results,
    )


@router.get(
    "/{correction_id}",
    response_model=ApiResponse[CorrectionResponse],
    summary="Get Correction Details",
    description="Retrieve details of a specific correction request including original snapshot.",
)
async def get_correction(
    correction_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[CorrectionResponse]:
    """Fetch correction request by ID."""
    service = CorrectionService(db)
    result = await service.get_correction(correction_id)
    return ApiResponse(data=result)


@router.patch(
    "/{correction_id}/status",
    response_model=ApiResponse[CorrectionResponse],
    summary="Review Correction Request",
    description="Approve or reject a correction request. Requires manager or admin role header.",
)
async def review_correction(
    correction_id: str,
    request: CorrectionStatusUpdateRequest,
    x_actor_id: str = Header(..., alias="X-Actor-ID", description="Reviewer employee/manager ID"),
    x_role: str = Header(..., alias="X-Role", description="Reviewer role (e.g. manager, admin)"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[CorrectionResponse]:
    """Process approval or rejection of a correction request."""
    service = CorrectionService(db)
    result = await service.review_correction(
        correction_id=correction_id,
        target_status=request.status,
        remarks=request.remarks,
        reviewer_id=x_actor_id,
        reviewer_role=x_role,
    )
    return ApiResponse(
        message=f"Correction request successfully {request.status.value.lower()}.",
        data=result,
    )
