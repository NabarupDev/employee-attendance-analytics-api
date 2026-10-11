"""API endpoints for attendance analytics powered by MongoDB Aggregation Pipelines."""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.client import get_database
from app.schemas.analytics import (
    DailyDepartmentSummaryResponse,
    DepartmentPeriodSummaryResponse,
    EmployeePeriodSummaryResponse,
)
from app.schemas.common import ApiResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Attendance Analytics"])


@router.get(
    "/daily-summary",
    response_model=ApiResponse[List[DailyDepartmentSummaryResponse]],
    summary="Daily Department Attendance Summary",
    description="Aggregates daily attendance counts, work hours, and correction statistics grouped by department.",
)
async def get_daily_summary(
    date: Optional[str] = Query(
        None,
        description="Target calendar date (YYYY-MM-DD). Defaults to current date (UTC).",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    department: Optional[str] = Query(None, description="Optional department filter"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[DailyDepartmentSummaryResponse]]:
    """Generate daily department attendance report using MongoDB aggregation pipeline."""
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    service = AnalyticsService(db)
    results = await service.get_daily_department_summary(
        date_str=target_date,
        department=department,
    )
    return ApiResponse(
        message=f"Generated daily attendance summary for {target_date}.",
        data=results,
    )


@router.get(
    "/employee/{employee_id}",
    response_model=ApiResponse[EmployeePeriodSummaryResponse],
    summary="Employee Period Attendance Summary",
    description="Calculates cumulative attendance days, work hours, daily breakdown, and average hours for an employee.",
)
async def get_employee_period_summary(
    employee_id: str,
    start_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period start date (YYYY-MM-DD)"),
    end_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period end date (YYYY-MM-DD)"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[EmployeePeriodSummaryResponse]:
    """Generate individual employee attendance period report using MongoDB aggregation pipeline."""
    service = AnalyticsService(db)
    result = await service.get_employee_period_summary(
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
    )
    return ApiResponse(
        message=f"Generated attendance summary for employee '{employee_id}' ({start_date} to {end_date}).",
        data=result,
    )


@router.get(
    "/department-summary",
    response_model=ApiResponse[DepartmentPeriodSummaryResponse],
    summary="Department Performance & Overtime Analytics",
    description="Computes total department attendance, presence rate, overtime days, and average hours over a period.",
)
async def get_department_period_summary(
    department: str = Query(..., min_length=2, description="Target department name (e.g. Engineering)"),
    start_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period start date (YYYY-MM-DD)"),
    end_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period end date (YYYY-MM-DD)"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[DepartmentPeriodSummaryResponse]:
    """Generate department performance report using MongoDB aggregation pipeline."""
    service = AnalyticsService(db)
    result = await service.get_department_period_summary(
        department=department,
        start_date=start_date,
        end_date=end_date,
    )
    return ApiResponse(
        message=f"Generated performance summary for department '{department}' ({start_date} to {end_date}).",
        data=result,
    )
