from app.http import Router, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions, get_current_user
from app.db.database import get_db
from app.db.models import User
from app.schemas.organization import DepartmentCreate, DepartmentPublic, DesignationCreate, DesignationPublic, OrgNode
from app.services.org_service import list_departments, create_department, list_designations, create_designation, get_org_hierarchy

router = Router()


def _tenant(user):
    if not user.tenant_id:
        raise HTTPException(403, 'An organization assignment is required')
    return user.tenant_id


@router.get('/departments', response_model=list[DepartmentPublic])
def departments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [DepartmentPublic(id=d.id, name=d.name) for d in list_departments(db=db, tenant_id=_tenant(user), scoped=True)]


@router.post('/departments', response_model=DepartmentPublic)
def create_dept(
    payload: DepartmentCreate,
    _user: User = Depends(require_permissions('manage_org')),
    db: Session = Depends(get_db),
) -> DepartmentPublic:
    d = create_department(payload=payload, db=db, tenant_id=_tenant(_user))
    return DepartmentPublic(id=d.id, name=d.name)


@router.get('/designations', response_model=list[DesignationPublic])
def designations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [DesignationPublic(id=d.id, name=d.name) for d in list_designations(db=db, tenant_id=_tenant(user), scoped=True)]


@router.post('/designations', response_model=DesignationPublic)
def create_des(
    payload: DesignationCreate,
    _user: User = Depends(require_permissions('manage_org')),
    db: Session = Depends(get_db),
) -> DesignationPublic:
    d = create_designation(payload=payload, db=db, tenant_id=_tenant(_user))
    return DesignationPublic(id=d.id, name=d.name)


@router.get('/hierarchy', response_model=list[OrgNode])
def get_hierarchy(
    _user: User = Depends(get_current_user), # Just basic auth for now
    db: Session = Depends(get_db),
):
    return get_org_hierarchy(db, tenant_id=_tenant(_user), scoped=True)
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from app.db.models import Tenant, Department, Designation, Employee, Shift, Holiday, LeaveType, LeaveBalance, Salary, Subscription

class WorkPolicy(BaseModel):
    timezone: str = 'Asia/Kolkata'
    working_days: list[int] = Field(min_length=1, max_length=7)
    @field_validator('working_days')
    @classmethod
    def valid_days(cls, values):
        if len(set(values)) != len(values) or any(day not in range(7) for day in values):
            raise ValueError('Select distinct weekdays from 0 (Monday) to 6 (Sunday)')
        return sorted(values)
    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc: raise ValueError('Use a valid IANA timezone') from exc
        return value

class LeavePolicy(BaseModel):
    id: str | None = None
    name: str = Field(min_length=2, max_length=80)
    description: str | None = None
    default_days_per_year: float = Field(ge=0, le=366)
    is_paid: bool = True
    is_active: bool = True

class OpeningBalance(BaseModel):
    employee_id: str
    leave_type_id: str
    year: int = Field(ge=2000, le=2200)
    granted_days: float = Field(ge=0, le=366)

@router.get('/setup')
def company_setup(user: User = Depends(require_permissions('manage_org')), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, _tenant(user))
    counts = {name: db.scalar(select(func.count(model.id))) or 0 for name, model in [('departments',Department),('designations',Designation),('employees',Employee),('shifts',Shift),('holidays',Holiday),('leave_types',LeaveType),('leave_balances',LeaveBalance),('salaries',Salary)]}
    types = db.scalars(select(LeaveType).order_by(LeaveType.name)).all()
    return {'timezone': tenant.timezone, 'working_days': json.loads(tenant.working_days_json), 'counts': counts, 'leave_types': [{'id': item.id, 'name': item.name, 'description': item.description, 'default_days_per_year': float(item.default_days_per_year), 'is_paid': item.is_paid, 'is_active': item.is_active} for item in types]}

@router.put('/settings')
def set_work_policy(payload: WorkPolicy, user: User = Depends(require_permissions('manage_org')), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, _tenant(user))
    tenant.timezone = payload.timezone
    tenant.working_days_json = json.dumps(payload.working_days)
    db.commit()
    return payload.model_dump()

@router.post('/leave-types')
def set_leave_policy(payload: LeavePolicy, user: User = Depends(require_permissions('manage_org')), db: Session = Depends(get_db)):
    item = db.scalar(select(LeaveType).where(LeaveType.id == payload.id)) if payload.id else None
    if payload.id and not item:
        raise HTTPException(404, 'Leave type not found')
    duplicate = db.scalar(select(LeaveType).where(LeaveType.name == payload.name.strip(), LeaveType.id != payload.id))
    if duplicate:
        raise HTTPException(409, 'A leave type with this name already exists')
    if item is None:
        item = LeaveType(tenant_id=user.tenant_id)
        db.add(item)
    for key,value in payload.model_dump(exclude={'id'}).items():
        setattr(item,key,value.strip() if isinstance(value,str) else value)
    db.commit()
    return {'id': item.id, **payload.model_dump(exclude={'id'})}

@router.put('/leave-balances')
def allocate_balance(payload: OpeningBalance, user: User = Depends(require_permissions('manage_org')), db: Session = Depends(get_db)):
    employee = db.scalar(select(Employee).where(Employee.id == payload.employee_id))
    kind = db.scalar(select(LeaveType).where(LeaveType.id == payload.leave_type_id))
    if not employee or not kind:
        raise HTTPException(404, 'Employee or leave type not found')
    balance = db.scalar(select(LeaveBalance).where(LeaveBalance.employee_id == employee.id, LeaveBalance.leave_type_id == kind.id, LeaveBalance.year == payload.year).with_for_update())
    if balance is None:
        balance = LeaveBalance(employee_id=employee.id, leave_type_id=kind.id, year=payload.year, granted_days=0, balance_days=0)
        db.add(balance)
    consumed = float(balance.granted_days or 0)-float(balance.balance_days or 0)
    if payload.granted_days < consumed:
        raise HTTPException(409, 'Opening balance cannot be less than leave already consumed')
    balance.granted_days = payload.granted_days
    balance.balance_days = payload.granted_days-consumed
    db.commit()
    return {'id': balance.id, 'granted_days': float(balance.granted_days), 'balance_days': float(balance.balance_days)}
