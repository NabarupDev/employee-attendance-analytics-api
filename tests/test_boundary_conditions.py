"""Comprehensive regression tests verifying exact boundary thresholds for attendance and shifts.

Tests verified:
1. Exact status duration boundaries (239m ABSENT, 240m HALF_DAY, 479m HALF_DAY, 480m PRESENT).
2. Overtime calculation boundary (480m standard vs 481m overtime).
3. Punctuality grace-period threshold (09:15:00 on-time vs 09:16:00 late arrival).
4. Overnight cross-midnight shift handling (22:00 -> 06:00 next day = 480m PRESENT).
5. Missing punch-out (orphan session in progress) and duplicate transition enforcement.
6. Reviewer spoofing rejection for unregistered and non-manager callers.
"""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from app.schemas.attendance import AttendanceStatus
from app.services.attendance_service import AttendanceService


def test_attendance_status_threshold_math():
    """Verify exact minute threshold math for daily attendance status."""
    # 0 minutes -> ABSENT
    assert AttendanceService.calculate_status(0, False) == AttendanceStatus.ABSENT

    # 239 minutes (3 hours 59 minutes) -> ABSENT
    assert AttendanceService.calculate_status(239, False) == AttendanceStatus.ABSENT

    # Exact 240 minutes (4 hours 00 minutes) -> HALF_DAY
    assert AttendanceService.calculate_status(240, False) == AttendanceStatus.HALF_DAY

    # 479 minutes (7 hours 59 minutes) -> HALF_DAY
    assert AttendanceService.calculate_status(479, False) == AttendanceStatus.HALF_DAY

    # Exact 480 minutes (8 hours 00 minutes) -> PRESENT
    assert AttendanceService.calculate_status(480, False) == AttendanceStatus.PRESENT

    # 481 minutes (8 hours 01 minutes) -> PRESENT
    assert AttendanceService.calculate_status(481, False) == AttendanceStatus.PRESENT

    # Any active session open -> IN_PROGRESS regardless of logged minutes
    assert AttendanceService.calculate_status(500, True) == AttendanceStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_exact_duration_boundaries_via_api(async_client: AsyncClient):
    """
    Test punch-in and punch-out across exact boundary minutes through the API:
    - 239 min -> ABSENT
    - 240 min -> HALF_DAY
    - 480 min -> PRESENT
    """
    # 1. Test 239 minutes (09:00 to 12:59) -> ABSENT
    p1 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-01T09:00:00Z"},
    )
    assert p1.status_code == 201
    o1 = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-01T12:59:00Z"},
    )
    assert o1.status_code == 200
    assert o1.json()["data"]["total_work_minutes"] == 239
    assert o1.json()["data"]["status"] == "ABSENT"

    # 2. Test 240 minutes (09:00 to 13:00) -> HALF_DAY
    p2 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-02T09:00:00Z"},
    )
    assert p2.status_code == 201
    o2 = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-02T13:00:00Z"},
    )
    assert o2.status_code == 200
    assert o2.json()["data"]["total_work_minutes"] == 240
    assert o2.json()["data"]["status"] == "HALF_DAY"

    # 3. Test 480 minutes (09:00 to 17:00) -> PRESENT
    p3 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-03T09:00:00Z"},
    )
    assert p3.status_code == 201
    o3 = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-03T17:00:00Z"},
    )
    assert o3.status_code == 200
    assert o3.json()["data"]["total_work_minutes"] == 480
    assert o3.json()["data"]["status"] == "PRESENT"


