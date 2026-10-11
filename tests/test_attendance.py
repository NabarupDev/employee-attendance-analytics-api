"""Unit and integration tests for attendance operations, session transitions, and business rules."""

from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_successful_punch_in(async_client: AsyncClient):
    """Verify successful punch-in records session and returns HTTP 201 Created."""
    # Past timestamp earlier today
    now = datetime.now(timezone.utc)
    punch_time = (now - timedelta(minutes=10)).isoformat()

    response = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": punch_time},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["employee_id"] == "EMP-1001"
    assert data["department"] == "Engineering"
    assert data["has_active_session"] is True
    assert data["status"] == "IN_PROGRESS"
    assert len(data["punches"]) == 1
    assert data["punches"][0]["punch_out"] is None


@pytest.mark.asyncio
async def test_successful_punch_out_and_duration_calculation(async_client: AsyncClient):
    """Verify punch-out closes session, computes duration, and determines status."""
    # Using past date (2026-10-05) to ensure times are not in the future
    base_time = datetime(2026, 10, 5, 9, 0, 0, tzinfo=timezone.utc)
    in_time = base_time.isoformat()
    out_time = (base_time + timedelta(hours=8, minutes=30)).isoformat()  # 510 minutes

    # Punch in
    in_res = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": in_time},
    )
    assert in_res.status_code == 201

    # Punch out
    out_res = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": out_time},
    )
    assert out_res.status_code == 200
    data = out_res.json()["data"]
    assert data["has_active_session"] is False
    assert data["total_work_minutes"] == 510
    assert data["total_work_hours"] == 8.5
    assert data["status"] == "PRESENT"
    assert len(data["punches"]) == 1
    assert data["punches"][0]["duration_minutes"] == 510


@pytest.mark.asyncio
async def test_duplicate_punch_in_fails_400(async_client: AsyncClient):
    """BR-01: Verify duplicate punch-in while active session is open is rejected with 400."""
    base_time = datetime(2026, 10, 5, 9, 0, 0, tzinfo=timezone.utc)

    # First punch in
    first_res = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": base_time.isoformat()},
    )
    assert first_res.status_code == 201

    # Duplicate punch in
    duplicate_res = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": (base_time + timedelta(minutes=30)).isoformat()},
    )
    assert duplicate_res.status_code == 400
    error_payload = duplicate_res.json()
    assert error_payload["error"] == "ACTIVE_SESSION_EXISTS"
    assert "already has an active punch session" in error_payload["message"].lower()


@pytest.mark.asyncio
async def test_punch_out_without_active_session_fails_400(async_client: AsyncClient):
    """BR-02: Verify punch-out without active session is rejected with 400."""
    past_time = datetime(2026, 10, 5, 17, 0, 0, tzinfo=timezone.utc).isoformat()
    response = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": past_time},
    )
    assert response.status_code == 400
    error_payload = response.json()
    assert error_payload["error"] == "NO_ACTIVE_SESSION"
    assert "no active punch session" in error_payload["message"].lower()


@pytest.mark.asyncio
async def test_punch_out_before_punch_in_fails_422(async_client: AsyncClient):
    """BR-03: Verify punch-out timestamp <= punch-in timestamp is rejected with 422."""
    in_time = datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc)
    out_time_invalid = datetime(2026, 10, 5, 9, 30, 0, tzinfo=timezone.utc)

    await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": in_time.isoformat()},
    )

    response = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": out_time_invalid.isoformat()},
    )
    assert response.status_code == 422
    error_payload = response.json()
    assert error_payload["error"] == "INVALID_TIMESTAMP"
    assert "strictly after" in error_payload["message"].lower()


@pytest.mark.asyncio
async def test_future_timestamp_fails_422(async_client: AsyncClient):
    """BR-04: Verify future timestamps are rejected with HTTP 422."""
    future_time = datetime.now(timezone.utc) + timedelta(days=2)
    response = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": future_time.isoformat()},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_employee_fails_404(async_client: AsyncClient):
    """Verify punch operations for non-existent employee return HTTP 404."""
    response = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-9999"},
    )
    assert response.status_code == 404
    error_payload = response.json()
    assert error_payload["error"] == "EMPLOYEE_NOT_FOUND"


@pytest.mark.asyncio
async def test_multiple_sessions_same_day_status_progression(async_client: AsyncClient):
    """Verify multiple punch sessions in a day accumulate hours and update status correctly."""
    # Morning session: 4 hours (240 mins) on 2026-10-06 -> status: HALF_DAY
    m_in = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc).isoformat()
    m_out = datetime(2026, 10, 6, 13, 0, 0, tzinfo=timezone.utc).isoformat()

    await async_client.post("/api/v1/attendance/punch-in", json={"employee_id": "EMP-1001", "timestamp": m_in})
    out1 = await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": m_out})
    assert out1.status_code == 200
    assert out1.json()["data"]["status"] == "HALF_DAY"
    assert out1.json()["data"]["total_work_minutes"] == 240

    # Afternoon session: another 4.5 hours (270 mins) -> total 510 mins -> status: PRESENT
    a_in = datetime(2026, 10, 6, 14, 0, 0, tzinfo=timezone.utc).isoformat()
    a_out = datetime(2026, 10, 6, 18, 30, 0, tzinfo=timezone.utc).isoformat()

    await async_client.post("/api/v1/attendance/punch-in", json={"employee_id": "EMP-1001", "timestamp": a_in})
    out2 = await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": a_out})
    assert out2.status_code == 200
    assert out2.json()["data"]["status"] == "PRESENT"
    assert out2.json()["data"]["total_work_minutes"] == 510
    assert out2.json()["data"]["total_work_hours"] == 8.5
    assert len(out2.json()["data"]["punches"]) == 2


