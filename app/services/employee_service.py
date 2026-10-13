"""Service layer for employee lookups and management."""

import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import EmployeeNotFoundError
from app.schemas.employee import EmployeeCreateRequest, EmployeeResponse

logger = logging.getLogger(__name__)


class EmployeeService:
    """Handles employee operations and persistence."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.db = db
        self.collection = db["employees"]

    async def get_employee(self, employee_id: str) -> Optional[dict]:
        """Fetch employee document by employee_id or emp_code."""
        return await self.collection.find_one({
            "$or": [{"employee_id": employee_id}, {"emp_code": employee_id}]
        })

    async def ensure_employee_exists(self, employee_id: str) -> dict:
        """Verify employee exists in database, raising EmployeeNotFoundError otherwise."""
        employee = await self.get_employee(employee_id)
        if not employee:
            logger.warning("Employee lookup failed for ID: %s", employee_id)
            raise EmployeeNotFoundError(employee_id)
        return employee

    async def create_employee(self, data: EmployeeCreateRequest) -> EmployeeResponse:
        """Register or update an employee record."""
        payload = data.model_dump()
        payload["emp_code"] = data.employee_id
        existing = await self.get_employee(data.employee_id)
        if existing:
            await self.collection.update_one(
                {"employee_id": data.employee_id},
                {"$set": payload},
            )
        else:
            await self.collection.insert_one(payload)

        created = await self.ensure_employee_exists(data.employee_id)
        return EmployeeResponse(
            employee_id=created["employee_id"],
            name=created["name"],
            email=created["email"],
            department=created["department"],
            designation=created.get("designation", "Employee"),
            shift_start=created.get("shift_start", "09:00"),
            shift_end=created.get("shift_end", "18:00"),
            joined_on=created.get("joined_on"),
            is_active=created.get("is_active", True),
        )

    async def list_employees(
        self,
        department: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[EmployeeResponse]:
        """List employees with optional filtering and pagination."""
        query = {}
        if department:
            query["department"] = department
        if is_active is not None:
            query["is_active"] = is_active
        cursor = self.collection.find(query).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [
            EmployeeResponse(
                employee_id=doc["employee_id"],
                name=doc["name"],
                email=doc["email"],
                department=doc["department"],
                designation=doc.get("designation", "Employee"),
                shift_start=doc.get("shift_start", "09:00"),
                shift_end=doc.get("shift_end", "18:00"),
                joined_on=doc.get("joined_on"),
                is_active=doc.get("is_active", True),
            )
            for doc in docs
        ]
