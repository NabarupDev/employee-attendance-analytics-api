"""Pytest configuration and shared test fixtures with database isolation."""

from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
try:
    from mongomock_motor import AsyncMongoMockClient
except ImportError as err:
    raise ImportError(
        "mongomock_motor is required for the hermetic in-memory test suite. "
        "Please install all dependencies: pip install -r requirements.txt (or pip install 'mongomock-motor>=0.0.29')"
    ) from err

from app.core.config import Settings
from app.db.client import get_database
from app.main import create_application


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Return test settings with safe test configuration."""
    return Settings(
        PROJECT_NAME="Employee Attendance & Analytics API (Test)",
        ENVIRONMENT="testing",
        DEBUG=True,
        MONGODB_URI="mongodb://localhost:27017",
        MONGODB_DB_NAME="test_attendance_analytics_db",
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=1000,
    )


@pytest_asyncio.fixture
async def mock_db():
    """Create an isolated, in-memory MongoDB mock database for testing."""
    client = AsyncMongoMockClient()
    db = client["test_attendance_db"]

    # Pre-seed default test employees
    await db["employees"].insert_many([
        {
            "employee_id": "EMP-1001",
            "name": "Alice Walker",
            "email": "alice.walker@hr0ne.internal",
            "department": "Engineering",
            "designation": "Backend Engineer",
            "is_active": True,
        },
        {
            "employee_id": "EMP-1002",
            "name": "Bob Smith",
            "email": "bob.smith@hr0ne.internal",
            "department": "Product",
            "designation": "Product Manager",
            "is_active": True,
        },
        {
            "employee_id": "MGR-5001",
            "name": "Carol Danvers",
            "email": "carol.danvers@hr0ne.internal",
            "department": "Management",
            "designation": "Engineering Manager",
            "is_active": True,
        },
        {
            "employee_id": "MGR-5002",
            "name": "Dave Rogers",
            "email": "dave.rogers@hr0ne.internal",
            "department": "Management",
            "designation": "Operations Manager",
            "is_active": True,
        },
        {
            "employee_id": "MGR-1001",
            "name": "Eve Adams",
            "email": "eve.adams@hr0ne.internal",
            "department": "Management",
            "designation": "Operations Manager",
            "is_active": True,
        },
    ])




    yield db

    # Cleanup collections after test
    await db["attendance"].drop()
    await db["employees"].drop()


@pytest_asyncio.fixture
async def async_client(mock_db):
    """Create an asynchronous HTTP test client for FastAPI with isolated mock DB dependency."""
    app = create_application()

    # Override get_database dependency with the isolated mock database
    app.dependency_overrides[get_database] = lambda: mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