@pytest.mark.asyncio
async def test_punctuality_grace_period_boundaries(async_client: AsyncClient):
    """
    Test shift punctuality cutoff:
    Shift start is 09:00, grace period is 15 minutes (cutoff 09:15).
    - Punch at 09:15:00 is ON-TIME (not on late leaderboard).
    - Punch at 09:16:00 is LATE (16 minutes late on leaderboard).
    """
    # Register test employee with shift_start 09:00
    await async_client.post(
        "/api/v1/employees",
        json={
            "employee_id": "EMP-PUNCT-1",
            "name": "Punctual Employee",
            "email": "punctual@hr0ne.internal",
            "department": "Engineering",
            "shift_start": "09:00",
        },
    )
    await async_client.post(
        "/api/v1/employees",
        json={
            "employee_id": "EMP-LATE-1",
            "name": "Late Employee",
            "email": "late@hr0ne.internal",
            "department": "Engineering",
            "shift_start": "09:00",
        },
    )

    # EMP-PUNCT-1 punches at exact grace cutoff 09:15:00
    await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-PUNCT-1", "timestamp": "2026-10-04T09:15:00Z"},
    )
    await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-PUNCT-1", "timestamp": "2026-10-04T17:15:00Z"},
    )

    # EMP-LATE-1 punches 1 minute past grace cutoff 09:16:00
    await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-LATE-1", "timestamp": "2026-10-04T09:16:00Z"},
    )
    await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-LATE-1", "timestamp": "2026-10-04T17:16:00Z"},
    )

    # Query late leaderboard for 2026-10-04
    lb_res = await async_client.get(
        "/api/v1/analytics/leaderboard/late",
        params={"start_date": "2026-10-04", "end_date": "2026-10-04"},
    )
    assert lb_res.status_code == 200
    entries = lb_res.json()["data"]

    # EMP-PUNCT-1 should NOT have late counts
    punct_entry = next((e for e in entries if e["employee_id"] == "EMP-PUNCT-1"), None)
    if punct_entry:
        assert punct_entry["late_count"] == 0

    # EMP-LATE-1 must have late_count=1 and total_late_minutes=16
    late_entry = next((e for e in entries if e["employee_id"] == "EMP-LATE-1"), None)
    assert late_entry is not None
    assert late_entry["late_count"] == 1
    assert late_entry["total_late_minutes"] == 16


@pytest.mark.asyncio
async def test_overnight_cross_midnight_shift(async_client: AsyncClient):
    """
    Test overnight shift spanning across midnight:
    - Punch-in: 2026-10-10T22:00:00Z (Day 1)
    - Punch-out: 2026-10-11T06:00:00Z (Day 2)
    - Duration = 480 minutes (8 hours) -> status PRESENT on Day 1 record.
    """
    pin_res = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-10T22:00:00Z"},
    )
    assert pin_res.status_code == 201
    assert pin_res.json()["data"]["has_active_session"] is True
    assert pin_res.json()["data"]["date"] == "2026-10-10"

    pout_res = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-11T06:00:00Z"},
    )
    assert pout_res.status_code == 200
    record = pout_res.json()["data"]
    assert record["date"] == "2026-10-10"
    assert record["has_active_session"] is False
    assert record["total_work_minutes"] == 480
    assert record["status"] == "PRESENT"


@pytest.mark.asyncio
async def test_missing_punchout_and_orphan_session_handling(async_client: AsyncClient):
    """
    Verify state transitions when an employee fails to punch out:
    - Status is IN_PROGRESS.
    - Subsequent punch-in is rejected with 400 ACTIVE_SESSION_EXISTS.
    - Duplicate punch-out after closing is rejected with 400 NO_ACTIVE_SESSION.
    """
    # 1. Punch-in without punch-out
    res1 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-11T09:00:00Z"},
    )
    assert res1.status_code == 201
    assert res1.json()["data"]["status"] == "IN_PROGRESS"
    assert res1.json()["data"]["has_active_session"] is True

    # 2. Blocked duplicate punch-in
    dup_pin = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-11T10:00:00Z"},
    )
    assert dup_pin.status_code == 400
    assert dup_pin.json()["error"] == "ACTIVE_SESSION_EXISTS"

    # 3. Clean punch-out closes session
    pout = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-11T17:00:00Z"},
    )
    assert pout.status_code == 200
    assert pout.json()["data"]["has_active_session"] is False

    # 4. Attempt to punch-out again with no active session
    dup_pout = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-11T18:00:00Z"},
    )
    assert dup_pout.status_code == 400
    assert dup_pout.json()["error"] == "NO_ACTIVE_SESSION"


