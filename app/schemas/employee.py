"""Employee Pydantic models and validation schemas."""

from typing import Optional
from pydantic import BaseModel, Field


class EmployeeCreateRequest(BaseModel):
    """Schema for registering or seeding an employee."""

    employee_id: str = Field(..., min_length=2, max_length=50, description="Unique employee identifier (e.g. EMP-1001)")
    name: str = Field(..., min_length=2, max_length=100, description="Employee full name")
    email: str = Field(
        ...,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Employee corporate email address",
    )
    department: str = Field(..., min_length=2, max_length=100, description="Department name (e.g. Engineering, Sales)")
    designation: Optional[str] = Field(default="Employee", max_length=100, description="Job title")
    is_active: bool = Field(default=True, description="Whether the employee is active")


class EmployeeResponse(BaseModel):
    """Schema for employee details returned to client."""

    employee_id: str
    name: str
    email: str
    department: str
    designation: str
    is_active: bool
