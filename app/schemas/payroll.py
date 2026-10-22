"""Pydantic schemas for Payroll Management (Phase 6)."""
from datetime import datetime, date
from pydantic import BaseModel, Field


# --- Salary Schemas ---
class SalaryCreate(BaseModel):
    employee_id: str
    base_salary: float
    grade: str | None = None
    currency: str = "INR"
    effective_from: date


class SalaryPublic(BaseModel):
    id: str
    employee_id: str
    base_salary: float
    grade: str | None
    currency: str
    effective_from: date
    effective_to: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --- Salary Component Schemas ---
class SalaryComponentCreate(BaseModel):
    name: str
    component_type: str  # 'earning', 'deduction', 'tax'
    description: str | None = None

class SalaryComponentUpdate(BaseModel):
    name: str | None = None
    component_type: str | None = None
    description: str | None = None
    is_active: bool | None = None



class SalaryComponentPublic(BaseModel):
    id: str
    name: str
    component_type: str
    description: str | None
    is_active: bool


# --- Employee Salary Component Schemas ---
class EmployeeSalaryComponentCreate(BaseModel):
    employee_id: str
    salary_component_id: str
    amount: float
    is_fixed: bool = True


class EmployeeSalaryComponentPublic(BaseModel):
    id: str
    employee_id: str
    salary_component_id: str
    amount: float
    is_fixed: bool
    created_at: datetime
    updated_at: datetime


# --- Payslip Schemas ---
class PayslipCreate(BaseModel):
    employee_id: str
    month: int = Field(ge=1, le=12)
    year: int


class PayslipComponentIn(BaseModel):
    salary_component_id: str
    component_name: str
    component_type: str
    amount: float


class PayslipComponentPublic(BaseModel):
    id: str
    component_name: str
    component_type: str
    amount: float


class PayslipPublic(BaseModel):
    id: str
    employee_id: str
    month: int
    year: int
    base_salary: float
    gross_salary: float
    total_deductions: float
    total_tax: float
    net_salary: float
    days_worked: float
    days_absent: float
    status: str
    processed_by: str | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PayslipDetailPublic(PayslipPublic):
    components: list[PayslipComponentPublic] = []


class PaginatedPayslips(BaseModel):
    items: list[PayslipPublic] = []
    total: int
    page: int
    size: int


# --- Batch Payroll Schemas ---
class BatchPayrollRequest(BaseModel):
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    year: int = Field(..., ge=2000, description="Year")


class BatchPayrollError(BaseModel):
    employee_id: str
    employee_name: str
    error: str


class BatchPayrollResult(BaseModel):
    total_employees: int
    successful: int
    failed: int
    already_exists: int
    errors: list[BatchPayrollError] = []


# --- Salary History Schemas ---
class SalaryHistoryItem(BaseModel):
    id: str
    base_salary: float
    grade: str | None
    currency: str
    effective_from: date
    effective_to: date | None
    reason_for_change: str | None
    modified_by: str | None
    created_at: datetime


class SalaryHistoryResponse(BaseModel):
    items: list[SalaryHistoryItem] = []
    total: int
    page: int
    size: int


class UpdateSalaryRequest(BaseModel):
    base_salary: float = Field(..., gt=0, description="New base salary")
    grade: str | None = None
    effective_from: date = Field(..., description="Effective from date")
    reason: str | None = None