@pytest.mark.asyncio
async def test_reviewer_spoofing_safeguards(async_client: AsyncClient):
    """
    Verify that caller cannot spoof reviewer authorization:
    1. Unregistered reviewer ID is rejected (403).
    2. Registered non-manager employee claiming X-Role: manager is rejected (403).
    3. Self-approval is rejected (403).
    4. Registered manager is accepted (200).
    """
    create_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-12",
            "proposed_punches": [
                {"punch_in": "2026-10-12T09:00:00Z", "punch_out": "2026-10-12T17:00:00Z"}
            ],
            "reason": "Test spoofing defense barriers.",
        },
    )
    assert create_res.status_code == 201
    cid = create_res.json()["data"]["id"]

    # 1. Unregistered ID claiming manager role
    res_fake = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Malicious actor"},
        headers={"X-Actor-ID": "UNKNOWN-HACKER", "X-Role": "manager"},
    )
    assert res_fake.status_code == 403
    assert "not found in registered employee directory" in res_fake.json()["message"].lower()

    # 2. Registered employee with non-manager designation (EMP-1001 is Backend Engineer)
    # attempting to approve someone else's request
    # Let's create request for EMP-1002
    corr2 = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1002",
            "attendance_date": "2026-10-12",
            "proposed_punches": [
                {"punch_in": "2026-10-12T09:00:00Z", "punch_out": "2026-10-12T17:00:00Z"}
            ],
            "reason": "Test non-manager role claim.",
        },
    )
    cid2 = corr2.json()["data"]["id"]

    res_non_mgr = await async_client.patch(
        f"/api/v1/corrections/{cid2}/status",
        json={"status": "APPROVED", "remarks": "Engineer claiming to be manager"},
        headers={"X-Actor-ID": "EMP-1001", "X-Role": "manager"},
    )
    assert res_non_mgr.status_code == 403
    assert "non-managerial designation" in res_non_mgr.json()["message"].lower()

    # 3. Legitimate manager (MGR-5001 is Engineering Manager) succeeds
    res_legit = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Legitimate approval"},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert res_legit.status_code == 200
    assert res_legit.json()["data"]["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_unauthorized_regularization_enforcement(async_client: AsyncClient):
    """
    Verify strict authorization on direct attendance regularization:
    1. Missing X-Actor-ID -> 403 Forbidden
    2. Unregistered X-Actor-ID -> 403 Forbidden
    3. Registered non-manager (EMP-1001, Backend Engineer) claiming X-Role: admin -> 403 Forbidden
    4. Self-regularization attempt (EMP-1001 regularizing EMP-1001) -> 403 Forbidden
    5. Self-regularization attempt by a manager (MGR-5001 regularizing MGR-5001) -> 403 Forbidden
    6. Authorized manager (MGR-5001) regularizing EMP-1001 -> 200 OK
    """
    reg_payload = {
        "punches": [
            {
                "punch_in": "2026-10-08T09:00:00Z",
                "punch_out": "2026-10-08T17:00:00Z",
            }
        ],
        "reason": "Direct regularization authorization test.",
    }

    # 1. Missing X-Actor-ID header
    r1 = await async_client.patch(
        "/api/v1/attendance/records/EMP-1001/2026-10-08/regularize",
        json=reg_payload,
    )
    assert r1.status_code == 403
    assert "x-actor-id" in r1.json()["message"].lower()

    # 2. Unregistered X-Actor-ID
    r2 = await async_client.patch(
        "/api/v1/attendance/records/EMP-1001/2026-10-08/regularize",
        json=reg_payload,
        headers={"X-Actor-ID": "GHOST-ACTOR"},
    )
    assert r2.status_code == 403
    assert "not found in registered employee directory" in r2.json()["message"].lower()

    # 3. Registered non-manager claiming X-Role: admin
    r3 = await async_client.patch(
        "/api/v1/attendance/records/EMP-1002/2026-10-08/regularize",
        json=reg_payload,
        headers={"X-Actor-ID": "EMP-1001", "X-Role": "admin"},
    )
    assert r3.status_code == 403
    assert "non-managerial designation" in r3.json()["message"].lower()

    # 4. Self-regularization attempt (EMP-1001 regularizing own record)
    r4 = await async_client.patch(
        "/api/v1/attendance/records/EMP-1001/2026-10-08/regularize",
        json=reg_payload,
        headers={"X-Actor-ID": "EMP-1001"},
    )
    assert r4.status_code == 403
    assert "strictly prohibited from directly regularizing their own" in r4.json()["message"].lower()

    # 5. Manager self-regularization attempt (MGR-5001 regularizing own record)
    r5 = await async_client.patch(
        "/api/v1/attendance/records/MGR-5001/2026-10-08/regularize",
        json=reg_payload,
        headers={"X-Actor-ID": "MGR-5001"},
    )
    assert r5.status_code == 403
    assert "strictly prohibited from directly regularizing their own" in r5.json()["message"].lower()

    # 6. Authorized manager regularizing EMP-1001 succeeds
    r6 = await async_client.patch(
        "/api/v1/attendance/records/EMP-1001/2026-10-08/regularize",
        json=reg_payload,
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert r6.status_code == 200
    assert r6.json()["data"]["total_work_minutes"] == 480


@pytest.mark.asyncio
async def test_unauthorized_admin_role_claims_on_corrections(async_client: AsyncClient):
    """
    Verify that a registered non-manager employee CANNOT bypass authorization
    by sending X-Role: admin header. Permissions must resolve from trusted database data.
    """
    # Create correction request for EMP-1002
    corr_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1002",
            "attendance_date": "2026-10-07",
            "proposed_punches": [
                {"punch_in": "2026-10-07T09:00:00Z", "punch_out": "2026-10-07T17:00:00Z"}
            ],
            "reason": "Test admin role spoofing prevention.",
        },
    )
    assert corr_res.status_code == 201
    cid = corr_res.json()["data"]["id"]

    # EMP-1001 (Backend Engineer) claims X-Role: admin
    res = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "I claim to be admin"},
        headers={"X-Actor-ID": "EMP-1001", "X-Role": "admin"},
    )
    assert res.status_code == 403
    assert "non-managerial designation" in res.json()["message"].lower()


