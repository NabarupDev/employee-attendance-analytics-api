"""Common API response schemas and envelopes."""

from typing import Generic, Optional, TypeVar
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    """Standard API response envelope."""

    success: bool = True
    message: str = "Operation completed successfully."
    data: Optional[DataT] = None


class ErrorResponse(BaseModel):
    """Standard error response structure."""

    error: str = Field(..., description="Error code identifier")
    message: str = Field(..., description="Human-readable error explanation")
    details: Optional[dict] = Field(default=None, description="Additional context or validation details")