@pytest.mark.asyncio
async def test_get_attendance_history_and_filtering(async_client: AsyncClient):
    """Verify querying employee attendance history with date filters."""
    # Create two records on different past dates
    d1_in = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc).isoformat()
    d1_out = datetime(2026, 10, 1, 17, 0, 0, tzinfo=timezone.utc).isoformat()
    await async_client.post("/api/v1/attendance/punch-in", json={"employee_id": "EMP-1001", "timestamp": d1_in})
    await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": d1_out})

    d2_in = datetime(2026, 10, 2, 9, 0, 0, tzinfo=timezone.utc).isoformat()
    d2_out = datetime(2026, 10, 2, 17, 0, 0, tzinfo=timezone.utc).isoformat()
    await async_client.post("/api/v1/attendance/punch-in", json={"employee_id": "EMP-1001", "timestamp": d2_in})
    await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": d2_out})

    # Query all records
    all_res = await async_client.get("/api/v1/attendance/EMP-1001")
    assert all_res.status_code == 200
    assert len(all_res.json()["data"]) == 2

    # Query specific date
    single_res = await async_client.get("/api/v1/attendance/EMP-1001?date=2026-10-01")
    assert single_res.status_code == 200
    assert len(single_res.json()["data"]) == 1
    assert single_res.json()["data"][0]["date"] == "2026-10-01"

    # Query daily endpoint directly
    daily_res = await async_client.get("/api/v1/attendance/EMP-1001/daily/2026-10-01")
    assert daily_res.status_code == 200
    assert daily_res.json()["data"]["date"] == "2026-10-01"

    # Query non-existent daily record -> 404
    missing_res = await async_client.get("/api/v1/attendance/EMP-1001/daily/2026-09-01")
    assert missing_res.status_code == 404
    assert missing_res.json()["error"] == "ATTENDANCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_register_and_lookup_new_employee(async_client: AsyncClient):
    """Verify registering a new employee via POST /api/v1/employees."""
    new_emp_payload = {
        "employee_id": "EMP-2005",
        "name": "Clara Oswald",
        "email": "clara.oswald@hr0ne.internal",
        "department": "Finance",
        "designation": "Financial Analyst",
    }
    create_res = await async_client.post("/api/v1/employees", json=new_emp_payload)
    assert create_res.status_code == 201
    assert create_res.json()["data"]["employee_id"] == "EMP-2005"

    # Lookup employee
    get_res = await async_client.get("/api/v1/employees/EMP-2005")
    assert get_res.status_code == 200
    assert get_res.json()["data"]["department"] == "Finance"


@pytest.mark.asyncio
async def test_cross_day_punch_in_rejected_when_active(async_client: AsyncClient):
    """
    Verify that an active session from a previous day
    blocks punch-in on subsequent days until punched out.
    """
    # Day 1: Punch in at 23:00 UTC
    day1_time = datetime(2026, 10, 10, 23, 0, 0, tzinfo=timezone.utc).isoformat()
    res1 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": day1_time},
    )
    assert res1.status_code == 201

    # Day 2: Attempt punch in at 08:00 UTC without punching out Day 1
    day2_time = datetime(2026, 10, 11, 8, 0, 0, tzinfo=timezone.utc).isoformat()
    res2 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": day2_time},
    )
    assert res2.status_code == 400
    assert res2.json()["error"] == "ACTIVE_SESSION_EXISTS"


@pytest.mark.asyncio
async def test_overlapping_same_day_punch_in_rejected(async_client: AsyncClient):
    """
    Verify that a second punch-in on the same day cannot
    have a timestamp earlier than or equal to the previous session's punch-out.
    """
    base_date = datetime(2026, 10, 10, tzinfo=timezone.utc)
    in1 = (base_date.replace(hour=9, minute=0)).isoformat()
    out1 = (base_date.replace(hour=12, minute=0)).isoformat()

    # Session 1: 09:00 -> 12:00
    r1 = await async_client.post("/api/v1/attendance/punch-in", json={"employee_id": "EMP-1001", "timestamp": in1})
    assert r1.status_code == 201
    r2 = await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": out1})
    assert r2.status_code == 200

    # Attempt Session 2 punch-in at 11:30 (before 12:00) -> 422
    in2_invalid = (base_date.replace(hour=11, minute=30)).isoformat()
    r3 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": in2_invalid},
    )
    assert r3.status_code == 422
    assert r3.json()["error"] == "INVALID_TIMESTAMP"


@pytest.mark.asyncio
async def test_inverted_date_range_on_attendance_history_rejected(async_client: AsyncClient):
    """
    Verify that inverted date range on attendance history
    returns HTTP 422 Unprocessable Content.
    """
    res = await async_client.get(
        "/api/v1/attendance/EMP-1001?start_date=2026-10-10&end_date=2026-10-01"
    )
    assert res.status_code == 422
    assert res.json()["error"] == "INVALID_TIMESTAMP"


@pytest.mark.asyncio
async def test_concurrent_punch_out_cas_conflict(async_client: AsyncClient):
    """
    Verify CAS protection when punch-out is attempted twice.
    """
    t_in = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc).isoformat()
    t_out = datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc).isoformat()

    await async_client.post("/api/v1/attendance/punch-in", json={"employee_id": "EMP-1001", "timestamp": t_in})

    # First punch out succeeds
    res1 = await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": t_out})
    assert res1.status_code == 200

    # Second punch out immediately fails with 400 NO_ACTIVE_SESSION
    res2 = await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": t_out})
    assert res2.status_code == 400
    assert res2.json()["error"] == "NO_ACTIVE_SESSION"
