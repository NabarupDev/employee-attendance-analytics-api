"""Employee Pydantic models and validation schemas."""

from typing import Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field


class EmployeeCreateRequest(BaseModel):
    """Schema for registering or seeding an employee."""

    employee_id: str = Field(
        ...,
        validation_alias=AliasChoices("employee_id", "emp_code"),
        min_length=2,
        max_length=50,
        description="Unique employee identifier (e.g. EMP-1001 or emp_code)",
        examples=["EMP-1001"],
    )
    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Employee full name",
        examples=["Alice Walker"],
    )
    email: str = Field(
        ...,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Employee corporate email address",
        examples=["alice.walker@hr0ne.internal"],
    )
    department: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Department name (e.g. Engineering, Sales)",
        examples=["Engineering"],
    )
    designation: Optional[str] = Field(
        default="Employee",
        max_length=100,
        description="Job title",
        examples=["Backend Engineer"],
    )
    shift_start: Optional[str] = Field(
        default="09:00",
        description="Shift start time in HH:MM format",
        examples=["09:00"],
    )
    shift_end: Optional[str] = Field(
        default="18:00",
        description="Shift end time in HH:MM format",
        examples=["18:00"],
    )
    joined_on: Optional[str] = Field(
        default=None,
        description="Employee joining date in YYYY-MM-DD format",
        examples=["2026-01-15"],
    )
    is_active: bool = Field(
        default=True,
        description="Whether the employee is active",
        examples=[True],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "name": "Alice Walker",
                "email": "alice.walker@hr0ne.internal",
                "department": "Engineering",
                "designation": "Backend Engineer",
                "shift_start": "09:00",
                "shift_end": "18:00",
                "joined_on": "2026-01-15",
                "is_active": True,
            }
        }
    )


class EmployeeResponse(BaseModel):
    """Schema for employee details returned to client."""

    employee_id: str = Field(..., examples=["EMP-1001"])
    name: str = Field(..., examples=["Alice Walker"])
    email: str = Field(..., examples=["alice.walker@hr0ne.internal"])
    department: str = Field(..., examples=["Engineering"])
    designation: str = Field(..., examples=["Backend Engineer"])
    shift_start: Optional[str] = Field("09:00", examples=["09:00"])
    shift_end: Optional[str] = Field("18:00", examples=["18:00"])
    joined_on: Optional[str] = Field(None, examples=["2026-01-15"])
    is_active: bool = Field(True, examples=[True])

    @computed_field
    @property
    def emp_code(self) -> str:
        """Alias for employee_id to satisfy contracts expecting emp_code."""
        return self.employee_id

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "EMP-1001",
                "emp_code": "EMP-1001",
                "name": "Alice Walker",
                "email": "alice.walker@hr0ne.internal",
                "department": "Engineering",
                "designation": "Backend Engineer",
                "shift_start": "09:00",
                "shift_end": "18:00",
                "joined_on": "2026-01-15",
                "is_active": True,
            }
        }
    )

