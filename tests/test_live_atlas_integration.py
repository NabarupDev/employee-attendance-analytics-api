"""Live integration tests executed directly against the real MongoDB Atlas cluster."""

from datetime import datetime, timezone
import pytest
from app.core.config import get_settings
from app.db.client import db_manager


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_mongodb_atlas_connectivity_and_aggregation():
    """
    Directly verify database operations and aggregation pipelines
    on the live MongoDB Atlas cluster (not mocks).
    """
    settings = get_settings()
    await db_manager.connect(settings)

    is_healthy, msg = await db_manager.ping()
    assert is_healthy is True, f"Failed to ping live MongoDB Atlas: {msg}"
    assert db_manager.database is not None

    db = db_manager.database
    test_col = db["_integration_atlas_test"]

    try:
        # 1. Clean slate for test collection
        await test_col.drop()

        # 2. Insert test documents directly into live Atlas cluster
        test_docs = [
            {
                "employee_id": "EMP-LIVE-1",
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
                "employee_id": "EMP-LIVE-2",
                "department": "Engineering",
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
        ]
        insert_res = await test_col.insert_many(test_docs)
        assert len(insert_res.inserted_ids) == 2

        # 3. Execute multi-stage aggregation pipeline on the live Atlas cluster
        pipeline = [
            {"$match": {"date": "2026-10-10", "department": "Engineering"}},
            {
                "$group": {
                    "_id": "$department",
                    "total_records": {"$sum": 1},
                    "present_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                    },
                    "half_day_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "HALF_DAY"]}, 1, 0]}
                    },
                    "corrected_count": {"$sum": {"$cond": ["$is_corrected", 1, 0]}},
                    "total_work_minutes": {"$sum": "$total_work_minutes"},
                }
            },
        ]

        cursor = test_col.aggregate(pipeline)
        results = await cursor.to_list(length=10)

        # 4. Verify exact mathematical correctness on live Atlas
        assert len(results) == 1
        res = results[0]
        assert res["_id"] == "Engineering"
        assert res["total_records"] == 2
        assert res["present_count"] == 1
        assert res["half_day_count"] == 1
        assert res["corrected_count"] == 1
        assert res["total_work_minutes"] == 750  # 510 + 240

    finally:
        # 5. Clean up temporary test collection completely from live Atlas
        await test_col.drop()
        await db_manager.close()
