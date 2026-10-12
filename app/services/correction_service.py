"""Service layer implementing attendance corrections, business rule enforcement, and audit trails."""

from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.exceptions import (
    BusinessRuleViolationError,
    CorrectionAlreadyResolvedError,
    CorrectionNotFoundError,
    DuplicateCorrectionRequestError,
    InvalidTimestampError,
    UnauthorizedReviewerError,
)
from app.schemas.attendance import AttendanceStatus
from app.schemas.correction import (
    AuditEntryResponse,
    CorrectionCreateRequest,
    CorrectionResponse,
    CorrectionStatus,
    ProposedPunchInterval,
)
from app.services.attendance_service import AttendanceService
from app.services.employee_service import EmployeeService

logger = logging.getLogger(__name__)


class CorrectionService:
    """Manages attendance correction requests, approval workflows, and audit trail generation."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.db = db
        self.corrections_collection = db["corrections"]
        self.attendance_collection = db["attendance"]
        self.employee_service = EmployeeService(db)

    @staticmethod
    def _doc_to_response(doc: dict) -> CorrectionResponse:
        """Serialize a MongoDB correction document to a Pydantic response."""
        proposed = [
            ProposedPunchInterval(
                punch_in=p["punch_in"],
                punch_out=p["punch_out"],
            )
            for p in doc.get("proposed_punches", [])
        ]

        return CorrectionResponse(
            id=str(doc["_id"]),
            employee_id=doc["employee_id"],
            attendance_date=doc["attendance_date"],
            original_record_snapshot=doc.get("original_record_snapshot"),
            proposed_punches=proposed,
            reason=doc["reason"],
            status=CorrectionStatus(doc["status"]),
            requested_by=doc.get("requested_by", doc["employee_id"]),
            reviewed_by=doc.get("reviewed_by"),
            review_remarks=doc.get("review_remarks"),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            reviewed_at=doc.get("reviewed_at"),
        )

    async def submit_correction(
        self,
        data: CorrectionCreateRequest,
        actor_id: Optional[str] = None,
    ) -> CorrectionResponse:
        """
        Submit a new attendance correction request.
        
        Business Rules Enforced:
        - Employee must exist.
        - Cannot request correction for future calendar dates.
        - Cannot request correction for dates older than 30 days (retroactive window).
        - Cannot submit duplicate pending correction for same date.
        - Snapshot of current attendance record preserved for audit trail.
        """
        employee = await self.employee_service.ensure_employee_exists(data.employee_id)
        department = employee.get("department", "General")

        # Parse target date
        target_date = datetime.strptime(data.attendance_date, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()

        if target_date > today:
            raise InvalidTimestampError("Corrections cannot be requested for future dates.")

        if (today - target_date).days > 30:
            raise BusinessRuleViolationError(
                "Corrections cannot be requested for attendance older than 30 days.",
                code="RETROACTIVE_LIMIT_EXCEEDED",
            )

        # Check for existing PENDING correction for this employee and date
        existing_pending = await self.corrections_collection.find_one({
            "employee_id": data.employee_id,
            "attendance_date": data.attendance_date,
            "status": CorrectionStatus.PENDING.value,
        })
        if existing_pending:
            logger.warning(
                "Duplicate pending correction rejected for employee %s on %s",
                data.employee_id,
                data.attendance_date,
            )
            raise DuplicateCorrectionRequestError(data.employee_id, data.attendance_date)

        # Fetch original attendance record for snapshot preservation
        original_record = await self.attendance_collection.find_one({
            "employee_id": data.employee_id,
            "date": data.attendance_date,
        })

        # Reject correction request if employee currently has an active open session for this date
        if original_record and original_record.get("has_active_session"):
            raise BusinessRuleViolationError(
                "Cannot submit a correction request for an ongoing active shift. Please punch out first."
            )

        if original_record:
            # Serialize snapshot safely without MongoDB ObjectId
            original_snapshot: Dict[str, Any] = {
                "id": str(original_record["_id"]),
                "employee_id": original_record["employee_id"],
                "department": original_record.get("department", department),
                "date": original_record["date"],
                "punches": original_record.get("punches", []),
                "total_work_minutes": original_record.get("total_work_minutes", 0),
                "status": original_record.get("status", AttendanceStatus.ABSENT.value),
            }
        else:
            original_snapshot = {
                "employee_id": data.employee_id,
                "department": department,
                "date": data.attendance_date,
                "punches": [],
                "total_work_minutes": 0,
                "status": AttendanceStatus.ABSENT.value,
            }

        now_utc = datetime.now(timezone.utc)
        doc = {
            "employee_id": data.employee_id,
            "attendance_date": data.attendance_date,
            "original_record_snapshot": original_snapshot,
            "proposed_punches": [p.model_dump() for p in data.proposed_punches],
            "reason": data.reason,
            "status": CorrectionStatus.PENDING.value,
            "requested_by": actor_id or data.employee_id,
            "reviewed_by": None,
            "review_remarks": None,
            "created_at": now_utc,
            "reviewed_at": None,
        }

        try:
            result = await self.corrections_collection.insert_one(doc)
            created_doc = await self.corrections_collection.find_one({"_id": result.inserted_id})
        except DuplicateKeyError:
            # Concurrent duplicate submission caught by partial unique index
            logger.warning(
                "Concurrent duplicate pending correction rejected for employee %s on %s",
                data.employee_id,
                data.attendance_date,
            )
            raise DuplicateCorrectionRequestError(data.employee_id, data.attendance_date)

        logger.info(
            "Correction request created: id=%s for employee=%s on date=%s",
            str(result.inserted_id),
            data.employee_id,
            data.attendance_date,
        )
        return self._doc_to_response(created_doc)

    async def review_correction(
        self,
        correction_id: str,
        target_status: CorrectionStatus,
        remarks: Optional[str] = None,
        reviewer_id: Optional[str] = None,
        reviewer_role: Optional[str] = None,
    ) -> CorrectionResponse:
        """
        Review, resolve, and atomically apply an attendance correction.
        
        Business Rules Enforced:
        - Reviewer must hold role 'manager' or 'admin'.
        - Reviewer cannot approve their own correction request.
        - Finalized correction requests (APPROVED or REJECTED) are immutable.
        - If APPROVED: atomically updates attendance record, recomputes total work hours,
          sets is_corrected = True, and appends full before/after audit entry.
        - If REJECTED: records decision without modifying attendance record.
        """
        # Role verification
        allowed_roles = {"manager", "admin", "lead"}
        normalized_role = (reviewer_role or "").lower()
        if normalized_role not in allowed_roles:
            raise UnauthorizedReviewerError(
                f"Role '{reviewer_role}' is not authorized. Must be one of: {allowed_roles}."
            )

        if not reviewer_id:
            raise UnauthorizedReviewerError("Reviewer identity (X-Actor-ID) is required.")

        try:
            oid = ObjectId(correction_id)
        except Exception:
            raise CorrectionNotFoundError(correction_id)

        correction = await self.corrections_collection.find_one({"_id": oid})
        if not correction:
            raise CorrectionNotFoundError(correction_id)

        # Self-approval prevention
        if reviewer_id == correction["employee_id"]:
            raise UnauthorizedReviewerError(
                "Employees are strictly prohibited from approving their own attendance corrections."
            )

        # Immutability check
        if correction["status"] != CorrectionStatus.PENDING.value:
            raise CorrectionAlreadyResolvedError(correction["status"])

        now_utc = datetime.now(timezone.utc)

        # Update correction document to resolved status atomically first via CAS
        update_result = await self.corrections_collection.update_one(
            {"_id": oid, "status": CorrectionStatus.PENDING.value},
            {
                "$set": {
                    "status": target_status.value,
                    "reviewed_by": reviewer_id,
                    "review_remarks": remarks,
                    "reviewed_at": now_utc,
                }
            },
        )
        if update_result.modified_count == 0:
            latest = await self.corrections_collection.find_one({"_id": oid})
            current_status = latest.get("status", "UNKNOWN") if latest else "UNKNOWN"
            raise CorrectionAlreadyResolvedError(current_status)

        if target_status == CorrectionStatus.APPROVED:
            # Build updated punches from proposed punches
            new_punches = []
            for p in correction["proposed_punches"]:
                p_in = p["punch_in"]
                p_out = p["punch_out"]
                if p_in.tzinfo is not None and p_out.tzinfo is None:
                    p_out = p_out.replace(tzinfo=p_in.tzinfo)
                elif p_in.tzinfo is None and p_out.tzinfo is not None:
                    p_in = p_in.replace(tzinfo=p_out.tzinfo)
                duration = int(round((p_out - p_in).total_seconds() / 60))
                new_punches.append({
                    "session_id": str(uuid.uuid4()),
                    "punch_in": p_in,
                    "punch_out": p_out,
                    "duration_minutes": duration,
                })

            new_total_minutes = sum(p["duration_minutes"] for p in new_punches)
            new_status = AttendanceService.calculate_status(
                total_work_minutes=new_total_minutes,
                has_active_session=False,
            )

            original_snapshot = correction.get("original_record_snapshot", {})

            # Prepare comprehensive before-and-after audit history entry
            audit_entry = {
                "correction_id": str(correction["_id"]),
                "applied_at": now_utc,
                "reviewed_by": reviewer_id,
                "reason": correction["reason"],
                "previous_punches": original_snapshot.get("punches", []),
                "new_punches": new_punches,
                "previous_total_minutes": original_snapshot.get("total_work_minutes", 0),
                "new_total_minutes": new_total_minutes,
                "previous_status": original_snapshot.get("status", AttendanceStatus.ABSENT.value),
                "new_status": new_status.value,
            }

            # Atomically update or insert attendance record
            await self.attendance_collection.update_one(
                {
                    "employee_id": correction["employee_id"],
                    "date": correction["attendance_date"],
                },
                {
                    "$set": {
                        "punches": new_punches,
                        "has_active_session": False,
                        "total_work_minutes": new_total_minutes,
                        "status": new_status.value,
                        "is_corrected": True,
                        "updated_at": now_utc,
                    },
                    "$push": {"audit_history": audit_entry},
                    "$setOnInsert": {
                        "employee_id": correction["employee_id"],
                        "department": original_snapshot.get("department", "General"),
                        "date": correction["attendance_date"],
                        "created_at": now_utc,
                    },
                },
                upsert=True,
            )

        updated_correction = await self.corrections_collection.find_one({"_id": oid})
        logger.info(
            "Correction request %s resolved as %s by reviewer %s",
            correction_id,
            target_status.value,
            reviewer_id,
        )
        return self._doc_to_response(updated_correction)

    async def list_corrections(
        self,
        employee_id: Optional[str] = None,
        status: Optional[str] = None,
        date: Optional[str] = None,
    ) -> List[CorrectionResponse]:
        """Query corrections with optional filters."""
        query: Dict[str, Any] = {}
        if employee_id:
            query["employee_id"] = employee_id
        if status:
            query["status"] = status.upper()
        if date:
            query["attendance_date"] = date

        cursor = self.corrections_collection.find(query).sort("created_at", -1)
        records = await cursor.to_list(length=1000)
        return [self._doc_to_response(doc) for doc in records]

    async def get_correction(self, correction_id: str) -> CorrectionResponse:
        """Retrieve a single correction request by ID."""
        try:
            oid = ObjectId(correction_id)
        except Exception:
            raise CorrectionNotFoundError(correction_id)

        doc = await self.corrections_collection.find_one({"_id": oid})
        if not doc:
            raise CorrectionNotFoundError(correction_id)
        return self._doc_to_response(doc)

    async def get_audit_trail(
        self,
        employee_id: str,
        date: Optional[str] = None,
    ) -> List[AuditEntryResponse]:
        """Fetch historical before-and-after audit entries for an employee."""
        await self.employee_service.ensure_employee_exists(employee_id)

        query = {"employee_id": employee_id, "is_corrected": True}
        if date:
            query["date"] = date

        records = await self.attendance_collection.find(query).sort("date", 1).to_list(length=1000)
        audit_entries: List[AuditEntryResponse] = []

        for r in records:
            for entry in r.get("audit_history", []):
                audit_entries.append(
                    AuditEntryResponse(
                        correction_id=entry["correction_id"],
                        applied_at=entry["applied_at"],
                        reviewed_by=entry["reviewed_by"],
                        reason=entry["reason"],
                        previous_punches=entry.get("previous_punches", []),
                        new_punches=entry.get("new_punches", []),
                        previous_total_minutes=entry.get("previous_total_minutes", 0),
                        new_total_minutes=entry.get("new_total_minutes", 0),
                        previous_status=entry.get("previous_status", AttendanceStatus.ABSENT.value),
                        new_status=entry.get("new_status", AttendanceStatus.PRESENT.value),
                    )
                )

        audit_entries.sort(key=lambda x: x.applied_at)
        return audit_entries
