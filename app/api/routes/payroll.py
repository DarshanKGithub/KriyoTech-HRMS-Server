from app.services.auth_service import resolve_employee_id
"""API routes for Payroll Management (Phase 6)."""
from datetime import datetime

from app.http import Router, Depends, HTTPException, Query, status
from app.http import FileResponse
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user, has_permission, require_permissions
from app.db.database import get_db
from app.db.models import User
from app.schemas.payroll import (
    SalaryPublic,
    PayslipPublic,
    PayslipDetailPublic,
    PayslipCreate,
    PaginatedPayslips,
    BatchPayrollRequest,
    BatchPayrollResult,
    SalaryHistoryResponse,
    UpdateSalaryRequest,
    SalaryComponentCreate,
    SalaryComponentUpdate,
    SalaryComponentPublic,
)
from app.services.payroll_service import (
    create_payslip,
    get_payslip,
    list_payslips,
    approve_payslip,
    mark_payslip_paid,
    get_or_create_salary,
    get_payslip_details,
    send_payslip_email,
    run_batch_payroll,
    get_salary_history,
    update_salary,
)
router = Router()


# --- Salary Components ---

@router.get('/components', response_model=list[SalaryComponentPublic])
def list_components(
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
):
    from app.db.models import SalaryComponent
    components = db.query(SalaryComponent).filter(SalaryComponent.tenant_id == user.tenant_id).all()
    return components

