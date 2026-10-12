"""Unit and integration tests for MongoDB aggregation pipelines and attendance analytics."""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase


@pytest.mark.asyncio
async def test_analytics_against_known_dataset(async_client: AsyncClient, mock_db: AsyncIOMotorDatabase):
    """
    Test analytics pipelines against a controlled dataset with verified mathematical ground-truth.
    
    Dataset composition on 2026-10-10:
    - EMP-1001 (Engineering): 510 mins (8.5h), PRESENT, is_corrected=False
    - EMP-1002 (Product): 240 mins (4.0h), HALF_DAY, is_corrected=True
    - EMP-1003 (Engineering): 0 mins, IN_PROGRESS (open punch-in), has_active_session=True
    """
    # Seed 3rd employee for dataset
    await mock_db["employees"].insert_one({
        "employee_id": "EMP-1003",
        "name": "Charlie Brown",
        "email": "charlie@hr0ne.internal",
        "department": "Engineering",
        "designation": "QA Engineer",
        "is_active": True,
    })

    # Seed attendance documents
    await mock_db["attendance"].insert_many([
        {
            "employee_id": "EMP-1001",
            "department": "Engineering",
            "date": "2026-10-10",
            "punches": [
                {
                    "session_id": "s1",
                    "punch_in": datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc),
                    "punch_out": datetime(2026, 10, 10, 17, 30, tzinfo=timezone.utc),
                    "duration_minutes": 510,
                }
            ],
            "has_active_session": False,
            "total_work_minutes": 510,
            "status": "PRESENT",
            "is_corrected": False,
        },
        {
            "employee_id": "EMP-1002",
            "department": "Product",
            "date": "2026-10-10",
            "punches": [
                {
                    "session_id": "s2",
                    "punch_in": datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc),
                    "punch_out": datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc),
                    "duration_minutes": 240,
                }
            ],
            "has_active_session": False,
            "total_work_minutes": 240,
            "status": "HALF_DAY",
            "is_corrected": True,
        },
        {
            "employee_id": "EMP-1003",
            "department": "Engineering",
            "date": "2026-10-10",
            "punches": [
                {
                    "session_id": "s3",
                    "punch_in": datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
                    "punch_out": None,
                    "duration_minutes": None,
                }
            ],
            "has_active_session": True,
            "total_work_minutes": 0,
            "status": "IN_PROGRESS",
            "is_corrected": False,
        },
    ])

    # 1. Test Daily Summary (All Departments)
    res_daily = await async_client.get("/api/v1/analytics/daily-summary?date=2026-10-10")
    assert res_daily.status_code == 200
    daily_data = res_daily.json()["data"]
    assert len(daily_data) == 2  # Engineering and Product

    # Verify Engineering Metrics
    eng = next(d for d in daily_data if d["department"] == "Engineering")
    assert eng["total_employees_logged"] == 2
    assert eng["present_count"] == 1
    assert eng["half_day_count"] == 0
    assert eng["in_progress_count"] == 1
    assert eng["total_work_minutes"] == 510
    assert eng["total_work_hours"] == 8.5
    assert eng["avg_work_hours"] == 4.25
    assert eng["corrected_records_count"] == 0

    # Verify Product Metrics
    prod = next(d for d in daily_data if d["department"] == "Product")
    assert prod["total_employees_logged"] == 1
    assert prod["present_count"] == 0
    assert prod["half_day_count"] == 1
    assert prod["total_work_minutes"] == 240
    assert prod["total_work_hours"] == 4.0
    assert prod["avg_work_hours"] == 4.0
    assert prod["corrected_records_count"] == 1

    # 2. Test Daily Summary Filtered by Single Department
    res_eng_only = await async_client.get("/api/v1/analytics/daily-summary?date=2026-10-10&department=Engineering")
    assert res_eng_only.status_code == 200
    eng_only_data = res_eng_only.json()["data"]
    assert len(eng_only_data) == 1
    assert eng_only_data[0]["department"] == "Engineering"


