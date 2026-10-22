from datetime import date, datetime

from pydantic import BaseModel, Field


class LeaveTypePublic(BaseModel):
    id: str
    name: str
    description: str | None = None
    default_days_per_year: float
    is_active: bool
    created_at: datetime


class LeaveRequestCreate(BaseModel):
    leave_type_id: str
    start_date: date
    end_date: date
    session_from: str | None = 'Session 1'
    session_to: str | None = 'Session 2'
    reason: str | None = None
    contact_details: str | None = None
    cc_to: list[str] | None = None  # List of email addresses
    attachment_paths: list[str] | None = None  # List of file paths


class LeaveRequestUpdate(BaseModel):
    status: str | None = None
    reason: str | None = None


class LeaveRequestPublic(BaseModel):
    id: str
    employee_id: str
    employee_name: str | None = None
    leave_type_id: str
    start_date: date
    end_date: date
    session_from: str | None = None
    session_to: str | None = None
    days_requested: float
    reason: str | None = None
    contact_details: str | None = None
    cc_to: str | None = None
    attachment_paths: str | None = None
    status: str
    approver_id: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApprovePayload(BaseModel):
    approve: bool = Field(...)
    note: str | None = None


class LeaveBalancePublic(BaseModel):
    id: str
    employee_id: str
    leave_type_id: str
    year: int
    granted_days: float
    balance_days: float
    created_at: datetime
    updated_at: datetime


class PaginatedLeaveRequests(BaseModel):
    items: list[LeaveRequestPublic]
    total: int
    page: int
    size: int


class FileUploadResponse(BaseModel):
    file_path: str
    filename: str
    size: int


class BulkApprovePayload(BaseModel):
    request_ids: list[str] = Field(default_factory=list)
    approve: bool = True


class BulkApproveResult(BaseModel):
    processed: int
    approved: int
    rejected: int
    failed: int
    failed_ids: list[str] = Field(default_factory=list)


class HolidayCreate(BaseModel):
    name: str
    holiday_date: date
    is_public: bool = True


class HolidayPublic(BaseModel):
    id: str
    name: str
    holiday_date: date
    is_public: bool
    created_at: datetime

class CCOption(BaseModel):
    id: str
    name: str
    email: str
    role: str

class CCOptionsPublic(BaseModel):
    manager: CCOption | None = None
    hr: list[CCOption] = Field(default_factory=list)
    ceo: list[CCOption] = Field(default_factory=list)

class LeaveHistoryItem(BaseModel):
    id: str
    action: str
    actor_name: str | None = None
    created_at: datetime
