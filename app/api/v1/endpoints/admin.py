"""Admin endpoints for performance diagnostics and pipeline explanation."""

from typing import Optional
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.client import get_database
from app.schemas.analytics import AdminExplainResponse
from app.schemas.common import ApiResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/admin", tags=["Administration & Diagnostics"])


@router.get(
    "/explain/{endpoint_name}",
    response_model=ApiResponse[AdminExplainResponse],
    summary="Explain Aggregation Execution Plan",
    description="Returns MongoDB aggregation pipeline execution stats and stage details for an analytics endpoint.",
)
async def explain_pipeline(
    endpoint_name: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[AdminExplainResponse]:
    """Retrieve execution explanation for a given report."""
    service = AnalyticsService(db)
    result = await service.explain_report(endpoint_name)
    return ApiResponse(
        message=f"Execution plan for '{endpoint_name}' retrieved successfully.",
        data=result,
    )


@router.get(
    "/explain",
    response_model=ApiResponse[AdminExplainResponse],
    include_in_schema=False,
)
async def explain_pipeline_query(
    endpoint: Optional[str] = None,
    endpoint_name: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[AdminExplainResponse]:
    """Retrieve execution explanation via query parameter."""
    target = endpoint or endpoint_name or "daily-summary"
    service = AnalyticsService(db)
    result = await service.explain_report(target)
    return ApiResponse(
        message=f"Execution plan for '{target}' retrieved successfully.",
        data=result,
    )