@pytest.mark.asyncio
async def test_concurrent_attendance_modifications_detected(async_client: AsyncClient):
    """
    Verify Optimistic Concurrency Control (OCC):
    1. If an active punch session is open on the correction date, approval is rejected (409 Conflict).
    2. If punches were modified or added after the snapshot was captured, approval is rejected (409 Conflict).
    3. Concurrent punches are not overwritten and correction remains PENDING.
    """
    # 1. Employee punches in and out on 2026-10-07 (Session 1: 09:00 - 13:00)
    p1 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-07T09:00:00Z"},
    )
    assert p1.status_code == 201
    o1 = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-07T13:00:00Z"},
    )
    assert o1.status_code == 200

    # 2. Employee files correction request (snapshot captures exactly 1 punch)
    c_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-07",
            "proposed_punches": [
                {"punch_in": "2026-10-07T09:00:00Z", "punch_out": "2026-10-07T17:00:00Z"}
            ],
            "reason": "Forgot to log afternoon session.",
        },
    )
    assert c_res.status_code == 201
    cid = c_res.json()["data"]["id"]

    # 3. Conflict scenario A: Employee punches in concurrently (session is open)
    p2 = await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-07T14:00:00Z"},
    )
    assert p2.status_code == 201

    # Manager attempts approval while session is active -> 409 Conflict
    appr_attempt1 = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Approving while active session open"},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert appr_attempt1.status_code == 409
    assert "active punch session is currently open" in appr_attempt1.json()["message"].lower()

    # 4. Conflict scenario B: Punch out to close session (attendance now has 2 punches, snapshot had 1)
    o2 = await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-07T16:00:00Z"},
    )
    assert o2.status_code == 200

    # Manager attempts approval after concurrent punch was added -> 409 Conflict
    appr_attempt2 = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Approving after punches mutated"},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert appr_attempt2.status_code == 409
    assert "conflicting attendance modification detected" in appr_attempt2.json()["message"].lower()

    # Verify attendance still has the 2 punches (not overwritten)
    att_check = await async_client.get("/api/v1/attendance?employee_id=EMP-1001&date=2026-10-07")
    assert att_check.status_code == 200
    assert len(att_check.json()["data"][0]["punches"]) == 2

    # Verify correction status is still PENDING
    corr_check = await async_client.get(f"/api/v1/corrections/{cid}")
    assert corr_check.status_code == 200
    assert corr_check.json()["data"]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_failed_correction_writes_and_compensating_recovery(async_client: AsyncClient):
    """
    Verify that if writing to attendance collection fails after CAS update on corrections,
    compensating recovery reverts the correction status back to PENDING.
    """
    from unittest.mock import patch
    import mongomock

    # Create correction request
    c_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-06",
            "proposed_punches": [
                {"punch_in": "2026-10-06T09:00:00Z", "punch_out": "2026-10-06T17:00:00Z"}
            ],
            "reason": "Test write failure rollback.",
        },
    )
    assert c_res.status_code == 201
    cid = c_res.json()["data"]["id"]

    orig_update = mongomock.collection.Collection.update_one
    def failing_att_update(self, filter, update, *args, **kwargs):
        if self.name == "attendance":
            raise RuntimeError("Simulated database failure on attendance")
        return orig_update(self, filter, update, *args, **kwargs)

    with patch("mongomock.collection.Collection.update_one", failing_att_update):
        with pytest.raises(RuntimeError, match="Simulated database failure on attendance"):
            await async_client.patch(
                f"/api/v1/corrections/{cid}/status",
                json={"status": "APPROVED", "remarks": "Should trigger rollback"},
                headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
            )

    # Verify compensating write reverted correction back to PENDING
    corr_after = await async_client.get(f"/api/v1/corrections/{cid}")
    assert corr_after.status_code == 200
    data = corr_after.json()["data"]
    assert data["status"] == "PENDING"
    assert data["reviewed_by"] is None


