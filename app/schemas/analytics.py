"""Pydantic validation schemas for attendance analytics reports."""

from typing import List, Optional
from pydantic import BaseModel, Field


class DailyDepartmentSummaryResponse(BaseModel):
    """Daily attendance summary grouped by department."""

    date: str
    department: str
    total_employees_logged: int
    present_count: int
    half_day_count: int
    absent_count: int = 0
    in_progress_count: int
    corrected_records_count: int
    total_work_minutes: int
    total_work_hours: float
    avg_work_hours: float


class EmployeePeriodDailyEntry(BaseModel):
    """Individual daily breakdown entry within an employee period summary."""

    date: str
    status: str
    total_work_minutes: int
    total_work_hours: float
    is_corrected: bool


class EmployeePeriodSummaryResponse(BaseModel):
    """Employee attendance and work hour analytics across a date range."""

    employee_id: str
    start_date: str
    end_date: str
    total_days_logged: int
    present_days: int
    half_days: int
    absent_days: int
    in_progress_days: int
    corrected_days_count: int
    total_work_minutes: int
    total_work_hours: float
    avg_daily_work_hours: float
    daily_breakdown: List[EmployeePeriodDailyEntry]


class DepartmentPeriodSummaryResponse(BaseModel):
    """Department performance and punctuality analytics across a date range."""

    department: str
    start_date: str
    end_date: str
    total_attendance_records: int
    present_count: int
    half_day_count: int
    absent_count: int
    corrected_records_count: int
    overtime_records_count: int
    total_work_minutes: int
    total_work_hours: float
    avg_hours_per_record: float
    present_rate_percent: float
