"""Service layer implementing attendance operations, business rules, and calculations."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.exceptions import (
    ActiveSessionExistsError,
    AttendanceRecordNotFoundError,
    BusinessRuleViolationError,
    InvalidTimestampError,
    NoActiveSessionError,
)
from app.schemas.attendance import (
    AttendanceRecordResponse,
    AttendanceStatus,
    PunchSessionResponse,
    RegularizeAttendanceRequest,
)
from app.services.analytics_service import validate_date_range
from app.services.employee_service import EmployeeService

logger = logging.getLogger(__name__)


class AttendanceService:
    """Orchestrates punch-in, punch-out, and daily attendance aggregations."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.db = db
        self.collection = db["attendance"]
        self.employee_service = EmployeeService(db)

    @staticmethod
    def calculate_status(total_work_minutes: int, has_active_session: bool) -> AttendanceStatus:
        """
        Evaluate daily attendance status based on work minutes and active session state.
        
        Rules:
        - Active session in progress: IN_PROGRESS
        - Total duration >= 480 minutes (8.0 hours): PRESENT
        - Total duration >= 240 minutes (4.0 hours) and < 480 minutes: HALF_DAY
        - Total duration < 240 minutes: ABSENT
        """
        if has_active_session:
            return AttendanceStatus.IN_PROGRESS
        if total_work_minutes >= 480:
            return AttendanceStatus.PRESENT
        if total_work_minutes >= 240:
            return AttendanceStatus.HALF_DAY
        return AttendanceStatus.ABSENT

    @staticmethod
    def _doc_to_response(doc: dict) -> AttendanceRecordResponse:
        """Convert a MongoDB attendance document into a Pydantic response model."""
        punches = [
            PunchSessionResponse(
                session_id=p["session_id"],
                punch_in=p["punch_in"],
                punch_out=p.get("punch_out"),
                duration_minutes=p.get("duration_minutes"),
            )
            for p in doc.get("punches", [])
        ]

        total_work_minutes = doc.get("total_work_minutes", 0)
        total_work_hours = round(total_work_minutes / 60.0, 2)

        return AttendanceRecordResponse(
            id=str(doc["_id"]),
            employee_id=doc["employee_id"],
            department=doc.get("department", "General"),
            date=doc["date"],
            punches=punches,
            has_active_session=doc.get("has_active_session", False),
            total_work_minutes=total_work_minutes,
            total_work_hours=total_work_hours,
            status=AttendanceStatus(doc.get("status", AttendanceStatus.ABSENT)),
            is_corrected=doc.get("is_corrected", False),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
        )

    async def punch_in(
        self,
        employee_id: str,
        timestamp: Optional[datetime] = None,
    ) -> AttendanceRecordResponse:
        """
        Record an employee punch-in event.
        
        Business Rules Enforced:
        - Employee must exist in system (BR-Missing-Employee).
        - Timestamps cannot be in the future (BR-04).
        - Cannot punch in if an active session is already open (BR-01).
        """
        employee = await self.employee_service.ensure_employee_exists(employee_id)
        department = employee.get("department", "General")

        now_utc = datetime.now(timezone.utc)
        punch_time = timestamp.astimezone(timezone.utc) if timestamp else now_utc

        if (punch_time - now_utc).total_seconds() > 60:
            raise InvalidTimestampError("Punch-in timestamp cannot be set in the future.")

        # Check if the employee currently has an active open session across any date
        active_session_record = await self.collection.find_one({
            "employee_id": employee_id,
            "has_active_session": True,
        })
        if active_session_record:
            logger.warning(
                "Duplicate punch-in attempt for employee: %s (active session open on %s)",
                employee_id,
                active_session_record.get("date"),
            )
            raise ActiveSessionExistsError(
                "Employee already has an active punch session. Punch out before punching in again."
            )

        date_str = punch_time.strftime("%Y-%m-%d")

        # Check existing attendance record for today
        existing_record = await self.collection.find_one({
            "employee_id": employee_id,
            "date": date_str,
        })

        if existing_record:
            # Enforce chronological ordering: new punch_in must be strictly after previous punch_out
            punches = existing_record.get("punches", [])
            if punches:
                last_punch_out = punches[-1].get("punch_out")
                if last_punch_out is not None:
                    if last_punch_out.tzinfo is None:
                        last_punch_out = last_punch_out.replace(tzinfo=timezone.utc)
                    if punch_time <= last_punch_out:
                        raise InvalidTimestampError(
                            "Punch-in timestamp must be strictly after the previous session's punch-out timestamp."
                        )

        new_session = {
            "session_id": str(uuid.uuid4()),
            "punch_in": punch_time,
            "punch_out": None,
            "duration_minutes": None,
        }

        if existing_record:
            # Append new session to existing record using atomic CAS guard
            update_res = await self.collection.update_one(
                {"_id": existing_record["_id"], "has_active_session": False},
                {
                    "$push": {"punches": new_session},
                    "$set": {
                        "has_active_session": True,
                        "status": AttendanceStatus.IN_PROGRESS.value,
                        "updated_at": punch_time,
                    },
                },
            )
            if update_res.modified_count == 0:
                raise ActiveSessionExistsError(
                    "Employee already has an active punch session. Punch out before punching in again."
                )
            updated_doc = await self.collection.find_one({"_id": existing_record["_id"]})
        else:
            # Create fresh daily attendance record
            new_record = {
                "employee_id": employee_id,
                "department": department,
                "date": date_str,
                "punches": [new_session],
                "has_active_session": True,
                "total_work_minutes": 0,
                "status": AttendanceStatus.IN_PROGRESS.value,
                "is_corrected": False,
                "created_at": punch_time,
                "updated_at": punch_time,
            }
            try:
                res = await self.collection.insert_one(new_record)
                updated_doc = await self.collection.find_one({"_id": res.inserted_id})
            except DuplicateKeyError:
                # Concurrent insert collision on unique index (employee_id, date)
                logger.warning(
                    "Duplicate key collision on punch-in for employee %s on %s",
                    employee_id,
                    date_str,
                )
                raise ActiveSessionExistsError(
                    "Concurrent punch-in request detected or active session already created."
                )

        logger.info("Punch-in recorded successfully for employee: %s on %s", employee_id, date_str)
        return self._doc_to_response(updated_doc)

    async def punch_out(
        self,
        employee_id: str,
        timestamp: Optional[datetime] = None,
    ) -> AttendanceRecordResponse:
        """
        Record an employee punch-out event.
        
        Business Rules Enforced:
        - Employee must exist in system (BR-Missing-Employee).
        - Must have an active open punch-in session (BR-02).
        - Punch-out timestamp must be strictly greater than punch-in timestamp (BR-03).
        - Recalculates total work duration and attendance status (BR-05).
        """
        await self.employee_service.ensure_employee_exists(employee_id)

        now_utc = datetime.now(timezone.utc)
        punch_time = timestamp.astimezone(timezone.utc) if timestamp else now_utc

        if (punch_time - now_utc).total_seconds() > 60:
            raise InvalidTimestampError("Punch-out timestamp cannot be set in the future.")

        # Find active session record for this employee
        record = await self.collection.find_one({
            "employee_id": employee_id,
            "has_active_session": True,
        })

        if not record:
            logger.warning("Punch-out attempted without active session for employee: %s", employee_id)
            raise NoActiveSessionError(
                "No active punch session found for employee. Must punch in before punching out."
            )

        # Locate the open session in punches array
        punches = record.get("punches", [])
        open_session_idx = -1
        for idx, s in enumerate(punches):
            if s.get("punch_out") is None:
                open_session_idx = idx
                break

        if open_session_idx == -1:
            raise NoActiveSessionError("No open punch-in session found to close.")

        open_session = punches[open_session_idx]
        punch_in_time = open_session["punch_in"]

        # Ensure timezone consistency when comparing
        if punch_in_time.tzinfo is None:
            punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

        if punch_time <= punch_in_time:
            logger.warning("Invalid punch-out time %s <= punch-in time %s", punch_time, punch_in_time)
            raise InvalidTimestampError(
                "Punch-out timestamp must be strictly after the punch-in timestamp."
            )

        # Calculate session duration
        session_duration = int(round((punch_time - punch_in_time).total_seconds() / 60))
        open_session["punch_out"] = punch_time
        open_session["duration_minutes"] = session_duration

        # Recalculate daily total work duration
        total_minutes = sum(
            p.get("duration_minutes", 0) or 0
            for p in punches
            if p.get("duration_minutes") is not None
        )

        new_status = self.calculate_status(total_work_minutes=total_minutes, has_active_session=False)

        # Update database atomically using CAS on has_active_session == True
        res = await self.collection.update_one(
            {"_id": record["_id"], "has_active_session": True},
            {
                "$set": {
                    "punches": punches,
                    "has_active_session": False,
                    "total_work_minutes": total_minutes,
                    "status": new_status.value,
                    "updated_at": punch_time,
                }
            },
        )
        if res.modified_count == 0:
            raise NoActiveSessionError(
                "No active punch session found for employee. Must punch in before punching out."
            )

        updated_doc = await self.collection.find_one({"_id": record["_id"]})
        logger.info(
            "Punch-out recorded for employee %s: session=%d mins, daily_total=%d mins, status=%s",
            employee_id,
            session_duration,
            total_minutes,
            new_status.value,
        )
        return self._doc_to_response(updated_doc)

    async def get_attendance(
        self,
        employee_id: str,
        date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[AttendanceRecordResponse]:
        """Fetch attendance history for an employee."""
        await self.employee_service.ensure_employee_exists(employee_id)

        query = {"employee_id": employee_id}
        if date:
            query["date"] = date
        elif start_date and end_date:
            validate_date_range(start_date, end_date)
            query["date"] = {"$gte": start_date, "$lte": end_date}
        elif start_date:
            query["date"] = {"$gte": start_date}
        elif end_date:
            query["date"] = {"$lte": end_date}

        cursor = self.collection.find(query).sort("date", 1)
        records = await cursor.to_list(length=1000)

        return [self._doc_to_response(doc) for doc in records]

    async def get_daily_record(self, employee_id: str, date: str) -> AttendanceRecordResponse:
        """Fetch a specific daily attendance record or raise 404."""
        employee = await self.employee_service.ensure_employee_exists(employee_id)
        canonical_id = employee["employee_id"]
        doc = await self.collection.find_one({"employee_id": canonical_id, "date": date})
        if not doc:
            raise AttendanceRecordNotFoundError(
                f"No attendance record found for employee '{employee_id}' on date '{date}'."
            )
        return self._doc_to_response(doc)

    async def get_all_attendance(
        self,
        employee_id: Optional[str] = None,
        department: Optional[str] = None,
        date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[AttendanceRecordResponse]:
        """Fetch attendance records across the organization with optional filtering."""
        query: Dict[str, Any] = {}
        if employee_id:
            emp = await self.employee_service.get_employee(employee_id)
            canonical_id = emp["employee_id"] if emp else employee_id
            query["employee_id"] = canonical_id
        if department:
            query["department"] = department
        if date:
            query["date"] = date
        elif start_date and end_date:
            validate_date_range(start_date, end_date)
            query["date"] = {"$gte": start_date, "$lte": end_date}
        elif start_date:
            query["date"] = {"$gte": start_date}
        elif end_date:
            query["date"] = {"$lte": end_date}
        if status:
            query["status"] = status.upper()

        cursor = self.collection.find(query).sort("date", -1).skip(skip).limit(limit)
        records = await cursor.to_list(length=limit)
        return [self._doc_to_response(doc) for doc in records]

    async def regularize_attendance(
        self,
        employee_id: str,
        date: str,
        request: RegularizeAttendanceRequest,
        actor_id: Optional[str] = None,
        role: Optional[str] = None,
    ) -> AttendanceRecordResponse:
        """
        Directly regularize an employee's attendance record for a specific date,
        updating punches, status, and recording an immutable audit entry.

        Enforces:
        - Authorizing actor identity (X-Actor-ID) is mandatory.
        - Authorizing actor must exist in registered employee directory and be active.
        - Authorizing actor must hold a managerial designation in database.
        - Self-regularization is strictly forbidden (cannot regularize own attendance).
        """
        from app.core.exceptions import UnauthorizedReviewerError

        if not actor_id:
            raise UnauthorizedReviewerError(
                "Authorizing actor identity (X-Actor-ID) is required for attendance regularization."
            )

        employee = await self.employee_service.ensure_employee_exists(employee_id)
        canonical_id = employee["employee_id"]

        # Self-regularization prevention
        if actor_id == canonical_id:
            raise UnauthorizedReviewerError(
                "Employees are strictly prohibited from directly regularizing their own attendance records."
            )

        # Verify authorizing actor in registered employee directory
        actor_emp = await self.employee_service.get_employee(actor_id)
        if not actor_emp:
            raise UnauthorizedReviewerError(
                f"Authorizing actor '{actor_id}' not found in registered employee directory."
            )
        if not actor_emp.get("is_active", True):
            raise UnauthorizedReviewerError(
                f"Authorizing actor '{actor_id}' is inactive and cannot regularize attendance."
            )

        # Cross-check managerial privilege against database designation
        designation = (actor_emp.get("designation") or "").lower()
        is_managerial = any(kw in designation for kw in ("manager", "admin", "lead", "director", "head", "vp"))
        if not is_managerial:
            raise UnauthorizedReviewerError(
                f"Actor '{actor_id}' holds non-managerial designation '{actor_emp.get('designation')}' "
                "and is not authorized to regularize attendance records."
            )

        department = employee.get("department", "General")
        now_utc = datetime.now(timezone.utc)


        new_punches = []
        if request.punches:
            for p in request.punches:
                p_in = p.punch_in
                p_out = p.punch_out
                if p_out <= p_in:
                    raise InvalidTimestampError("punch_out must be strictly after punch_in.")
                dur = int(round((p_out - p_in).total_seconds() / 60))
                new_punches.append({
                    "session_id": str(uuid.uuid4()),
                    "punch_in": p_in,
                    "punch_out": p_out,
                    "duration_minutes": dur,
                })
        elif request.punch_in and request.punch_out:
            p_in = request.punch_in
            p_out = request.punch_out
            if p_out <= p_in:
                raise InvalidTimestampError("punch_out must be strictly after punch_in.")
            dur = int(round((p_out - p_in).total_seconds() / 60))
            new_punches.append({
                "session_id": str(uuid.uuid4()),
                "punch_in": p_in,
                "punch_out": p_out,
                "duration_minutes": dur,
            })
        else:
            raise BusinessRuleViolationError("Either punch_in & punch_out or punches list must be provided.")

        new_total_minutes = sum(p["duration_minutes"] for p in new_punches)
        new_status = self.calculate_status(total_work_minutes=new_total_minutes, has_active_session=False)

        existing_record = await self.collection.find_one({"employee_id": canonical_id, "date": date})
        prev_punches = existing_record.get("punches", []) if existing_record else []
        prev_minutes = existing_record.get("total_work_minutes", 0) if existing_record else 0
        prev_status = (
            existing_record.get("status", AttendanceStatus.ABSENT.value)
            if existing_record
            else AttendanceStatus.ABSENT.value
        )

        audit_entry = {
            "regularized_by": actor_id or "system",
            "reason": request.reason,
            "applied_at": now_utc,
            "previous_punches": prev_punches,
            "new_punches": new_punches,
            "previous_total_minutes": prev_minutes,
            "new_total_minutes": new_total_minutes,
            "previous_status": prev_status,
            "new_status": new_status.value,
        }

        await self.collection.update_one(
            {"employee_id": canonical_id, "date": date},
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
                    "employee_id": canonical_id,
                    "department": department,
                    "date": date,
                    "created_at": now_utc,
                },
            },
            upsert=True,
        )

        updated = await self.collection.find_one({"employee_id": canonical_id, "date": date})
        logger.info(
            "Attendance regularized for employee: %s on %s by %s: total=%dm status=%s",
            canonical_id,
            date,
            actor_id or "system",
            new_total_minutes,
            new_status.value,
        )
        return self._doc_to_response(updated)

