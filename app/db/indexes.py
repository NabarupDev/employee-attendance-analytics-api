"""MongoDB index definitions and automated initialization."""

import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


async def init_db_indexes(database: Optional[AsyncIOMotorDatabase]) -> None:
    """
    Ensure all application indexes are created on MongoDB collections.
    
    Safe to execute multiple times (idempotent).
    """
    if database is None:
        logger.warning("Database instance is None. Skipping index initialization.")
        return

    try:
        # 1. Attendance Collection Indexes
        attendance_indexes = [
            IndexModel(
                [("employee_id", ASCENDING), ("date", ASCENDING)],
                unique=True,
                name="idx_employee_date_unique",
            ),
            IndexModel(
                [("date", ASCENDING), ("department", ASCENDING)],
                name="idx_date_department",
            ),
            IndexModel(
                [("employee_id", ASCENDING), ("has_active_session", ASCENDING)],
                name="idx_employee_active_session",
            ),
        ]
        await database["attendance"].create_indexes(attendance_indexes)
        logger.info("Attendance collection indexes ensured.")

        # 2. Corrections Collection Indexes
        corrections_indexes = [
            IndexModel(
                [("employee_id", ASCENDING), ("attendance_date", ASCENDING)],
                unique=True,
                partialFilterExpression={"status": "PENDING"},
                name="idx_unique_pending_correction_per_date",
            ),
            IndexModel(
                [("status", ASCENDING), ("created_at", DESCENDING)],
                name="idx_status_created_at",
            ),
        ]
        await database["corrections"].create_indexes(corrections_indexes)
        logger.info("Corrections collection indexes ensured.")

        # 3. Employees Collection Indexes
        employee_indexes = [
            IndexModel(
                [("employee_id", ASCENDING)],
                unique=True,
                name="idx_employee_id_unique",
            ),
            IndexModel(
                [("department", ASCENDING)],
                name="idx_department",
            ),
        ]
        await database["employees"].create_indexes(employee_indexes)
        logger.info("Employees collection indexes ensured.")

    except PyMongoError as exc:
        logger.warning(
            "Could not ensure database indexes at startup (database may be unreachable or indexing deferred): %s",
            exc.__class__.__name__,
        )
    except Exception as exc:
        logger.error("Unexpected error ensuring database indexes: %s", str(exc))
