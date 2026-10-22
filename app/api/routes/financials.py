from app.services.auth_service import resolve_employee_id
from app.http import Router, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Optional

from app.core.rbac import get_current_user, require_permissions, has_permission
from app.db.database import get_db
from app.db.models import User, SalaryStructure, Reimbursement, EmployeeLoan
from app.schemas.financials import (
    SalaryStructureCreate, SalaryStructurePublic,
    ReimbursementCreate, ReimbursementPublic,
    EmployeeLoanCreate, EmployeeLoanPublic
)

router = Router()

# --- Salary Structure ---

@router.post('/salary-structures', response_model=SalaryStructurePublic)
def create_salary_structure(
    payload: SalaryStructureCreate,
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db)
):
    from app.db.models import Employee
    from app.core.business_time import business_today
    from app.services.payroll_service import update_salary
    employee = db.scalar(select(Employee).where(Employee.id==payload.employee_id))
    if not employee:
        raise HTTPException(404, 'Employee not found')
    existing = db.scalar(select(SalaryStructure).where(SalaryStructure.employee_id==payload.employee_id))
    data=payload.model_dump(exclude={'effective_from'})
    if existing:
        for key,value in data.items(): setattr(existing,key,value)
        struct=existing
    else:
        struct=SalaryStructure(**data); db.add(struct)
    update_salary(employee.id,payload.base_salary,None,payload.effective_from or business_today(db,user.tenant_id),'Compensation setup',user.id,db,tenant_id=user.tenant_id)
    return SalaryStructurePublic.model_validate(struct,from_attributes=True)


@router.get('/salary-structures/{employee_id}', response_model=SalaryStructurePublic)
def get_salary_structure(
    employee_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_payroll'):
        raise HTTPException(status_code=403, detail='Not authorized')

    struct = db.query(SalaryStructure).filter(SalaryStructure.employee_id == employee_id).first()
    if not struct:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    return SalaryStructurePublic.model_validate(struct, from_attributes=True)

# --- Reimbursements ---

@router.post('/reimbursements', response_model=ReimbursementPublic)
def apply_reimbursement(
    payload: ReimbursementCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reim = Reimbursement(**payload.model_dump(), employee_id=user.id)
    db.add(reim)
    db.commit()
    db.refresh(reim)
    return ReimbursementPublic.model_validate(reim, from_attributes=True)

@router.get('/reimbursements', response_model=list[ReimbursementPublic])
def list_reimbursements(
    employee_id: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Reimbursement)
    if employee_id:
        if employee_id != resolve_employee_id(user, db) and user.role not in ['HR', 'Admin', 'Manager']:
            raise HTTPException(status_code=403, detail="Not authorized")
        query = query.filter(Reimbursement.employee_id == employee_id)
    else:
        if user.role not in ['HR', 'Admin', 'Manager']:
            query = query.filter(Reimbursement.employee_id == user.id)
            
    items = query.order_by(Reimbursement.applied_on.desc()).all()
    return [ReimbursementPublic.model_validate(i, from_attributes=True) for i in items]

@router.patch('/reimbursements/{id}/status', response_model=ReimbursementPublic)
def update_reimbursement_status(
    id: str,
    status: str = Query(...),
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db)
):
    reim = db.query(Reimbursement).filter(Reimbursement.id == id).first()
    if not reim:
        raise HTTPException(status_code=404, detail="Reimbursement not found")
    reim.status = status
    db.commit()
    db.refresh(reim)
    return ReimbursementPublic.model_validate(reim, from_attributes=True)

# --- Loans ---

@router.post('/loans', response_model=EmployeeLoanPublic)
def apply_loan(
    payload: EmployeeLoanCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    loan = EmployeeLoan(**payload.model_dump(), employee_id=user.id)
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return EmployeeLoanPublic.model_validate(loan, from_attributes=True)

@router.get('/loans', response_model=list[EmployeeLoanPublic])
def list_loans(
    employee_id: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(EmployeeLoan)
    if employee_id:
        if employee_id != resolve_employee_id(user, db) and user.role not in ['HR', 'Admin', 'Manager']:
            raise HTTPException(status_code=403, detail="Not authorized")
        query = query.filter(EmployeeLoan.employee_id == employee_id)
    else:
        if user.role not in ['HR', 'Admin', 'Manager']:
            query = query.filter(EmployeeLoan.employee_id == user.id)
            
    items = query.order_by(EmployeeLoan.created_at.desc()).all()
    return [EmployeeLoanPublic.model_validate(i, from_attributes=True) for i in items]
