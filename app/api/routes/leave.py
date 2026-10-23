from app.services.auth_service import resolve_employee_id
"""API routes for Leave Management (Phase 5)."""
from datetime import date
import json

from app.http import Router, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user, has_permission
from app.db.database import get_db
from app.db.models import User
from app.schemas.leave import (
    LeaveRequestCreate,
    LeaveRequestPublic,
    PaginatedLeaveRequests,
    ApprovePayload,
    LeaveBalancePublic,
    BulkApprovePayload,
    BulkApproveResult,
    HolidayCreate,
    HolidayPublic,
    LeaveHistoryItem,
    CCOptionsPublic,
)
from app.services.leave_service import (
    create_leave_request,
    list_leave_requests,
    get_leave_request,
    approve_leave,
    get_leave_balances,
    save_leave_attachment,
    bulk_approve_leave,
    list_holidays,
    create_holiday,
    delete_holiday,
)
router = Router()


@router.get('/types', response_model=list)
def get_leave_types(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all active leave types."""
    from app.db.models import LeaveType
    leave_types = db.query(LeaveType).filter(LeaveType.is_active.is_(True)).all()
    
    return [
        {
            'id': lt.id,
            'name': lt.name,
            'description': lt.description,
            'default_days_per_year': lt.default_days_per_year,
        }
        for lt in leave_types
    ]


@router.post('/requests', response_model=LeaveRequestPublic)
def request_leave_endpoint(
    payload: LeaveRequestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeaveRequestPublic:
    # user.id is user.id; map to employee id: login returns employee_id in user payload when available
    employee_id = resolve_employee_id(user, db)
    # create_leave_request will validate employee existence
    lr = create_leave_request(employee_id, payload, db, tenant_id=user.tenant_id)
    return LeaveRequestPublic.model_validate({
        'id': lr.id,
        'employee_id': lr.employee_id,
            'employee_name': getattr(lr.employee, 'full_name', None) if getattr(lr, 'employee', None) else None,
        'leave_type_id': lr.leave_type_id,
        'start_date': lr.start_date,
        'end_date': lr.end_date,
        'session_from': lr.session_from,
        'session_to': lr.session_to,
        'days_requested': lr.days_requested,
        'reason': lr.reason,
        'contact_details': lr.contact_details,
        'cc_to': lr.cc_to,
        'attachment_paths': lr.attachment_paths,
        'status': lr.status,
        'approver_id': lr.approver_id,
        'approved_at': lr.approved_at,
        'created_at': lr.created_at,
        'updated_at': lr.updated_at,
    })


@router.get('/requests', response_model=PaginatedLeaveRequests)
def list_requests_endpoint(
    employee_id: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedLeaveRequests:
    if employee_id and employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees requests')

    if not employee_id and not has_permission(user.role, 'view_leave'):
        employee_id = resolve_employee_id(user, db)

    items, total = list_leave_requests(db, tenant_id=user.tenant_id, employee_id=employee_id, status_filter=status, page=page, size=size)
    return PaginatedLeaveRequests(
        items=[LeaveRequestPublic.model_validate({
            'id': r.id,
            'employee_id': r.employee_id,
            'employee_name': getattr(r.employee, 'full_name', None) if getattr(r, 'employee', None) else None,
            'leave_type_id': r.leave_type_id,
            'start_date': r.start_date,
            'end_date': r.end_date,
            'session_from': r.session_from,
            'session_to': r.session_to,
            'days_requested': r.days_requested,
            'reason': r.reason,
            'contact_details': r.contact_details,
            'cc_to': r.cc_to,
            'attachment_paths': r.attachment_paths,
            'status': r.status,
            'approver_id': r.approver_id,
            'approved_at': r.approved_at,
            'created_at': r.created_at,
            'updated_at': r.updated_at,
        }) for r in items],
        total=total,
        page=page,
        size=size,
    )


@router.get('/requests/team', response_model=PaginatedLeaveRequests)
def list_team_requests_endpoint(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedLeaveRequests:
    """Fetch leave requests for employees managed by the current user."""
    if user.role not in ['Admin', 'HR', 'Manager']:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient privileges')

    manager_id = resolve_employee_id(user, db)
    items, total = list_leave_requests(db, tenant_id=user.tenant_id, manager_id=manager_id, status_filter=status, page=page, size=size)
    return PaginatedLeaveRequests(
        items=[LeaveRequestPublic.model_validate({
            'id': r.id,
            'employee_id': r.employee_id,
            'employee_name': getattr(r.employee, 'full_name', None) if getattr(r, 'employee', None) else None,
            'leave_type_id': r.leave_type_id,
            'start_date': r.start_date,
            'end_date': r.end_date,
            'session_from': r.session_from,
            'session_to': r.session_to,
            'days_requested': r.days_requested,
            'reason': r.reason,
            'contact_details': r.contact_details,
            'cc_to': r.cc_to,
            'attachment_paths': r.attachment_paths,
            'status': r.status,
            'approver_id': r.approver_id,
            'approved_at': r.approved_at,
            'created_at': r.created_at,
            'updated_at': r.updated_at,
        }) for r in items],
        total=total,
        page=page,
        size=size,
    )


@router.get('/requests/{request_id}', response_model=LeaveRequestPublic)
def get_request_endpoint(
    request_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lr = get_leave_request(request_id, db, tenant_id=user.tenant_id)
    if lr.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees requests')

    return LeaveRequestPublic.model_validate({
        'id': lr.id,
        'employee_id': lr.employee_id,
            'employee_name': getattr(lr.employee, 'full_name', None) if getattr(lr, 'employee', None) else None,
        'leave_type_id': lr.leave_type_id,
        'start_date': lr.start_date,
        'end_date': lr.end_date,
        'session_from': lr.session_from,
        'session_to': lr.session_to,
        'days_requested': lr.days_requested,
        'reason': lr.reason,
        'contact_details': lr.contact_details,
        'cc_to': lr.cc_to,
        'attachment_paths': lr.attachment_paths,
        'status': lr.status,
        'approver_id': lr.approver_id,
        'approved_at': lr.approved_at,
        'created_at': lr.created_at,
        'updated_at': lr.updated_at,
    })


@router.post('/requests/{request_id}/approve', response_model=LeaveRequestPublic)
def approve_request_endpoint(
    request_id: str,
    payload: ApprovePayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user.role, 'approve_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient privileges')

    # For Manager role, ensure they are manager of the employee
    lr = get_leave_request(request_id, db, tenant_id=user.tenant_id)
    if user.role == 'Manager':
        # ensure manager relationship (employee.manager_id == user.id)
        from app.db.models import Employee
        emp = db.query(Employee).filter(Employee.id == lr.employee_id).first()
        if not emp or emp.manager_id != resolve_employee_id(user, db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not authorized to approve this request')

    updated = approve_leave(request_id, user.id, payload.approve, db, tenant_id=user.tenant_id)
    return LeaveRequestPublic.model_validate({
        'id': updated.id,
        'employee_id': updated.employee_id,
            'employee_name': getattr(updated.employee, 'full_name', None) if getattr(updated, 'employee', None) else None,
        'leave_type_id': updated.leave_type_id,
        'start_date': updated.start_date,
        'end_date': updated.end_date,
        'session_from': updated.session_from,
        'session_to': updated.session_to,
        'days_requested': updated.days_requested,
        'reason': updated.reason,
        'contact_details': updated.contact_details,
        'cc_to': updated.cc_to,
        'attachment_paths': updated.attachment_paths,
        'status': updated.status,
        'approver_id': updated.approver_id,
        'approved_at': updated.approved_at,
        'created_at': updated.created_at,
        'updated_at': updated.updated_at,
    })


@router.post('/requests/bulk-approve', response_model=BulkApproveResult)
def bulk_approve_requests_endpoint(
    payload: BulkApprovePayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user.role, 'approve_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient privileges')

    if not payload.request_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='request_ids cannot be empty')

    result = bulk_approve_leave(payload.request_ids, user.id, payload.approve, db, tenant_id=user.tenant_id)
    return BulkApproveResult.model_validate(result, from_attributes=True)


@router.get('/balances', response_model=list[LeaveBalancePublic])
def balances_endpoint(
    employee_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if employee_id and employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees balances')

    if not employee_id:
        employee_id = resolve_employee_id(user, db)

    balances = get_leave_balances(employee_id, db)
    out = []
    for b in balances:
        out.append(LeaveBalancePublic.model_validate({
            'id': b.id,
            'employee_id': b.employee_id,
            'leave_type_id': b.leave_type_id,
            'year': b.year,
            'granted_days': b.granted_days,
            'balance_days': b.balance_days,
            'created_at': b.created_at,
            'updated_at': b.updated_at,
        }))
    return out


@router.get('/balances/with-details')
def balances_with_details_endpoint(
    employee_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get leave balances with leave type details (name, description)."""
    if employee_id and employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees balances')

    if not employee_id:
        employee_id = resolve_employee_id(user, db)

    balances = get_leave_balances(employee_id, db)
    out = []
    for b in balances:
        out.append({
            'id': b.id,
            'employee_id': b.employee_id,
            'leave_type_id': b.leave_type_id,
            'leave_type_name': b.leave_type.name if getattr(b, 'leave_type', None) else 'Unknown',
            'year': b.year,
            'granted_days': b.granted_days,
            'balance_days': b.balance_days,
            'created_at': b.created_at.isoformat(),
            'updated_at': b.updated_at.isoformat(),
        })
    return out


@router.get('/holidays', response_model=list[HolidayPublic])
def list_holidays_endpoint(
    year: int | None = Query(None),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    holidays = list_holidays(db, year=year, tenant_id=_user.tenant_id)
    return [
        HolidayPublic.model_validate(
            {
                'id': holiday.id,
                'name': holiday.name,
                'holiday_date': holiday.holiday_date,
                'is_public': holiday.is_public,
                'created_at': holiday.created_at,
            }
        )
        for holiday in holidays
    ]


@router.post('/holidays', response_model=HolidayPublic)
def create_holiday_endpoint(
    payload: HolidayCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user.role, 'approve_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient privileges')

    holiday = create_holiday(payload.name, payload.holiday_date, payload.is_public, db, tenant_id=user.tenant_id)
    return HolidayPublic.model_validate(
        {
            'id': holiday.id,
            'name': holiday.name,
            'holiday_date': holiday.holiday_date,
            'is_public': holiday.is_public,
            'created_at': holiday.created_at,
        }
    )


@router.delete('/holidays/{holiday_id}')
def delete_holiday_endpoint(
    holiday_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not has_permission(user.role, 'approve_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient privileges')

    delete_holiday(holiday_id, db, tenant_id=user.tenant_id)
    return {'ok': True}


@router.post('/requests/{request_id}/upload')
def upload_leave_attachment(
    request_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an attachment file for a leave request."""
    # Verify the leave request exists and belongs to the user or user is authorized to approve
    lr = get_leave_request(request_id, db, tenant_id=user.tenant_id)
    if lr.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'approve_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot upload files for other employees')

    # Save the file
    content = file.file.read()
    file_path = save_leave_attachment(request_id, file.filename or 'file', content)
    
    return {'file_path': file_path, 'filename': file.filename}


@router.get('/cc-options', response_model=CCOptionsPublic)
def get_cc_options(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models import Employee
    employee = db.query(Employee).filter(Employee.id == user.id).first()
    
    manager = None
    if employee and employee.manager_id:
        mgr_user = db.query(User).filter(User.id == employee.manager_id).first()
        if mgr_user:
            manager = {
                'id': mgr_user.id,
                'name': mgr_user.full_name,
                'email': mgr_user.email,
                'role': mgr_user.role,
            }
            
    hrs = db.query(User).filter(User.role == 'HR', User.is_active == True, User.tenant_id == user.tenant_id).all()
    ceos = db.query(User).filter(User.role == 'CEO', User.is_active == True, User.tenant_id == user.tenant_id).all()
    
    hr_list = [{'id': hr.id, 'name': hr.full_name, 'email': hr.email, 'role': hr.role} for hr in hrs]
    ceo_list = [{'id': ceo.id, 'name': ceo.full_name, 'email': ceo.email, 'role': ceo.role} for ceo in ceos]
    
    return CCOptionsPublic(manager=manager, hr=hr_list, ceo=ceo_list)


@router.get('/requests/{request_id}/history', response_model=list[LeaveHistoryItem])
def get_leave_history(
    request_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models import AuditLog
    # Ensure user can view this request
    lr = get_leave_request(request_id, db, tenant_id=user.tenant_id)
    if lr.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_leave'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees requests')

    logs = db.query(AuditLog).filter(
        AuditLog.object_type == 'leave_request',
        AuditLog.object_id == request_id
    ).order_by(AuditLog.created_at.asc()).all()
    
    history = []
    for log in logs:
        actor_name = None
        if log.actor_id:
            actor = db.query(User).filter(User.id == log.actor_id).first()
            if actor:
                actor_name = actor.full_name
        
        if not actor_name and log.action == 'create' and getattr(lr, 'employee', None):
            actor_name = lr.employee.full_name

        history.append({
            'id': log.id,
            'action': log.action,
            'actor_name': actor_name,
            'created_at': log.created_at
        })
        
    return history


@router.post('/requests/{request_id}/cancel',response_model=LeaveRequestPublic)
def cancel_request_endpoint(request_id: str,user: User = Depends(get_current_user),db: Session = Depends(get_db)):
    from app.services.leave_service import cancel_leave
    return LeaveRequestPublic.model_validate(cancel_leave(request_id,user,db),from_attributes=True)