@pytest.mark.asyncio
async def test_employee_period_summary_pipeline(async_client: AsyncClient, mock_db: AsyncIOMotorDatabase):
    """Verify employee period aggregation pipeline computes totals, averages, and daily breakdown."""
    # Seed 3 consecutive dates for EMP-1001:
    # 2026-10-01: 480 mins (8.0h, PRESENT)
    # 2026-10-02: 240 mins (4.0h, HALF_DAY, is_corrected=True)
    # 2026-10-03: 540 mins (9.0h, PRESENT)
    await mock_db["attendance"].insert_many([
        {
            "employee_id": "EMP-1001",
            "department": "Engineering",
            "date": "2026-10-01",
            "punches": [{"session_id": "p1", "punch_in": datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc), "punch_out": datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc), "duration_minutes": 480}],
            "has_active_session": False,
            "total_work_minutes": 480,
            "status": "PRESENT",
            "is_corrected": False,
        },
        {
            "employee_id": "EMP-1001",
            "department": "Engineering",
            "date": "2026-10-02",
            "punches": [{"session_id": "p2", "punch_in": datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), "punch_out": datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc), "duration_minutes": 240}],
            "has_active_session": False,
            "total_work_minutes": 240,
            "status": "HALF_DAY",
            "is_corrected": True,
        },
        {
            "employee_id": "EMP-1001",
            "department": "Engineering",
            "date": "2026-10-03",
            "punches": [{"session_id": "p3", "punch_in": datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc), "punch_out": datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc), "duration_minutes": 540}],
            "has_active_session": False,
            "total_work_minutes": 540,
            "status": "PRESENT",
            "is_corrected": False,
        },
    ])

    response = await async_client.get(
        "/api/v1/analytics/employee/EMP-1001?start_date=2026-10-01&end_date=2026-10-03"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["employee_id"] == "EMP-1001"
    assert data["total_days_logged"] == 3
    assert data["present_days"] == 2
    assert data["half_days"] == 1
    assert data["corrected_days_count"] == 1
    assert data["total_work_minutes"] == 1260  # 480 + 240 + 540
    assert data["total_work_hours"] == 21.0
    assert data["avg_daily_work_hours"] == 7.0  # 21.0 / 3
    assert len(data["daily_breakdown"]) == 3
    assert data["daily_breakdown"][1]["date"] == "2026-10-02"
    assert data["daily_breakdown"][1]["is_corrected"] is True


@pytest.mark.asyncio
async def test_department_period_summary_and_overtime(async_client: AsyncClient, mock_db: AsyncIOMotorDatabase):
    """Verify department performance pipeline calculates rates, overtime records, and corrections."""
    await mock_db["attendance"].insert_many([
        # Day 1: 540 mins (>480 -> Overtime, PRESENT)
        {"employee_id": "EMP-1001", "department": "Engineering", "date": "2026-10-01", "total_work_minutes": 540, "status": "PRESENT", "is_corrected": False},
        # Day 2: 480 mins (Standard, PRESENT)
        {"employee_id": "EMP-1001", "department": "Engineering", "date": "2026-10-02", "total_work_minutes": 480, "status": "PRESENT", "is_corrected": False},
        # Day 3: 240 mins (HALF_DAY, is_corrected)
        {"employee_id": "EMP-1001", "department": "Engineering", "date": "2026-10-03", "total_work_minutes": 240, "status": "HALF_DAY", "is_corrected": True},
        # Day 4: 120 mins (ABSENT)
        {"employee_id": "EMP-1001", "department": "Engineering", "date": "2026-10-04", "total_work_minutes": 120, "status": "ABSENT", "is_corrected": False},
    ])

    response = await async_client.get(
        "/api/v1/analytics/department-summary?department=Engineering&start_date=2026-10-01&end_date=2026-10-04"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["department"] == "Engineering"
    assert data["total_attendance_records"] == 4
    assert data["present_count"] == 2
    assert data["half_day_count"] == 1
    assert data["absent_count"] == 1
    assert data["overtime_records_count"] == 1  # 540 mins > 480
    assert data["corrected_records_count"] == 1
    assert data["total_work_minutes"] == 1380
    assert data["total_work_hours"] == 23.0
    assert data["avg_hours_per_record"] == 5.75  # 23.0 / 4
    assert data["present_rate_percent"] == 50.0   # 2/4 * 100


@pytest.mark.asyncio
async def test_analytics_empty_result_sets(async_client: AsyncClient):
    """Verify querying dates/ranges with zero records returns graceful empty responses."""
    # Daily summary for empty date
    res_daily = await async_client.get("/api/v1/analytics/daily-summary?date=2025-01-01")
    assert res_daily.status_code == 200
    assert res_daily.json()["data"] == []

    # Employee period for empty range
    res_emp = await async_client.get(
        "/api/v1/analytics/employee/EMP-1001?start_date=2025-01-01&end_date=2025-01-31"
    )
    assert res_emp.status_code == 200
    data_emp = res_emp.json()["data"]
    assert data_emp["total_days_logged"] == 0
    assert data_emp["total_work_hours"] == 0.0
    assert data_emp["daily_breakdown"] == []

    # Department summary for empty range
    res_dept = await async_client.get(
        "/api/v1/analytics/department-summary?department=Engineering&start_date=2025-01-01&end_date=2025-01-31"
    )
    assert res_dept.status_code == 200
    data_dept = res_dept.json()["data"]
    assert data_dept["total_attendance_records"] == 0
    assert data_dept["present_rate_percent"] == 0.0


@pytest.mark.asyncio
async def test_analytics_invalid_parameters_fail_422(async_client: AsyncClient):
    """Verify start_date > end_date and invalid formats are rejected with 422."""
    # start_date > end_date
    response = await async_client.get(
        "/api/v1/analytics/employee/EMP-1001?start_date=2026-10-10&end_date=2026-10-01"
    )
    assert response.status_code == 422

    # Malformed date format
    bad_format = await async_client.get(
        "/api/v1/analytics/daily-summary?date=10-10-2026"
    )
    assert bad_format.status_code == 422


@pytest.mark.asyncio
async def test_daily_department_summary_calculates_absent_count(
    async_client: AsyncClient,
    mock_db: AsyncIOMotorDatabase,
):
    """
    Verify that employees who worked under 240 minutes
    (marked as ABSENT) are counted in absent_count in Daily Department Summary.
    """
    target_date = "2026-10-09"
    await mock_db["attendance"].insert_one({
        "employee_id": "EMP-1001",
        "department": "Engineering",
        "date": target_date,
        "punches": [
            {
                "session_id": "s-absent",
                "punch_in": datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc),
                "punch_out": datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc),
                "duration_minutes": 120,
            }
        ],
        "has_active_session": False,
        "total_work_minutes": 120,
        "status": "ABSENT",
        "is_corrected": False,
        "created_at": datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 9, 11, 0, tzinfo=timezone.utc),
    })

    res = await async_client.get(f"/api/v1/analytics/daily-summary?date={target_date}&department=Engineering")
    assert res.status_code == 200
    dept_data = res.json()["data"][0]
    assert dept_data["total_employees_logged"] == 1
    assert dept_data["absent_count"] == 1
    assert dept_data["present_count"] == 0
    assert dept_data["half_day_count"] == 0
    assert dept_data["total_work_minutes"] == 120
