from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date

class SalaryStructureBase(BaseModel):
    base_salary: float = Field(ge=0)
    hra: float = Field(ge=0)
    da: float = Field(ge=0)
    special_allowance: float = Field(ge=0)
    pf_percentage: float = Field(ge=0, le=100)
    esi_percentage: float = Field(ge=0, le=100)
    tax_bracket_percentage: float = Field(ge=0, le=100)

class SalaryStructureCreate(SalaryStructureBase):
    employee_id: str
    effective_from: date | None = None

class SalaryStructurePublic(SalaryStructureBase):
    id: str
    employee_id: str
    created_at: datetime

class ReimbursementCreate(BaseModel):
    expense_type: str
    amount: float
    receipt_url: Optional[str] = None
    description: Optional[str] = None

class ReimbursementPublic(ReimbursementCreate):
    id: str
    employee_id: str
    status: str
    applied_on: datetime

class EmployeeLoanCreate(BaseModel):
    loan_type: str
    amount: float
    interest_rate: float
    emi_amount: float
    remaining_balance: float

class EmployeeLoanPublic(EmployeeLoanCreate):
    id: str
    employee_id: str
    status: str
    created_at: datetime
