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
        """Fetch employee document by ID."""
        return await self.collection.find_one({"employee_id": employee_id})

    async def ensure_employee_exists(self, employee_id: str) -> dict:
        """Verify employee exists in database, raising EmployeeNotFoundError otherwise."""
        employee = await self.get_employee(employee_id)
        if not employee:
            logger.warning("Employee lookup failed for ID: %s", employee_id)
            raise EmployeeNotFoundError(employee_id)
        return employee

    async def create_employee(self, data: EmployeeCreateRequest) -> EmployeeResponse:
        """Register a new employee."""
        existing = await self.get_employee(data.employee_id)
        if existing:
            # Update existing
            await self.collection.update_one(
                {"employee_id": data.employee_id},
                {"$set": data.model_dump()},
            )
        else:
            await self.collection.insert_one(data.model_dump())

        created = await self.ensure_employee_exists(data.employee_id)
        return EmployeeResponse(
            employee_id=created["employee_id"],
            name=created["name"],
            email=created["email"],
            department=created["department"],
            designation=created.get("designation", "Employee"),
            is_active=created.get("is_active", True),
        )