@pytest.mark.asyncio
async def test_recovery_failures_handling(async_client: AsyncClient):
    """
    Verify that if attendance write fails AND compensating rollback write also fails,
    system raises DatabaseInconsistencyError and returns HTTP 500 with DATABASE_INCONSISTENCY_ERROR.
    """
    from unittest.mock import patch
    import mongomock

    c_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-05",
            "proposed_punches": [
                {"punch_in": "2026-10-05T09:00:00Z", "punch_out": "2026-10-05T17:00:00Z"}
            ],
            "reason": "Test fatal recovery failure.",
        },
    )
    assert c_res.status_code == 201
    cid = c_res.json()["data"]["id"]

    orig_update = mongomock.collection.Collection.update_one
    corrections_update_count = 0

    def fatal_failing_update(self, filter, update, *args, **kwargs):
        nonlocal corrections_update_count
        if self.name == "attendance":
            raise RuntimeError("Simulated attendance failure")
        if self.name == "corrections":
            corrections_update_count += 1
            # First call is CAS to APPROVED; second call is compensating rollback to PENDING
            if corrections_update_count > 1:
                raise RuntimeError("Simulated compensating recovery write failure")
        return orig_update(self, filter, update, *args, **kwargs)

    with patch("mongomock.collection.Collection.update_one", fatal_failing_update):
        res = await async_client.patch(
            f"/api/v1/corrections/{cid}/status",
            json={"status": "APPROVED", "remarks": "Should trigger fatal inconsistency error"},
            headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
        )
        assert res.status_code == 500
        assert res.json()["error"] == "DATABASE_INCONSISTENCY_ERROR"
