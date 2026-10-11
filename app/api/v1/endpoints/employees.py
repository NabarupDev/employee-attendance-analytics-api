"""Employee management and registration endpoints."""

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
            is_active=employee.get("is_active", True),
        )
    )
