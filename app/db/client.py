"""MongoDB client initialization, lifecycle management, and dependency injection."""

import logging
from typing import Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from app.core.config import Settings, get_settings
from app.core.exceptions import DatabaseConnectionError

logger = logging.getLogger(__name__)


class MongoDBManager:
    """Manages the MongoDB connection pool lifecycle."""

    def __init__(self) -> None:
        self.client: Optional[AsyncIOMotorClient] = None
        self.database: Optional[AsyncIOMotorDatabase] = None

    async def connect(self, settings: Optional[Settings] = None) -> None:
        """Establish asynchronous MongoDB connection pool."""
        cfg = settings or get_settings()

        if self.client is not None:
            logger.info("MongoDB client already initialized.")
            return

        try:
            logger.info("Connecting to MongoDB at: %s", cfg.masked_mongodb_uri)
            self.client = AsyncIOMotorClient(
                cfg.MONGODB_URI,
                minPoolSize=cfg.MONGODB_MIN_POOL_SIZE,
                maxPoolSize=cfg.MONGODB_MAX_POOL_SIZE,
                serverSelectionTimeoutMS=cfg.MONGODB_SERVER_SELECTION_TIMEOUT_MS,
                connectTimeoutMS=cfg.MONGODB_CONNECT_TIMEOUT_MS,
                socketTimeoutMS=cfg.MONGODB_SOCKET_TIMEOUT_MS,
                maxIdleTimeMS=cfg.MONGODB_MAX_IDLE_TIME_MS,
                retryWrites=True,
                retryReads=True,
            )
            self.database = self.client[cfg.MONGODB_DB_NAME]

            logger.info("MongoDB client pool initialized for database: %s", cfg.MONGODB_DB_NAME)
        except Exception as exc:
            logger.error("Failed to initialize MongoDB client: %s", str(exc))
            self.client = None
            self.database = None
            raise DatabaseConnectionError(
                "Failed to initialize database client. Please verify configuration."
            ) from exc

    async def close(self) -> None:
        """Gracefully close the MongoDB client connection pool."""
        if self.client is not None:
            logger.info("Closing MongoDB connection pool.")
            self.client.close()
            self.client = None
            self.database = None
            logger.info("MongoDB connection pool closed.")

    async def ping(self) -> Tuple[bool, str]:
        """
        Verify database responsiveness via an admin 'ping' command.
        
        Returns:
            Tuple[bool, str]: (is_healthy, message)
        """
        if self.client is None or self.database is None:
            return False, "Database client is not initialized."

        try:
            # Issue lightweight ping command to verify reachability
            await self.client.admin.command("ping")
            return True, "Database connection is healthy and responsive."
        except ServerSelectionTimeoutError:
            logger.warning("MongoDB ping timed out.")
            return False, "Database server selection timed out. Server may be unreachable."
        except PyMongoError as exc:
            logger.warning("MongoDB ping failed: %s", exc.__class__.__name__)
            return False, f"Database communication error: {exc.__class__.__name__}."
        except Exception:
            logger.exception("Unexpected error during database ping.")
            return False, "Unexpected error verifying database responsiveness."


# Module-level singleton instance
db_manager = MongoDBManager()


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency to retrieve the active MongoDB database."""
    if db_manager.database is None:
        raise DatabaseConnectionError(
            "Database connection is not active. Please ensure server lifecycle completed."
        )
    return db_manager.database


def get_client() -> AsyncIOMotorClient:
    """FastAPI dependency to retrieve the active MongoDB client."""
    if db_manager.client is None:
        raise DatabaseConnectionError(
            "Database client is not active. Please ensure server lifecycle completed."
        )
    return db_manager.client