@router.post('/components', response_model=SalaryComponentPublic)
def create_component(
    payload: SalaryComponentCreate,
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
):
    from app.db.models import SalaryComponent
    comp = SalaryComponent(
        tenant_id=user.tenant_id,
        name=payload.name,
        component_type=payload.component_type,
        description=payload.description,
        is_active=True
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return comp

@router.put('/components/{component_id}', response_model=SalaryComponentPublic)
def update_component(
    component_id: str,
    payload: SalaryComponentUpdate,
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
):
    from app.db.models import SalaryComponent
    comp = db.query(SalaryComponent).filter(SalaryComponent.id == component_id, SalaryComponent.tenant_id == user.tenant_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Salary component not found")
    
    if payload.name is not None:
        comp.name = payload.name
    if payload.component_type is not None:
        comp.component_type = payload.component_type
    if payload.description is not None:
        comp.description = payload.description
    if payload.is_active is not None:
        comp.is_active = payload.is_active
        
    db.commit()
    db.refresh(comp)
    return comp

@router.delete('/components/{component_id}')
def delete_component(
    component_id: str,
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
):
    from app.db.models import SalaryComponent
    comp = db.query(SalaryComponent).filter(SalaryComponent.id == component_id, SalaryComponent.tenant_id == user.tenant_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Salary component not found")
    
    db.delete(comp)
    db.commit()
    return {"message": "Component deleted"}


@router.get('/salary', response_model=SalaryPublic)
def get_salary_endpoint(
    employee_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalaryPublic:
    """Get salary details for an employee."""
    # Default to requesting user's own salary
    if not employee_id:
        employee_id = resolve_employee_id(user, db)
    
    # Employees can only view their own salary unless Admin/HR
    if employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_payroll'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees salary')
    
    sal = get_or_create_salary(employee_id, db, tenant_id=user.tenant_id)
    return SalaryPublic.model_validate({
        'id': sal.id,
        'employee_id': sal.employee_id,
        'base_salary': sal.base_salary,
        'grade': sal.grade,
        'currency': sal.currency,
        'effective_from': sal.effective_from,
        'effective_to': sal.effective_to,
        'is_active': sal.is_active,
        'created_at': sal.created_at,
        'updated_at': sal.updated_at,
    })


@router.post('/payslips', response_model=PayslipPublic)
def create_payslip_endpoint(
    payload: PayslipCreate,
    _user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
) -> PayslipPublic:
    """Generate a payslip for an employee (auto-calculates days_worked from attendance)."""
    # Auto-calculate days_worked and days_absent from attendance records
    ps = create_payslip(
        employee_id=payload.employee_id,
        month=payload.month,
        year=payload.year,
        db=db,
        tenant_id=_user.tenant_id
    )
    
    return PayslipPublic.model_validate({
        'id': ps.id,
        'employee_id': ps.employee_id,
        'month': ps.month,
        'year': ps.year,
        'base_salary': ps.base_salary,
        'gross_salary': ps.gross_salary,
        'total_deductions': ps.total_deductions,
        'total_tax': ps.total_tax,
        'net_salary': ps.net_salary,
        'days_worked': ps.days_worked,
        'days_absent': ps.days_absent,
        'status': ps.status,
        'processed_by': ps.processed_by,
        'processed_at': ps.processed_at,
        'created_at': ps.created_at,
        'updated_at': ps.updated_at,
    })


@router.get('/payslips', response_model=PaginatedPayslips)
def list_payslips_endpoint(
    employee_id: str | None = Query(None),
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedPayslips:
    """List payslips with optional filters."""
    if employee_id and employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_payroll'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees payslips')

    if not employee_id and not has_permission(user.role, 'view_payroll'):
        employee_id = resolve_employee_id(user, db)
    
    items, total = list_payslips(db, tenant_id=user.tenant_id, employee_id=employee_id, month=month, year=year, page=page, size=size)
    
    return PaginatedPayslips(
        items=[PayslipPublic.model_validate({
            'id': p.id,
            'employee_id': p.employee_id,
            'month': p.month,
            'year': p.year,
            'base_salary': p.base_salary,
            'gross_salary': p.gross_salary,
            'total_deductions': p.total_deductions,
            'total_tax': p.total_tax,
            'net_salary': p.net_salary,
            'days_worked': p.days_worked,
            'days_absent': p.days_absent,
            'status': p.status,
            'processed_by': p.processed_by,
            'processed_at': p.processed_at,
            'created_at': p.created_at,
            'updated_at': p.updated_at,
        }) for p in items],
        total=total,
        page=page,
        size=size,
    )


@router.get('/payslips/{payslip_id}', response_model=PayslipDetailPublic)
def get_payslip_endpoint(
    payslip_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed payslip with components breakdown."""
    ps = get_payslip(payslip_id, db, tenant_id=user.tenant_id)
    
    # Employees can only view their own payslips
    if ps.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_payroll'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees payslips')
    
    # Get components
    from app.db.models import PayslipComponent
    components = db.query(PayslipComponent).filter(PayslipComponent.payslip_id == payslip_id).all()
    
    return PayslipDetailPublic.model_validate({
        'id': ps.id,
        'employee_id': ps.employee_id,
        'month': ps.month,
        'year': ps.year,
        'base_salary': ps.base_salary,
        'gross_salary': ps.gross_salary,
        'total_deductions': ps.total_deductions,
        'total_tax': ps.total_tax,
        'net_salary': ps.net_salary,
        'days_worked': ps.days_worked,
        'days_absent': ps.days_absent,
        'status': ps.status,
        'processed_by': ps.processed_by,
        'processed_at': ps.processed_at,
        'created_at': ps.created_at,
        'updated_at': ps.updated_at,
        'components': [
            {
                'id': c.id,
                'component_name': c.component_name,
                'component_type': c.component_type,
                'amount': c.amount,
            } for c in components
        ],
    })


@router.post('/payslips/{payslip_id}/approve', response_model=PayslipPublic)
def approve_payslip_endpoint(
    payslip_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a payslip (HR/Admin only)."""
    if not has_permission(user.role, 'process_payroll'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient privileges')
    
    ps = approve_payslip(payslip_id, user.id, db, tenant_id=user.tenant_id)
    
    return PayslipPublic.model_validate({
        'id': ps.id,
        'employee_id': ps.employee_id,
        'month': ps.month,
        'year': ps.year,
        'base_salary': ps.base_salary,
        'gross_salary': ps.gross_salary,
        'total_deductions': ps.total_deductions,
        'total_tax': ps.total_tax,
        'net_salary': ps.net_salary,
        'days_worked': ps.days_worked,
        'days_absent': ps.days_absent,
        'status': ps.status,
        'processed_by': ps.processed_by,
        'processed_at': ps.processed_at,
        'created_at': ps.created_at,
        'updated_at': ps.updated_at,
    })


@router.post('/payslips/{payslip_id}/mark-paid', response_model=PayslipPublic)
def mark_paid_endpoint(
    payslip_id: str,
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
):
    """Mark payslip as paid (HR/Admin only)."""
    ps = mark_payslip_paid(payslip_id, user.id, db, tenant_id=user.tenant_id)
    
    return PayslipPublic.model_validate({
        'id': ps.id,
        'employee_id': ps.employee_id,
        'month': ps.month,
        'year': ps.year,
        'base_salary': ps.base_salary,
        'gross_salary': ps.gross_salary,
        'total_deductions': ps.total_deductions,
        'total_tax': ps.total_tax,
        'net_salary': ps.net_salary,
        'days_worked': ps.days_worked,
        'days_absent': ps.days_absent,
        'status': ps.status,
        'processed_by': ps.processed_by,
        'processed_at': ps.processed_at,
        'created_at': ps.created_at,
        'updated_at': ps.updated_at,
    })


@router.get('/payslips/{payslip_id}/pdf')
def download_payslip_pdf(
    payslip_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download payslip as PDF."""
    ps = get_payslip(payslip_id, db, tenant_id=user.tenant_id)
    
    # Permission check: Employee can only download their own, others need Admin/HR role
    if ps.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_payroll'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not authorized to download this payslip')
    
    # Get payslip details
    payslip_data = get_payslip_details(payslip_id, db, tenant_id=user.tenant_id)
    
    # Generate PDF
    from app.core.payroll_utils import generate_payslip_pdf_bytes
    pdf_bytes = generate_payslip_pdf_bytes(payslip_data)
    
    if not pdf_bytes or isinstance(pdf_bytes, str):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='PDF generation failed')
    
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    month_name = month_names[payslip_data['month'] - 1]
    filename = f"Payslip_{month_name}_{payslip_data['year']}.pdf"
    
    return FileResponse(
        __import__('io').BytesIO(pdf_bytes),
        media_type='application/pdf',
        filename=filename
    )


@router.post('/payslips/{payslip_id}/send-email')
def send_payslip_email_endpoint(
    payslip_id: str,
    _user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
) -> dict:
    """Send payslip via email to employee."""
    try:
        success = send_payslip_email(payslip_id, db, tenant_id=_user.tenant_id)
        if success:
            return {'success': True, 'message': 'Payslip sent successfully'}
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Failed to send payslip email')
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f'Error sending email: {str(e)}')


@router.post('/runs', response_model=BatchPayrollResult)
def run_batch_payroll_endpoint(
    payload: BatchPayrollRequest,
    _user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
) -> BatchPayrollResult:
    """Run batch payroll for all active employees for a given month/year."""
    # Validate month and year
    if payload.month < 1 or payload.month > 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid month (must be 1-12)')
    
    if payload.year < 2000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid year')
    
    result = run_batch_payroll(payload.month, payload.year, db, tenant_id=_user.tenant_id)
    
    return BatchPayrollResult(**result)


@router.get('/salary-history', response_model=SalaryHistoryResponse)
def get_salary_history_endpoint(
    employee_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SalaryHistoryResponse:
    """Get salary history for an employee."""
    # Default to requesting user's own history
    if not employee_id:
        employee_id = resolve_employee_id(user, db)
    
    # Permission check: Employee can only view their own, others need Admin/HR role
    if employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_payroll'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not authorized to view this salary history')
    
    result = get_salary_history(employee_id, db, page=page, size=size, tenant_id=user.tenant_id)
    
    return SalaryHistoryResponse(**result)


@router.put('/salary', response_model=SalaryPublic)
def update_salary_endpoint(
    payload: UpdateSalaryRequest,
    employee_id: str = Query(...),
    user: User = Depends(require_permissions('process_payroll')),
    db: Session = Depends(get_db),
) -> SalaryPublic:
    """Update employee salary (create new salary entry and mark old as inactive)."""
    # Update salary and create history entry
    new_salary = update_salary(
        employee_id=employee_id,
        new_base_salary=payload.base_salary,
        grade=payload.grade,
        effective_from=payload.effective_from,
        reason=payload.reason,
        modified_by_id=user.id,
        db=db,
        tenant_id=user.tenant_id
    )
    
    return SalaryPublic.model_validate({
        'id': new_salary.id,
        'employee_id': new_salary.employee_id,
        'base_salary': new_salary.base_salary,
        'grade': new_salary.grade,
        'currency': new_salary.currency,
        'effective_from': new_salary.effective_from,
        'effective_to': new_salary.effective_to,
        'is_active': new_salary.is_active,
        'created_at': new_salary.created_at,
        'updated_at': new_salary.updated_at,
    })
