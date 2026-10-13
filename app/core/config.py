"""Application settings and environment configuration."""

from functools import lru_cache
import re
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application Settings
    PROJECT_NAME: str = "Employee Attendance & Analytics API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = Field(default="development", description="development | staging | production | testing")
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # MongoDB Settings
    MONGODB_URI: str = Field(
        default="mongodb://localhost:27017",
        description="MongoDB connection string (URI)",
    )
    MONGODB_DB_NAME: str = Field(
        default="attendance_analytics_db",
        description="Target database name",
    )
    MONGODB_MIN_POOL_SIZE: int = 1
    MONGODB_MAX_POOL_SIZE: int = 50
    MONGODB_SERVER_SELECTION_TIMEOUT_MS: int = 5000
    MONGODB_CONNECT_TIMEOUT_MS: int = 10000
    MONGODB_SOCKET_TIMEOUT_MS: int = 20000
    MONGODB_MAX_IDLE_TIME_MS: int = 45000

    @property
    def is_testing(self) -> bool:
        """Check whether application is in testing mode."""
        return self.ENVIRONMENT.lower() == "testing"

    @property
    def is_production(self) -> bool:
        """Check whether application is in production mode."""
        return self.ENVIRONMENT.lower() == "production"

    @property
    def masked_mongodb_uri(self) -> str:
        """Return the MongoDB URI with any embedded credentials masked for safe logging."""
        # Matches mongodb://user:pass@host or mongodb+srv://user:pass@host
        pattern = r"://([^:]+):([^@]+)@"
        if re.search(pattern, self.MONGODB_URI):
            return re.sub(pattern, r"://\1:******@", self.MONGODB_URI)
        return self.MONGODB_URI


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
