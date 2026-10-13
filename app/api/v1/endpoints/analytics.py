"""API endpoints for attendance analytics powered by MongoDB Aggregation Pipelines."""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.client import get_database
from app.schemas.analytics import (
    DailyDepartmentSummaryResponse,
    DepartmentPeriodSummaryResponse,
    DepartmentTrendResponse,
    EmployeeMonthlySummaryResponse,
    EmployeePeriodSummaryResponse,
    LateArrivalLeaderboardEntry,
    MonthlyDepartmentSummaryResponse,
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


@router.get(
    "/monthly-summary",
    response_model=ApiResponse[List[MonthlyDepartmentSummaryResponse]],
    summary="Monthly Department Attendance Summary",
    description="Aggregates monthly attendance statistics, present/half/absent days, and overtime grouped by department.",
)
async def get_monthly_summary(
    year: int = Query(..., ge=2000, le=2100, description="Target calendar year (e.g. 2026)"),
    month: int = Query(..., ge=1, le=12, description="Target calendar month (1-12)"),
    department: Optional[str] = Query(None, description="Optional department filter"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[MonthlyDepartmentSummaryResponse]]:
    """Generate monthly attendance summary report."""
    service = AnalyticsService(db)
    results = await service.get_monthly_summary(
        year=year,
        month=month,
        department=department,
    )
    return ApiResponse(
        message=f"Generated monthly summary for {year:04d}-{month:02d}.",
        data=results,
    )


@router.get(
    "/late-arrivals",
    response_model=ApiResponse[List[LateArrivalLeaderboardEntry]],
    summary="Late-Arrival Leaderboard",
    description="Ranks employees by frequency of late arrivals based on shift start and a 15-minute grace period.",
)
@router.get(
    "/leaderboard/late",
    response_model=ApiResponse[List[LateArrivalLeaderboardEntry]],
    summary="Late-Arrival Leaderboard Alias",
    description="Alias endpoint ranking employees by late arrival counts.",
    include_in_schema=False,
)
async def get_late_arrivals(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period end date (YYYY-MM-DD)"),
    department: Optional[str] = Query(None, description="Optional department filter"),
    limit: int = Query(10, ge=1, le=100, description="Max leaderboard entries to return"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[LateArrivalLeaderboardEntry]]:
    """Generate late arrival leaderboard."""
    now_utc = datetime.now(timezone.utc)
    target_end = end_date or now_utc.strftime("%Y-%m-%d")
    target_start = start_date or f"{target_end[:7]}-01"
    service = AnalyticsService(db)
    results = await service.get_late_arrivals(
        start_date=target_start,
        end_date=target_end,
        department=department,
        limit=limit,
    )
    return ApiResponse(
        message=f"Generated late-arrival leaderboard for {target_start} to {target_end}.",
        data=results,
    )


@router.get(
    "/employees/{emp_code}/monthly",
    response_model=ApiResponse[EmployeeMonthlySummaryResponse],
    summary="Employee Monthly Attendance Summary",
    description="Calculates cumulative monthly attendance days, work hours, and daily breakdown for an employee.",
)
async def get_employee_monthly_summary(
    emp_code: str,
    year: Optional[int] = Query(None, ge=2000, le=2100, description="Target calendar year (defaults to current year)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Target calendar month 1-12 (defaults to current month)"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[EmployeeMonthlySummaryResponse]:
    """Generate employee monthly attendance report."""
    now_utc = datetime.now(timezone.utc)
    target_year = year or now_utc.year
    target_month = month or now_utc.month
    service = AnalyticsService(db)
    result = await service.get_employee_monthly_summary(
        employee_id=emp_code,
        year=target_year,
        month=target_month,
    )
    return ApiResponse(
        message=f"Generated monthly attendance summary for '{emp_code}' for {target_year:04d}-{target_month:02d}.",
        data=result,
    )


@router.get(
    "/departments/summary",
    response_model=ApiResponse[List[DepartmentPeriodSummaryResponse]],
    summary="Departments Summary (All or Specific)",
    description="Computes attendance, presence rate, overtime days, and average hours across departments over a date range.",
)
async def get_departments_summary(
    department: Optional[str] = Query(None, description="Optional target department name filter"),
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period end date (YYYY-MM-DD)"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[List[DepartmentPeriodSummaryResponse]]:
    """Generate multi-department performance summary report."""
    now_utc = datetime.now(timezone.utc)
    target_end = end_date or now_utc.strftime("%Y-%m-%d")
    target_start = start_date or f"{target_end[:7]}-01"
    service = AnalyticsService(db)
    results = await service.get_all_departments_period_summary(
        start_date=target_start,
        end_date=target_end,
        department=department,
    )
    return ApiResponse(
        message=f"Generated departments summary ({target_start} to {target_end}).",
        data=results,
    )


@router.get(
    "/departments/{department}/trend",
    response_model=ApiResponse[DepartmentTrendResponse],
    summary="Department Attendance Trend",
    description="Returns daily attendance, presence rates, and work-hour trends for a department.",
)
async def get_department_trend(
    department: str,
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Period end date (YYYY-MM-DD)"),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[DepartmentTrendResponse]:
    """Generate department daily trend report."""
    now_utc = datetime.now(timezone.utc)
    target_end = end_date or now_utc.strftime("%Y-%m-%d")
    target_start = start_date or f"{target_end[:7]}-01"
    service = AnalyticsService(db)
    result = await service.get_department_trend(
        department=department,
        start_date=target_start,
        end_date=target_end,
    )
    return ApiResponse(
        message=f"Generated trend analysis for department '{department}' ({target_start} to {target_end}).",
        data=result,
    )

