"""Employee management and registration endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.client import get_database
from app.schemas.common import ApiResponse
from app.schemas.employee import EmployeeCreateRequest, EmployeeResponse
from app.services.employee_service import EmployeeService

router = APIRouter(prefix="/employees", tags=["Employees"])


@router.post(
    "",
    response_model=ApiResponse[EmployeeResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Register Employee",
    description="Register or seed an employee profile for attendance tracking.",
)
async def register_employee(
    request: EmployeeCreateRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[EmployeeResponse]:
    """Register or update an employee record."""
    service = EmployeeService(db)
    result = await service.create_employee(request)
    return ApiResponse(
        message="Employee registered successfully.",
        data=result,
    )


@router.get(
    "",
    response_model=ApiResponse[list[EmployeeResponse]],
    summary="List Employees",
    description="Retrieve list of registered employees with optional department or status filtering.",
)
async def list_employees(
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
    skip: int = 0,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[list[EmployeeResponse]]:
    """List employees."""
    service = EmployeeService(db)
    employees = await service.list_employees(
        department=department,
        is_active=is_active,
        limit=limit,
        skip=skip,
    )
    return ApiResponse(
        message=f"Found {len(employees)} employee(s).",
        data=employees,
    )


@router.get(
    "/{employee_id}",
    response_model=ApiResponse[EmployeeResponse],
    summary="Get Employee Details",
    description="Retrieve employee details by their employee ID.",
)
async def get_employee(
    employee_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ApiResponse[EmployeeResponse]:
    """Fetch employee by ID."""
    service = EmployeeService(db)
    employee = await service.ensure_employee_exists(employee_id)
    return ApiResponse(
        data=EmployeeResponse(
            employee_id=employee["employee_id"],
            name=employee["name"],
            email=employee["email"],
            department=employee["department"],
            designation=employee.get("designation", "Employee"),
            shift_start=employee.get("shift_start", "09:00"),
            shift_end=employee.get("shift_end", "18:00"),
            joined_on=employee.get("joined_on"),
            is_active=employee.get("is_active", True),
        )
    )
