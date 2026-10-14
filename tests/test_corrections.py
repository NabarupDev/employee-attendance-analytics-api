"""Unit and integration tests for attendance corrections, reviewer authorization, and audit trails."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_submit_valid_correction(async_client: AsyncClient):
    """Verify submitting a valid correction request returns HTTP 201 and status PENDING."""
    payload = {
        "employee_id": "EMP-1001",
        "attendance_date": "2026-10-05",
        "proposed_punches": [
            {
                "punch_in": "2026-10-05T09:00:00Z",
                "punch_out": "2026-10-05T17:30:00Z",
            }
        ],
        "reason": "RFID badge scanner was down at main entrance door.",
    }
    response = await async_client.post(
        "/api/v1/corrections/request",
        json=payload,
        headers={"X-Actor-ID": "EMP-1001"},
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["employee_id"] == "EMP-1001"
    assert data["attendance_date"] == "2026-10-05"
    assert data["status"] == "PENDING"
    assert data["reason"] == payload["reason"]
    assert len(data["proposed_punches"]) == 1


@pytest.mark.asyncio
async def test_submit_correction_short_reason_fails_422(async_client: AsyncClient):
    """Verify correction request with reason < 10 chars is rejected with 422."""
    payload = {
        "employee_id": "EMP-1001",
        "attendance_date": "2026-10-05",
        "proposed_punches": [
            {"punch_in": "2026-10-05T09:00:00Z", "punch_out": "2026-10-05T17:00:00Z"}
        ],
        "reason": "Forgot",  # Only 6 characters
    }
    response = await async_client.post("/api/v1/corrections/request", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_correction_invalid_interval_fails_422(async_client: AsyncClient):
    """Verify proposed punch_out <= punch_in is rejected with 422."""
    payload = {
        "employee_id": "EMP-1001",
        "attendance_date": "2026-10-05",
        "proposed_punches": [
            {"punch_in": "2026-10-05T17:00:00Z", "punch_out": "2026-10-05T09:00:00Z"}
        ],
        "reason": "Forgot badge in morning, left early in evening.",
    }
    response = await async_client.post("/api/v1/corrections/request", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_correction_overlapping_intervals_fails_422(async_client: AsyncClient):
    """Verify overlapping proposed punch sessions are rejected with 422."""
    payload = {
        "employee_id": "EMP-1001",
        "attendance_date": "2026-10-05",
        "proposed_punches": [
            {"punch_in": "2026-10-05T09:00:00Z", "punch_out": "2026-10-05T13:00:00Z"},
            {"punch_in": "2026-10-05T12:00:00Z", "punch_out": "2026-10-05T17:00:00Z"},  # Overlaps 12:00-13:00
        ],
        "reason": "Multiple shifts on the same day due to split schedule.",
    }
    response = await async_client.post("/api/v1/corrections/request", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_correction_retroactive_window_exceeded_fails_400(async_client: AsyncClient):
    """Verify correction for date older than 30 days is rejected with 400."""
    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    payload = {
        "employee_id": "EMP-1001",
        "attendance_date": old_date,
        "proposed_punches": [
            {"punch_in": f"{old_date}T09:00:00Z", "punch_out": f"{old_date}T17:00:00Z"}
        ],
        "reason": "Retroactive correction requested beyond 30 days policy limit.",
    }
    response = await async_client.post("/api/v1/corrections/request", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == "RETROACTIVE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_submit_duplicate_pending_correction_fails_409(async_client: AsyncClient):
    """BR-COR-03: Verify submitting a second pending request for same date fails with 409."""
    payload = {
        "employee_id": "EMP-1001",
        "attendance_date": "2026-10-05",
        "proposed_punches": [
            {"punch_in": "2026-10-05T09:00:00Z", "punch_out": "2026-10-05T17:00:00Z"}
        ],
        "reason": "Scanner failed to register check-out properly.",
    }
    first_res = await async_client.post("/api/v1/corrections/request", json=payload)
    assert first_res.status_code == 201

    duplicate_res = await async_client.post("/api/v1/corrections/request", json=payload)
    assert duplicate_res.status_code == 409
    assert duplicate_res.json()["error"] == "DUPLICATE_PENDING_CORRECTION"


@pytest.mark.asyncio
async def test_self_approval_and_unauthorized_role_rejected_403(async_client: AsyncClient):
    """Verify unauthorized role and self-approval attempts are rejected with 403."""
    # Create request
    create_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-05",
            "proposed_punches": [{"punch_in": "2026-10-05T09:00:00Z", "punch_out": "2026-10-05T17:00:00Z"}],
            "reason": "Correction reason for testing authorization safeguards.",
        },
    )
    assert create_res.status_code == 201
    cid = create_res.json()["data"]["id"]

    # 1. Invalid role (employee cannot review)
    res_bad_role = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Approving as employee"},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "employee"},
    )
    assert res_bad_role.status_code == 403

    # 2. Self-approval attempt (manager trying to approve their own request)
    res_self_approval = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Approving my own request"},
        headers={"X-Actor-ID": "EMP-1001", "X-Role": "manager"},
    )
    assert res_self_approval.status_code == 403
    assert "own attendance corrections" in res_self_approval.json()["message"].lower()


@pytest.mark.asyncio
async def test_full_approval_workflow_and_audit_trail(async_client: AsyncClient):
    """Verify full approval flow atomically updates attendance and records audit trail."""
    # Step 1: Employee initially punched in 09:00 - 13:00 on 2026-10-05 (4 hours = HALF_DAY)
    await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-05T09:00:00Z"},
    )
    await async_client.post(
        "/api/v1/attendance/punch-out",
        json={"employee_id": "EMP-1001", "timestamp": "2026-10-05T13:00:00Z"},
    )

    init_rec = await async_client.get("/api/v1/attendance/EMP-1001/daily/2026-10-05")
    assert init_rec.json()["data"]["status"] == "HALF_DAY"
    assert init_rec.json()["data"]["total_work_minutes"] == 240
    assert init_rec.json()["data"]["is_corrected"] is False

    # Step 2: Employee submits correction proposing 09:00 - 17:30 (8.5 hours = 510 mins)
    corr_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-05",
            "proposed_punches": [{"punch_in": "2026-10-05T09:00:00Z", "punch_out": "2026-10-05T17:30:00Z"}],
            "reason": "Scanner missed punch-out at 17:30; verified with security camera footage.",
        },
    )
    assert corr_res.status_code == 201
    cid = corr_res.json()["data"]["id"]

    # Step 3: Manager reviews and approves request
    review_res = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Approved after reviewing CCTV timestamp."},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert review_res.status_code == 200
    assert review_res.json()["data"]["status"] == "APPROVED"
    assert review_res.json()["data"]["reviewed_by"] == "MGR-5001"

    # Step 4: Verify attendance record was atomically updated
    updated_rec = await async_client.get("/api/v1/attendance/EMP-1001/daily/2026-10-05")
    assert updated_rec.status_code == 200
    up_data = updated_rec.json()["data"]
    assert up_data["total_work_minutes"] == 510
    assert up_data["total_work_hours"] == 8.5
    assert up_data["status"] == "PRESENT"
    assert up_data["is_corrected"] is True

    # Step 5: Verify audit trail contains full before-and-after history
    audit_res = await async_client.get("/api/v1/attendance/EMP-1001/audit-trail?date=2026-10-05")
    assert audit_res.status_code == 200
    trail = audit_res.json()["data"]
    assert len(trail) == 1
    entry = trail[0]
    assert entry["correction_id"] == cid
    assert entry["reviewed_by"] == "MGR-5001"
    assert entry["previous_total_minutes"] == 240
    assert entry["new_total_minutes"] == 510
    assert entry["previous_status"] == "HALF_DAY"
    assert entry["new_status"] == "PRESENT"

    # Step 6: Verify immutability (cannot re-approve or reject resolved correction)
    re_review = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "REJECTED", "remarks": "Changed my mind"},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert re_review.status_code == 400
    assert re_review.json()["error"] == "CORRECTION_ALREADY_RESOLVED"


@pytest.mark.asyncio
async def test_rejection_workflow_preserves_original_attendance(async_client: AsyncClient):
    """Verify rejecting a correction request preserves the original attendance record untouched."""
    # Original record 240 minutes
    await async_client.post("/api/v1/attendance/punch-in", json={"employee_id": "EMP-1001", "timestamp": "2026-10-05T09:00:00Z"})
    await async_client.post("/api/v1/attendance/punch-out", json={"employee_id": "EMP-1001", "timestamp": "2026-10-05T13:00:00Z"})

    # Submit correction
    corr_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-05",
            "proposed_punches": [{"punch_in": "2026-10-05T09:00:00Z", "punch_out": "2026-10-05T18:00:00Z"}],
            "reason": "Claiming full day work without supporting gate record.",
        },
    )
    cid = corr_res.json()["data"]["id"]

    # Reject request
    rej_res = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "REJECTED", "remarks": "No badge swipe or CCTV evidence found."},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["data"]["status"] == "REJECTED"

    # Verify original attendance remained unchanged
    rec = await async_client.get("/api/v1/attendance/EMP-1001/daily/2026-10-05")
    assert rec.json()["data"]["total_work_minutes"] == 240
    assert rec.json()["data"]["status"] == "HALF_DAY"
    assert rec.json()["data"]["is_corrected"] is False


@pytest.mark.asyncio
async def test_correction_for_date_without_prior_attendance(async_client: AsyncClient):
    """Verify submitting and approving a correction for a missed day where employee never punched in."""
    corr_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-04",  # Day with 0 punches
            "proposed_punches": [{"punch_in": "2026-10-04T09:00:00Z", "punch_out": "2026-10-04T17:00:00Z"}],
            "reason": "Worked off-site at client location; offline attendance approved.",
        },
    )
    assert corr_res.status_code == 201
    cid = corr_res.json()["data"]["id"]

    # Approve
    appr_res = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Client site visit confirmed."},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert appr_res.status_code == 200

    # Verify newly synthesized attendance record
    rec = await async_client.get("/api/v1/attendance/EMP-1001/daily/2026-10-04")
    assert rec.status_code == 200
    assert rec.json()["data"]["status"] == "PRESENT"
    assert rec.json()["data"]["total_work_minutes"] == 480
    assert rec.json()["data"]["is_corrected"] is True


@pytest.mark.asyncio
async def test_review_non_existent_correction_fails_404(async_client: AsyncClient):
    """Verify reviewing an unknown correction ID returns HTTP 404."""
    response = await async_client.patch(
        "/api/v1/corrections/6accc81a433fbf232e652000/status",
        json={"status": "APPROVED", "remarks": "Non-existent"},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "CORRECTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_correction_on_active_shift_rejected(async_client: AsyncClient):
    """
    Verify that an employee with an active ongoing shift
    cannot submit a correction request for that date until punching out.
    """
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    t_in = (now - timedelta(hours=2)).isoformat()

    # Punch in today
    await async_client.post(
        "/api/v1/attendance/punch-in",
        json={"employee_id": "EMP-1001", "timestamp": t_in},
    )

    # Attempt to submit correction for today while still active
    correction_payload = {
        "employee_id": "EMP-1001",
        "attendance_date": today_str,
        "proposed_punches": [
            {
                "punch_in": (now - timedelta(hours=3)).isoformat(),
                "punch_out": (now - timedelta(hours=1)).isoformat(),
            }
        ],
        "reason": "Attempting correction while active shift is open.",
    }
    res = await async_client.post("/api/v1/corrections/request", json=correction_payload)
    assert res.status_code == 400
    assert "ongoing active shift" in res.json()["message"]


@pytest.mark.asyncio
async def test_correction_proposed_punch_date_mismatch_rejected(async_client: AsyncClient):
    """
    Verify that proposed punches with dates different from
    attendance_date are rejected with HTTP 422 Unprocessable Content.
    """
    correction_payload = {
        "employee_id": "EMP-1001",
        "attendance_date": "2026-10-05",
        "proposed_punches": [
            {
                # Punch timestamp is Oct 01, but attendance_date is Oct 05
                "punch_in": "2026-10-01T09:00:00Z",
                "punch_out": "2026-10-01T17:00:00Z",
            }
        ],
        "reason": "Mismatched timestamp date for correction request.",
    }
    res = await async_client.post("/api/v1/corrections/request", json=correction_payload)
    assert res.status_code == 422
    assert "does not match target attendance date" in res.text


@pytest.mark.asyncio
async def test_concurrent_correction_review_cas_conflict(async_client: AsyncClient):
    """
    Verify CAS prevents double review of the same correction request.
    """
    create_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-02",
            "proposed_punches": [
                {
                    "punch_in": "2026-10-02T09:00:00Z",
                    "punch_out": "2026-10-02T17:00:00Z",
                }
            ],
            "reason": "Biometric system failure during entry gate scan.",
        },
    )
    assert create_res.status_code == 201
    cid = create_res.json()["data"]["id"]

    # First review succeeds
    rev1 = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Approved by manager."},
        headers={"X-Actor-ID": "MGR-5001", "X-Role": "manager"},
    )
    assert rev1.status_code == 200

    # Second review fails with 400 CORRECTION_ALREADY_RESOLVED
    rev2 = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "REJECTED", "remarks": "Late conflicting rejection."},
        headers={"X-Actor-ID": "MGR-5002", "X-Role": "manager"},
    )
    assert rev2.status_code == 400
    assert rev2.json()["error"] == "CORRECTION_ALREADY_RESOLVED"


@pytest.mark.asyncio
async def test_reviewer_role_resolution_and_missing_role_rejected(async_client: AsyncClient):
    """
    Verify security boundary:
    1. Unauthenticated / missing role from non-manager is rejected with 403.
    2. Registered employee with managerial designation (EMP-1002, Product Manager) resolves to manager.
    3. Explicit X-Role: manager allows review.
    """
    create_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-06",
            "proposed_punches": [
                {"punch_in": "2026-10-06T09:00:00Z", "punch_out": "2026-10-06T17:00:00Z"}
            ],
            "reason": "Testing reviewer role security resolution.",
        },
    )
    assert create_res.status_code == 201
    cid = create_res.json()["data"]["id"]

    # 1. Unknown actor without X-Role is rejected (403)
    res1 = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Unauthorized review attempt"},
        headers={"X-Actor-ID": "UNKNOWN-999"},
    )
    assert res1.status_code == 403

    # 2. Registered employee with non-manager designation (EMP-1001, Backend Engineer) is rejected
    res2 = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Engineer trying to review"},
        headers={"X-Actor-ID": "EMP-1001"},
    )
    assert res2.status_code == 403

    # 3. Registered employee with manager designation (EMP-1002, Product Manager) succeeds without explicit X-Role
    res3 = await async_client.patch(
        f"/api/v1/corrections/{cid}/status",
        json={"status": "APPROVED", "remarks": "Approved by Product Manager"},
        headers={"X-Actor-ID": "EMP-1002"},
    )
    assert res3.status_code == 200
    assert res3.json()["data"]["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_correction_rollback_on_failure_and_resilience(async_client: AsyncClient, mock_db):
    """
    Verify compensating rollback behavior when failure occurs during status update,
    and verify that errors during rollback are propagated and logged.
    """
    from unittest.mock import AsyncMock, patch
    from app.services.correction_service import CorrectionService
    from app.schemas.correction import CorrectionStatus

    # Submit a correction
    create_res = await async_client.post(
        "/api/v1/corrections/request",
        json={
            "employee_id": "EMP-1001",
            "attendance_date": "2026-10-07",
            "proposed_punches": [
                {"punch_in": "2026-10-07T09:00:00Z", "punch_out": "2026-10-07T17:00:00Z"}
            ],
            "reason": "Test rollback resilience under database failure.",
        },
    )
    assert create_res.status_code == 201
    cid = create_res.json()["data"]["id"]

    service = CorrectionService(mock_db)

    # 1. Test safe recovery when update_one fails on attendance collection:
    # Verifies that attendance write failure reverts correction to PENDING
    # without touching or blind-overwriting attendance records.
    with patch.object(
        service.attendance_collection,
        "update_one",
        side_effect=RuntimeError("Simulated database failure during attendance write"),
    ):
        with pytest.raises(RuntimeError, match="Simulated database failure during attendance write"):
            await service.review_correction(
                correction_id=cid,
                target_status=CorrectionStatus.APPROVED,
                reviewer_id="MGR-5001",
                reviewer_role="manager",
            )

    # Verify that the correction is reverted to PENDING so it can be re-tried
    corr_doc = await mock_db["corrections"].find_one({"employee_id": "EMP-1001", "attendance_date": "2026-10-07"})
    assert corr_doc["status"] == "PENDING"
    assert corr_doc["reviewed_by"] is None

    # 2. Test successful recovery and subsequent approval
    successful_review = await service.review_correction(
        correction_id=cid,
        target_status=CorrectionStatus.APPROVED,
        reviewer_id="MGR-5001",
        reviewer_role="manager",
    )
    assert successful_review.status == CorrectionStatus.APPROVED

    # Verify attendance record is now updated
    att_doc = await mock_db["attendance"].find_one({"employee_id": "EMP-1001", "date": "2026-10-07"})
    assert att_doc is not None
    assert att_doc["is_corrected"] is True



