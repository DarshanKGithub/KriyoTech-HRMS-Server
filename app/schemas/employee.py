from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import date


ALLOWED_PROVISION_ROLES = ('Employee', 'Worker', 'Manager')


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: str
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    personal_email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    pan_number: Optional[str] = None
    aadhar_number: Optional[str] = None
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    manager_id: Optional[str] = None
    joining_date: Optional[date] = None
    date_of_confirmation: Optional[date] = None


class EmployeeCreateWithAccount(EmployeeCreate):
    """Create employee master record and linked login account (Admin/HR)."""
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default='Employee', description='Login role: Employee, Worker, or Manager')


class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    personal_email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    pan_number: Optional[str] = None
    aadhar_number: Optional[str] = None
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    manager_id: Optional[str] = None
    joining_date: Optional[date] = None
    date_of_confirmation: Optional[date] = None
    is_active: Optional[bool] = None


class EmployeePublic(BaseModel):
    id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    personal_email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    pan_number: Optional[str] = None
    aadhar_number: Optional[str] = None
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    manager_id: Optional[str] = None
    joining_date: Optional[date] = None
    date_of_confirmation: Optional[date] = None
    is_active: bool


class EmployeePublicWithAccount(EmployeePublic):
    role: str
    login_created: bool = True


class PaginatedEmployees(BaseModel):
    items: list[EmployeePublic]
    total: int
    page: int
    size: int
