"""Pydantic validation schemas for attendance analytics reports."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date": "2026-10-14",
                "department": "Engineering",
                "total_employees_logged": 15,
                "present_count": 12,
                "half_day_count": 2,
                "absent_count": 1,
                "in_progress_count": 1,
                "corrected_records_count": 0,
                "total_work_minutes": 6840,
                "total_work_hours": 114.0,
                "avg_work_hours": 7.6,
            }
        }
    )


class EmployeePeriodDailyEntry(BaseModel):
    """Individual daily breakdown entry within an employee period summary."""

    date: str
    status: str
    total_work_minutes: int
    total_work_hours: float
    is_corrected: bool

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date": "2026-10-13",
                "status": "PRESENT",
                "total_work_minutes": 510,
                "total_work_hours": 8.5,
                "is_corrected": False,
            }
        }
    )


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

    @computed_field
    @property
    def emp_code(self) -> str:
        """Alias for employee identifier."""
        return self.employee_id

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "emp_code": "EMP-1001",
                "start_date": "2026-10-01",
                "end_date": "2026-10-14",
                "total_days_logged": 10,
                "present_days": 8,
                "half_days": 2,
                "absent_days": 0,
                "in_progress_days": 0,
                "corrected_days_count": 1,
                "total_work_minutes": 4800,
                "total_work_hours": 80.0,
                "avg_daily_work_hours": 8.0,
                "daily_breakdown": [
                    {
                        "date": "2026-10-13",
                        "status": "PRESENT",
                        "total_work_minutes": 510,
                        "total_work_hours": 8.5,
                        "is_corrected": False,
                    }
                ],
            }
        }
    )


class EmployeeMonthlySummaryResponse(BaseModel):
    """Employee monthly attendance summary."""

    employee_id: str
    month: str  # YYYY-MM
    year: int
    month_number: int
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

    @computed_field
    @property
    def emp_code(self) -> str:
        """Alias for employee identifier."""
        return self.employee_id

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "emp_code": "EMP-1001",
                "month": "2026-10",
                "year": 2026,
                "month_number": 10,
                "total_days_logged": 10,
                "present_days": 8,
                "half_days": 2,
                "absent_days": 0,
                "in_progress_days": 0,
                "corrected_days_count": 0,
                "total_work_minutes": 4800,
                "total_work_hours": 80.0,
                "avg_daily_work_hours": 8.0,
                "daily_breakdown": [
                    {
                        "date": "2026-10-13",
                        "status": "PRESENT",
                        "total_work_minutes": 480,
                        "total_work_hours": 8.0,
                        "is_corrected": False,
                    }
                ],
            }
        }
    )


class DailyTrendEntry(BaseModel):
    """Daily performance and attendance metrics for trend reporting."""

    date: str
    total_records: int
    present_count: int
    half_day_count: int
    absent_count: int
    total_work_minutes: int
    total_work_hours: float
    avg_work_hours: float
    attendance_rate_percent: float

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date": "2026-10-13",
                "total_records": 20,
                "present_count": 18,
                "half_day_count": 2,
                "absent_count": 0,
                "total_work_minutes": 9600,
                "total_work_hours": 160.0,
                "avg_work_hours": 8.0,
                "attendance_rate_percent": 100.0,
            }
        }
    )


class DepartmentTrendResponse(BaseModel):
    """Trend of departmental attendance and work hours over a timeframe."""

    department: str
    start_date: str
    end_date: str
    daily_trends: List[DailyTrendEntry]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "department": "Engineering",
                "start_date": "2026-10-01",
                "end_date": "2026-10-14",
                "daily_trends": [
                    {
                        "date": "2026-10-13",
                        "total_records": 20,
                        "present_count": 18,
                        "half_day_count": 2,
                        "absent_count": 0,
                        "total_work_minutes": 9600,
                        "total_work_hours": 160.0,
                        "avg_work_hours": 8.0,
                        "attendance_rate_percent": 100.0,
                    }
                ],
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "department": "Engineering",
                "start_date": "2026-10-01",
                "end_date": "2026-10-14",
                "total_attendance_records": 50,
                "present_count": 45,
                "half_day_count": 5,
                "absent_count": 0,
                "corrected_records_count": 2,
                "overtime_records_count": 10,
                "total_work_minutes": 24000,
                "total_work_hours": 400.0,
                "avg_hours_per_record": 8.0,
                "present_rate_percent": 100.0,
            }
        }
    )


class MonthlyDepartmentSummaryResponse(BaseModel):
    """Monthly attendance overview grouped by department."""

    month: str  # YYYY-MM
    department: str
    total_attendance_records: int
    total_present_days: int
    total_half_days: int
    total_absent_days: int
    total_overtime_days: int
    total_work_hours: float
    avg_work_hours_per_day: float

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "month": "2026-10",
                "department": "Engineering",
                "total_attendance_records": 100,
                "total_present_days": 90,
                "total_half_days": 10,
                "total_absent_days": 0,
                "total_overtime_days": 20,
                "total_work_hours": 800.0,
                "avg_work_hours_per_day": 8.0,
            }
        }
    )


class LateArrivalLeaderboardEntry(BaseModel):
    """Leaderboard entry for employee late arrivals."""

    employee_id: str
    emp_code: str
    name: str
    department: str
    late_count: int
    total_late_minutes: int
    shift_start: str = "09:00"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "emp_code": "EMP-1001",
                "name": "Alice Walker",
                "department": "Engineering",
                "late_count": 3,
                "total_late_minutes": 45,
                "shift_start": "09:00",
            }
        }
    )


class AdminExplainResponse(BaseModel):
    """Execution plan explanation for MongoDB aggregation pipelines."""

    endpoint: str
    collection: str
    execution_success: bool
    execution_time_millis: float
    total_docs_examined: int
    n_returned: int
    stages_explained: List[str]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "endpoint": "/api/v1/analytics/departments/Engineering/trend",
                "collection": "attendance_records",
                "execution_success": True,
                "execution_time_millis": 2.45,
                "total_docs_examined": 150,
                "n_returned": 14,
                "stages_explained": [
                    "$match: { department: 'Engineering', date: { $gte: '2026-10-01', $lte: '2026-10-14' } }",
                    "$group: { _id: '$date', total_minutes: { $sum: '$total_work_minutes' } }",
                    "$sort: { _id: 1 }",
                ],
            }
        }
    )


