"""FastAPI application initialization and lifespan configuration."""

from contextlib import asynccontextmanager
import logging
from typing import Any, AsyncGenerator, Dict
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
)
from app.db.client import db_manager
from app.db.indexes import init_db_indexes

# Configure standard application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager.
    
    Handles clean database connection initialization on startup
    and graceful resource deallocation on shutdown.
    """
    settings = get_settings()
    logger.info("Initializing application in %s mode...", settings.ENVIRONMENT)

    # Startup: Connect to MongoDB
    try:
        await db_manager.connect(settings)
        # Attempt index initialization if database is available
        if db_manager.database is not None:
            await init_db_indexes(db_manager.database)
    except Exception as exc:
        logger.warning(
            "Application startup proceeded with database initialization notice: %s",
            str(exc),
        )

    yield

    # Shutdown: Close database connection pool
    logger.info("Shutting down application and closing database connections...")
    await db_manager.close()
    logger.info("Application shutdown complete.")


def create_application() -> FastAPI:
    """Application factory for FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        description="Employee Attendance & Analytics API with MongoDB Aggregation Pipelines",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS configuration - W3C compliant wildcard origin configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register centralized exception handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # Register API Routers (Dual-mounted: versioned prefix and root paths for 100% contract compliance)
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)
    app.include_router(api_v1_router, prefix="")

    @app.get(
        "/",
        tags=["System"],
        summary="Service Root",
        response_model=Dict[str, Any],
    )
    async def root() -> Dict[str, Any]:
        """Return basic service metadata."""
        return {
            "service": settings.PROJECT_NAME,
            "version": "0.1.0",
            "environment": settings.ENVIRONMENT,
            "status": "operational",
            "docs": "/docs",
        }

    @app.get(
        "/health",
        tags=["System"],
        summary="Health Check",
        response_model=Dict[str, Any],
    )
    async def health_check() -> JSONResponse:
        """
        System and database connectivity health check.
        
        Returns useful, sanitized connectivity details without exposing credentials.
        """
        is_db_healthy, db_message = await db_manager.ping()

        health_payload = {
            "status": "healthy" if is_db_healthy else "degraded",
            "environment": settings.ENVIRONMENT,
            "database": {
                "connected": is_db_healthy,
                "message": db_message,
                "target_database": settings.MONGODB_DB_NAME,
            },
        }

        http_status = status.HTTP_200_OK if is_db_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

        return JSONResponse(
            status_code=http_status,
            content=health_payload,
        )

    return app


app = create_application()
