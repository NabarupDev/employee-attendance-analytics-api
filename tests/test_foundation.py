"""Unit and integration tests for application configuration, health diagnostics, and MongoDB lifecycle."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from pymongo.errors import ServerSelectionTimeoutError

from app.core.config import Settings
from app.core.exceptions import DatabaseConnectionError
from app.db.client import MongoDBManager, get_database, get_client


def test_settings_defaults():
    """Verify default settings configuration."""
    settings = Settings(
        ENVIRONMENT="development",
        MONGODB_URI="mongodb://localhost:27017",
    )
    assert settings.PROJECT_NAME == "Employee Attendance & Analytics API"
    assert settings.is_testing is False
    assert settings.is_production is False
    assert settings.MONGODB_DB_NAME == "attendance_analytics_db"


def test_settings_masked_mongodb_uri():
    """Verify sensitive credentials are safely masked in MongoDB URI representation."""
    plain_settings = Settings(
        MONGODB_URI="mongodb://localhost:27017",
    )
    assert plain_settings.masked_mongodb_uri == "mongodb://localhost:27017"

    sensitive_settings = Settings(
        MONGODB_URI="mongodb+srv://admin_user:super_secret_password_123@cluster0.abc.mongodb.net/?retryWrites=true",
    )
    masked = sensitive_settings.masked_mongodb_uri
    assert "super_secret_password_123" not in masked
    assert "admin_user:******@" in masked


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    """Verify root endpoint returns HTTP 200 and expected metadata."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "version" in data
    assert "service" in data


@pytest.mark.asyncio
async def test_health_check_endpoint_structure(async_client: AsyncClient):
    """Verify health check endpoint returns structured diagnostic payload."""
    response = await async_client.get("/health")
    assert response.status_code in [200, 503]
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "connected" in data["database"]
    assert "message" in data["database"]
    # Verify no credential leaks in the message
    assert "password" not in data["database"]["message"].lower()


@pytest.mark.asyncio
async def test_db_manager_lifecycle():
    """Verify MongoDB manager connection lifecycle and cleanup."""
    manager = MongoDBManager()
    settings = Settings(
        MONGODB_URI="mongodb://localhost:27017",
        MONGODB_DB_NAME="test_db",
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=500,
    )

    # 1. Connect
    await manager.connect(settings)
    assert manager.client is not None
    assert manager.database is not None
    assert manager.database.name == "test_db"

    # 2. Close
    await manager.close()
    assert manager.client is None
    assert manager.database is None


@pytest.mark.asyncio
async def test_db_manager_ping_failure_sanitized_message():
    """Verify that database ping failures produce sanitized, non-sensitive error messages."""
    manager = MongoDBManager()
    settings = Settings(
        MONGODB_URI="mongodb://non_existent_host:27017",
        MONGODB_DB_NAME="test_db",
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=100,
    )
    await manager.connect(settings)

    # Mock admin command ping raising ServerSelectionTimeoutError
    with patch.object(
        manager.client.admin,
        "command",
        AsyncMock(side_effect=ServerSelectionTimeoutError("connection to non_existent_host failed")),
    ):
        is_healthy, message = await manager.ping()
        assert is_healthy is False
        assert "server selection timed out" in message.lower()
        # Ensure raw internal connection string with potential credentials is never echoed
        assert "mongodb://" not in message

    await manager.close()


def test_uninitialized_database_dependencies_raise_error():
    """Verify accessing get_database() or get_client() without active connection raises clean exception."""
    with patch("app.db.client.db_manager.database", None):
        with pytest.raises(DatabaseConnectionError) as exc_info:
            get_database()
        assert "Database connection is not active" in str(exc_info.value)

    with patch("app.db.client.db_manager.client", None):
        with pytest.raises(DatabaseConnectionError) as exc_info:
            get_client()
        assert "Database client is not active" in str(exc_info.value)
