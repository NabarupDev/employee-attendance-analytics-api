"""Contract alignment tests verifying unprefixed routes, emp_code aliases, and epoch timestamps."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_unprefixed_employee_registration_with_emp_code(async_client: AsyncClient):
    """Verify POST /employees accepts emp_code and returns dual identifier attributes."""
    payload = {
        "emp_code": "EMP-9999",
        "name": "Sarah Connor",
        "email": "sarah.connor@hr0ne.internal",
        "department": "Security",
        "designation": "Security Lead",
        "shift_start": "08:30",
        "shift_end": "17:30",
        "joined_on": "2026-01-15",
    }
    response = await async_client.post("/employees", json=payload)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["employee_id"] == "EMP-9999"
    assert data["emp_code"] == "EMP-9999"
    assert data["shift_start"] == "08:30"
    assert data["shift_end"] == "17:30"
    assert data["joined_on"] == "2026-01-15"

    # Also verify GET /employees/{emp_code} resolves correctly
    get_res = await async_client.get("/employees/EMP-9999")
    assert get_res.status_code == 200
    assert get_res.json()["data"]["emp_code"] == "EMP-9999"


@pytest.mark.asyncio
async def test_unprefixed_punch_in_and_out_with_epoch_ms(async_client: AsyncClient):
    """Verify POST /attendance/punch-in and punch-out accept epoch milliseconds and emp_code."""
    # Seed employee
    await async_client.post("/employees", json={
        "emp_code": "EMP-5555",
        "name": "Kyle Reese",
        "email": "kyle.reese@hr0ne.internal",
        "department": "Operations",
    })

    # Oct 10 2026 09:00:00 UTC = 1791622800000 ms
    # Oct 10 2026 17:30:00 UTC = 1791653400000 ms
    ts_in_ms = 1791622800000
    ts_out_ms = 1791653400000

    punch_in_res = await async_client.post("/attendance/punch-in", json={
        "emp_code": "EMP-5555",
        "timestamp": ts_in_ms,
    })
    assert punch_in_res.status_code == 201
    data = punch_in_res.json()["data"]
    assert data["employee_id"] == "EMP-5555"
    assert data["emp_code"] == "EMP-5555"
    assert data["status"] == "IN_PROGRESS"
    assert data["has_active_session"] is True

    punch_out_res = await async_client.post("/attendance/punch-out", json={
        "emp_code": "EMP-5555",
        "timestamp": ts_out_ms,
    })
    assert punch_out_res.status_code == 200
    data_out = punch_out_res.json()["data"]
    assert data_out["has_active_session"] is False
    assert data_out["total_work_minutes"] == 510
    assert data_out["total_work_hours"] == 8.5
    assert data_out["status"] == "PRESENT"


@pytest.mark.asyncio
async def test_root_get_attendance(async_client: AsyncClient):
    """Verify GET /attendance returns list of attendance records across all employees."""
    # Seed attendance
    await async_client.post("/attendance/punch-in", json={
        "employee_id": "EMP-1001",
        "timestamp": "2026-10-09T09:00:00Z",
    })
    await async_client.post("/attendance/punch-out", json={
        "employee_id": "EMP-1001",
        "timestamp": "2026-10-09T17:00:00Z",
    })

    response = await async_client.get("/attendance")
    assert response.status_code == 200
    records = response.json()["data"]
    assert len(records) >= 1
    assert records[0]["employee_id"] == "EMP-1001"
    assert records[0]["emp_code"] == "EMP-1001"


@pytest.mark.asyncio
async def test_direct_regularization_endpoint(async_client: AsyncClient):
    """Verify PATCH /attendance/records/{emp_code}/{date}/regularize updates attendance and creates audit entry."""
    reg_payload = {
        "punch_in": "2026-10-08T09:00:00Z",
        "punch_out": "2026-10-08T18:00:00Z",
        "reason": "Biometric device offline during entry and exit.",
    }
    response = await async_client.patch(
        "/attendance/records/EMP-1001/2026-10-08/regularize",
        json=reg_payload,
        headers={"X-Actor-ID": "MGR-1001"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["employee_id"] == "EMP-1001"
    assert data["emp_code"] == "EMP-1001"
    assert data["date"] == "2026-10-08"
    assert data["total_work_minutes"] == 540
    assert data["total_work_hours"] == 9.0
    assert data["status"] == "PRESENT"
    assert data["is_corrected"] is True


@pytest.mark.asyncio
async def test_monthly_summary_and_late_arrivals(async_client: AsyncClient):
    """Verify monthly summary and late arrivals leaderboard endpoints."""
    # Seed late punch-in: shift is 09:00, arrival at 09:30 (late by 30 mins, past 15 min grace)
    await async_client.post("/employees", json={
        "emp_code": "EMP-7777",
        "name": "John Connor",
        "email": "john.connor@hr0ne.internal",
        "department": "Engineering",
        "shift_start": "09:00",
    })
    await async_client.post("/attendance/punch-in", json={
        "emp_code": "EMP-7777",
        "timestamp": "2026-10-11T09:30:00Z",
    })
    await async_client.post("/attendance/punch-out", json={
        "emp_code": "EMP-7777",
        "timestamp": "2026-10-11T18:00:00Z",
    })

    # Test monthly summary
    monthly_res = await async_client.get("/analytics/monthly-summary?year=2026&month=10")
    assert monthly_res.status_code == 200
    m_data = monthly_res.json()["data"]
    assert len(m_data) >= 1
    assert any(d["department"] == "Engineering" for d in m_data)

    # Test late arrivals leaderboard
    late_res = await async_client.get("/analytics/late-arrivals?start_date=2026-10-01&end_date=2026-10-15")
    assert late_res.status_code == 200
    l_data = late_res.json()["data"]
    assert len(l_data) >= 1
    john = next((item for item in l_data if item["employee_id"] == "EMP-7777"), None)
    assert john is not None
    assert john["late_count"] >= 1
    assert john["total_late_minutes"] >= 30


@pytest.mark.asyncio
async def test_admin_explain_endpoint(async_client: AsyncClient):
    """Verify GET /admin/explain/{endpoint_name} works on root and prefixed paths."""
    res_root = await async_client.get("/admin/explain/daily-summary")
    assert res_root.status_code == 200
    data_root = res_root.json()["data"]
    assert data_root["endpoint"] == "daily-summary"
    assert data_root["execution_success"] is True
    assert len(data_root["stages_explained"]) > 0

    res_v1 = await async_client.get("/api/v1/admin/explain/daily-summary")
    assert res_v1.status_code == 200
    assert res_v1.json()["data"]["endpoint"] == "daily-summary"


@pytest.mark.asyncio
async def test_correction_and_attendance_alias_routes(async_client: AsyncClient):
    """Verify alias routes for submitting/reviewing corrections and fetching records."""
    # 1. Test POST /corrections directly (without /request)
    corr_payload = {
        "emp_code": "EMP-1001",
        "attendance_date": "2026-10-12",
        "proposed_punches": [
            {"punch_in": "2026-10-12T09:00:00Z", "punch_out": "2026-10-12T17:00:00Z"}
        ],
        "reason": "RFID badge forgotten at home, biometric log missing.",
    }
    create_res = await async_client.post("/corrections", json=corr_payload)
    assert create_res.status_code == 201
    cid = create_res.json()["data"]["id"]

    # 2. Test POST /corrections/{id}/review requires authorized manager role (no blind manager default)
    unauth_res = await async_client.post(
        f"/corrections/{cid}/review",
        json={"status": "APPROVED", "remarks": "Attempt without authorized role"},
        headers={"X-Actor-ID": "EMP-9999"},
    )
    assert unauth_res.status_code == 403

    # Authorized review with explicit X-Role: manager
    review_res = await async_client.post(
        f"/corrections/{cid}/review",
        json={"status": "APPROVED", "remarks": "Approved by senior manager"},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert review_res.status_code == 200
    assert review_res.json()["data"]["status"] == "APPROVED"


    # 3. Test GET /attendance/records/{employee_id} alias
    records_res = await async_client.get("/attendance/records/EMP-1001")
    assert records_res.status_code == 200
    assert len(records_res.json()["data"]) >= 1

    # 4. Test GET /attendance/records/{employee_id}/{date} alias
    daily_res = await async_client.get("/attendance/records/EMP-1001/2026-10-12")
    assert daily_res.status_code == 200
    assert daily_res.json()["data"]["is_corrected"] is True


@pytest.mark.asyncio
async def test_employees_listing_endpoint(async_client: AsyncClient):
    """Verify GET /employees returns registered employees with filtering."""
    res = await async_client.get("/employees")
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) >= 1
    assert "employee_id" in data[0]
    assert "emp_code" in data[0]
    assert "department" in data[0]

    # Department filter
    dept_res = await async_client.get("/employees?department=Security")
    assert dept_res.status_code == 200
    for emp in dept_res.json()["data"]:
        assert emp["department"] == "Security"


@pytest.mark.asyncio
async def test_employee_monthly_analytics_endpoint(async_client: AsyncClient):
    """Verify GET /analytics/employees/{emp_code}/monthly calculates monthly breakdown."""
    res = await async_client.get("/analytics/employees/EMP-1001/monthly?year=2026&month=10")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["employee_id"] == "EMP-1001"
    assert data["emp_code"] == "EMP-1001"
    assert data["month"] == "2026-10"
    assert data["year"] == 2026
    assert data["month_number"] == 10
    assert "total_days_logged" in data
    assert "total_work_hours" in data
    assert "daily_breakdown" in data


@pytest.mark.asyncio
async def test_departments_summary_endpoint(async_client: AsyncClient):
    """Verify GET /analytics/departments/summary aggregates multi-department performance."""
    res = await async_client.get("/analytics/departments/summary?start_date=2026-10-01&end_date=2026-10-15")
    assert res.status_code == 200
    data = res.json()["data"]
    assert isinstance(data, list)
    if len(data) > 0:
        assert "department" in data[0]
        assert "present_rate_percent" in data[0]
        assert "total_attendance_records" in data[0]


@pytest.mark.asyncio
async def test_departments_trend_and_leaderboard_late_endpoints(async_client: AsyncClient):
    """Verify GET /analytics/departments/{department}/trend and /analytics/leaderboard/late."""
    # 1. Department trend
    trend_res = await async_client.get("/analytics/departments/Engineering/trend?start_date=2026-10-01&end_date=2026-10-15")
    assert trend_res.status_code == 200
    t_data = trend_res.json()["data"]
    assert t_data["department"] == "Engineering"
    assert "daily_trends" in t_data

    # 2. Late leaderboard alias
    late_res = await async_client.get("/analytics/leaderboard/late")
    assert late_res.status_code == 200
    assert isinstance(late_res.json()["data"], list)


@pytest.mark.asyncio
async def test_direct_regularize_body_and_admin_explain_query(async_client: AsyncClient):
    """Verify POST /attendance/regularize and GET /admin/explain via query parameter."""
    # 1. Direct regularize via body
    reg_res = await async_client.post(
        "/attendance/regularize",
        json={
            "emp_code": "EMP-1001",
            "date": "2026-10-13",
            "punch_in": "2026-10-13T08:30:00Z",
            "punch_out": "2026-10-13T17:30:00Z",
            "reason": "Biometric system maintenance at security post.",
        },
        headers={"X-Actor-ID": "MGR-1001"},
    )
    assert reg_res.status_code == 200
    assert reg_res.json()["data"]["employee_id"] == "EMP-1001"
    assert reg_res.json()["data"]["status"] == "PRESENT"
    assert reg_res.json()["data"]["is_corrected"] is True

    # 2. Admin explain via query param
    explain_res = await async_client.get("/admin/explain?endpoint=daily-summary")
    assert explain_res.status_code == 200
    assert explain_res.json()["data"]["endpoint"] == "daily-summary"
    assert explain_res.json()["data"]["execution_success"] is True



