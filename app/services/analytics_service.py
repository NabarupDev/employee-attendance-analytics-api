"""Service layer implementing MongoDB Aggregation Pipelines for attendance analytics."""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import InvalidTimestampError
from app.schemas.analytics import (
    DailyDepartmentSummaryResponse,
    DepartmentPeriodSummaryResponse,
    EmployeePeriodDailyEntry,
    EmployeePeriodSummaryResponse,
)
from app.services.employee_service import EmployeeService

logger = logging.getLogger(__name__)


def validate_date_range(start_date: str, end_date: str) -> None:
    """Validate that start_date and end_date are valid YYYY-MM-DD and start_date <= end_date."""
    try:
        d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidTimestampError("Invalid calendar date format. Must follow YYYY-MM-DD.") from exc

    if d_start > d_end:
        raise InvalidTimestampError(
            f"start_date '{start_date}' cannot be after end_date '{end_date}'."
        )


class AnalyticsService:
    """Orchestrates multi-stage MongoDB aggregation pipelines for attendance analytics."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.db = db
        self.attendance_collection = db["attendance"]
        self.employee_service = EmployeeService(db)

    async def get_daily_department_summary(
        self,
        date_str: str,
        department: Optional[str] = None,
    ) -> List[DailyDepartmentSummaryResponse]:
        """
        Report 1: Daily Department Attendance Summary.
        
        MongoDB Aggregation Pipeline Stages:
        1. $match: Filter by specific date and optional department.
        2. $group: Group by department and aggregate counts and total work minutes.
        3. $project: Format fields and departmental metrics.
        4. $sort: Sort departments alphabetically.
        """
        match_stage: Dict[str, Any] = {"date": date_str}
        if department:
            match_stage["department"] = department

        pipeline = [
            {"$match": match_stage},
            {
                "$group": {
                    "_id": "$department",
                    "total_employees_logged": {"$sum": 1},
                    "present_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                    },
                    "half_day_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "HALF_DAY"]}, 1, 0]}
                    },
                    "absent_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]}
                    },
                    "in_progress_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$status", "IN_PROGRESS"]},
                                        {"$eq": ["$has_active_session", True]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "corrected_records_count": {
                        "$sum": {"$cond": ["$is_corrected", 1, 0]}
                    },
                    "total_work_minutes": {"$sum": "$total_work_minutes"},
                    "avg_work_minutes": {"$avg": "$total_work_minutes"},
                }
            },
            {
                "$project": {
                    "department": "$_id",
                    "total_employees_logged": 1,
                    "present_count": 1,
                    "half_day_count": 1,
                    "absent_count": 1,
                    "in_progress_count": 1,
                    "corrected_records_count": 1,
                    "total_work_minutes": 1,
                    "avg_work_minutes": 1,
                    "_id": 0,
                }
            },
            {"$sort": {"department": 1}},
        ]

        cursor = self.attendance_collection.aggregate(pipeline)
        raw_results = await cursor.to_list(length=500)

        results: List[DailyDepartmentSummaryResponse] = []
        for r in raw_results:
            total_mins = r.get("total_work_minutes", 0)
            avg_mins = r.get("avg_work_minutes", 0.0) or 0.0
            results.append(
                DailyDepartmentSummaryResponse(
                    date=date_str,
                    department=r["department"],
                    total_employees_logged=r.get("total_employees_logged", 0),
                    present_count=r.get("present_count", 0),
                    half_day_count=r.get("half_day_count", 0),
                    absent_count=r.get("absent_count", 0),
                    in_progress_count=r.get("in_progress_count", 0),
                    corrected_records_count=r.get("corrected_records_count", 0),
                    total_work_minutes=total_mins,
                    total_work_hours=round(total_mins / 60.0, 2),
                    avg_work_hours=round(avg_mins / 60.0, 2),
                )
            )

        return results

    async def get_employee_period_summary(
        self,
        employee_id: str,
        start_date: str,
        end_date: str,
    ) -> EmployeePeriodSummaryResponse:
        """
        Report 2: Employee Attendance & Work-Hour Summary over Date Range.
        
        MongoDB Aggregation Pipeline Stages:
        1. $match: Filter by employee_id and date boundaries ($gte, $lte).
        2. $sort: Sort daily entries chronologically.
        3. $group: Aggregate attendance days, work hours, and collect daily breakdown array.
        """
        await self.employee_service.ensure_employee_exists(employee_id)
        validate_date_range(start_date, end_date)

        pipeline = [
            {
                "$match": {
                    "employee_id": employee_id,
                    "date": {"$gte": start_date, "$lte": end_date},
                }
            },
            {"$sort": {"date": 1}},
            {
                "$group": {
                    "_id": "$employee_id",
                    "total_days_logged": {"$sum": 1},
                    "present_days": {
                        "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                    },
                    "half_days": {
                        "$sum": {"$cond": [{"$eq": ["$status", "HALF_DAY"]}, 1, 0]}
                    },
                    "absent_days": {
                        "$sum": {"$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]}
                    },
                    "in_progress_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$status", "IN_PROGRESS"]},
                                        {"$eq": ["$has_active_session", True]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "corrected_days_count": {
                        "$sum": {"$cond": ["$is_corrected", 1, 0]}
                    },
                    "total_work_minutes": {"$sum": "$total_work_minutes"},
                    "daily_records": {
                        "$push": {
                            "date": "$date",
                            "status": "$status",
                            "total_work_minutes": "$total_work_minutes",
                            "is_corrected": "$is_corrected",
                        }
                    },
                }
            },
        ]

        cursor = self.attendance_collection.aggregate(pipeline)
        raw_results = await cursor.to_list(length=1)

        if not raw_results:
            # Return empty clean summary if no attendance found in window
            return EmployeePeriodSummaryResponse(
                employee_id=employee_id,
                start_date=start_date,
                end_date=end_date,
                total_days_logged=0,
                present_days=0,
                half_days=0,
                absent_days=0,
                in_progress_days=0,
                corrected_days_count=0,
                total_work_minutes=0,
                total_work_hours=0.0,
                avg_daily_work_hours=0.0,
                daily_breakdown=[],
            )

        agg = raw_results[0]
        total_days = agg.get("total_days_logged", 0)
        total_mins = agg.get("total_work_minutes", 0)
        total_hours = round(total_mins / 60.0, 2)
        avg_daily_hours = round(total_hours / total_days, 2) if total_days > 0 else 0.0

        daily_breakdown = [
            EmployeePeriodDailyEntry(
                date=d["date"],
                status=d["status"],
                total_work_minutes=d.get("total_work_minutes", 0),
                total_work_hours=round(d.get("total_work_minutes", 0) / 60.0, 2),
                is_corrected=d.get("is_corrected", False),
            )
            for d in agg.get("daily_records", [])
        ]

        return EmployeePeriodSummaryResponse(
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            total_days_logged=total_days,
            present_days=agg.get("present_days", 0),
            half_days=agg.get("half_days", 0),
            absent_days=agg.get("absent_days", 0),
            in_progress_days=agg.get("in_progress_days", 0),
            corrected_days_count=agg.get("corrected_days_count", 0),
            total_work_minutes=total_mins,
            total_work_hours=total_hours,
            avg_daily_work_hours=avg_daily_hours,
            daily_breakdown=daily_breakdown,
        )

    async def get_department_period_summary(
        self,
        department: str,
        start_date: str,
        end_date: str,
    ) -> DepartmentPeriodSummaryResponse:
        """
        Report 3: Department Performance & Overtime Analytics over Date Range.
        
        MongoDB Aggregation Pipeline Stages:
        1. $match: Filter by department and date range ($gte, $lte).
        2. $group: Group by department, computing present rate, overtime counts, and averages.
        """
        validate_date_range(start_date, end_date)

        pipeline = [
            {
                "$match": {
                    "department": department,
                    "date": {"$gte": start_date, "$lte": end_date},
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "total_attendance_records": {"$sum": 1},
                    "present_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                    },
                    "half_day_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "HALF_DAY"]}, 1, 0]}
                    },
                    "absent_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]}
                    },
                    "corrected_records_count": {
                        "$sum": {"$cond": ["$is_corrected", 1, 0]}
                    },
                    "overtime_records_count": {
                        "$sum": {"$cond": [{"$gt": ["$total_work_minutes", 480]}, 1, 0]}
                    },
                    "total_work_minutes": {"$sum": "$total_work_minutes"},
                    "avg_work_minutes": {"$avg": "$total_work_minutes"},
                }
            },
        ]

        cursor = self.attendance_collection.aggregate(pipeline)
        raw_results = await cursor.to_list(length=1)

        if not raw_results:
            return DepartmentPeriodSummaryResponse(
                department=department,
                start_date=start_date,
                end_date=end_date,
                total_attendance_records=0,
                present_count=0,
                half_day_count=0,
                absent_count=0,
                corrected_records_count=0,
                overtime_records_count=0,
                total_work_minutes=0,
                total_work_hours=0.0,
                avg_hours_per_record=0.0,
                present_rate_percent=0.0,
            )

        agg = raw_results[0]
        total_records = agg.get("total_attendance_records", 0)
        present_count = agg.get("present_count", 0)
        total_mins = agg.get("total_work_minutes", 0)
        avg_mins = agg.get("avg_work_minutes", 0.0) or 0.0

        total_hours = round(total_mins / 60.0, 2)
        avg_hours = round(avg_mins / 60.0, 2)
        present_rate = (
            round((present_count / total_records) * 100.0, 2)
            if total_records > 0
            else 0.0
        )

        return DepartmentPeriodSummaryResponse(
            department=department,
            start_date=start_date,
            end_date=end_date,
            total_attendance_records=total_records,
            present_count=present_count,
            half_day_count=agg.get("half_day_count", 0),
            absent_count=agg.get("absent_count", 0),
            corrected_records_count=agg.get("corrected_records_count", 0),
            overtime_records_count=agg.get("overtime_records_count", 0),
            total_work_minutes=total_mins,
            total_work_hours=total_hours,
            avg_hours_per_record=avg_hours,
            present_rate_percent=present_rate,
        )
