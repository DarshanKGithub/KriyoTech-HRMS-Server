"""Services for leave request lifecycle and balance calculations."""
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.http import HTTPException, status
import json

from app.db.models import LeaveRequest, LeaveType, LeaveBalance, Employee, AuditLog, Holiday

# File upload configuration
LEAVE_UPLOADS_DIR = Path(__file__).resolve().parents[2] / 'uploads' / 'leave_attachments'
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
ALLOWED_FILE_TYPES = {'pdf'}


def _ensure_leave_uploads_dir() -> None:
    LEAVE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def save_leave_attachment(leave_request_id: str, filename: str, content: bytes) -> str:
    """Save a file attachment for a leave request. Returns the file path."""
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='File is empty')

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail='File must be <= 10MB')

    # Extract file extension
    if '.' not in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid filename format')
    
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_FILE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'File type .{ext} not allowed')

    _ensure_leave_uploads_dir()

    # Save file with leave request ID in the name to organize by request
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    target_filename = f"{leave_request_id}_{unique_id}.{ext}"
    target = LEAVE_UPLOADS_DIR / target_filename

    target.write_bytes(content)
    return f"leave_attachments/{target_filename}"


def _days_between(start_date, end_date) -> int:
    # inclusive
    return (end_date - start_date).days + 1


def create_leave_request(employee_id: str, payload, db: Session, tenant_id: str | None = None) -> LeaveRequest:
    # payload: LeaveRequestCreate-like
    # Validate employee
    emp_query = db.query(Employee).filter(Employee.id == employee_id)
    if tenant_id:
        emp_query = emp_query.filter(Employee.tenant_id == tenant_id)
    emp = emp_query.with_for_update(of=Employee).first()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee not found')

    lt_query = db.query(LeaveType).filter(LeaveType.id == payload.leave_type_id, LeaveType.is_active.is_(True))
    if tenant_id:
        lt_query = lt_query.filter(LeaveType.tenant_id == tenant_id)
    lt = lt_query.first()
    if not lt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Leave type not found')

    if payload.start_date > payload.end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='start_date must be before end_date')

    if payload.start_date.year != payload.end_date.year:
        raise HTTPException(400, 'Submit separate leave requests for each calendar year')
    overlap = db.query(LeaveRequest).filter(LeaveRequest.employee_id == employee_id, LeaveRequest.status.in_(['pending', 'pending_manager', 'pending_hr', 'approved']), LeaveRequest.start_date <= payload.end_date, LeaveRequest.end_date >= payload.start_date).first()
    if overlap:
        raise HTTPException(409, 'This request overlaps existing leave')
    from datetime import timedelta
    from app.core.business_time import working_days
    holidays = {item.holiday_date for item in db.query(Holiday).filter(Holiday.tenant_id == tenant_id)} if tenant_id else set()
    dates = [payload.start_date + timedelta(days=i) for i in range(_days_between(payload.start_date, payload.end_date))]
    dates = [day for day in dates if day.weekday() in working_days(db, tenant_id) and day not in holidays] if tenant_id else dates
    days = float(len(dates))
    if dates and dates[0] == payload.start_date and payload.session_from == 'Session 2': days -= .5
    if dates and dates[-1] == payload.end_date and payload.session_to == 'Session 1': days -= .5
    if days <= 0:
        raise HTTPException(400, 'Select at least one working half-day')

    # Convert cc_to and attachment_paths lists to JSON strings
    cc_to_json = json.dumps(payload.cc_to) if payload.cc_to else None
    attachment_paths_json = json.dumps(payload.attachment_paths) if payload.attachment_paths else None

    lr = LeaveRequest(
        employee_id=employee_id,
        leave_type_id=payload.leave_type_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        session_from=payload.session_from or 'Session 1',
        session_to=payload.session_to or 'Session 2',
        days_requested=days,
        reason=payload.reason,
        contact_details=payload.contact_details,
        cc_to=cc_to_json,
        attachment_paths=attachment_paths_json,
        status='pending_manager' if emp.manager_id else 'pending_hr',
    )
    db.add(lr)
    from app.services.workflow_notifications import notify_employee
    notify_employee(db,employee_id,'leave_requested','A leave request is awaiting review.',roles=('HR','Admin','CEO') if not emp.manager_id else ())
    if emp.manager_id: notify_employee(db,emp.manager_id,'leave_requested','A direct report has requested leave.')
    db.commit()
    db.refresh(lr)

    # audit
    try:
        db.add(AuditLog(actor_id=employee_id, action='create', object_type='leave_request', object_id=lr.id, data=str({'employee_id': employee_id, 'days': days})))
        db.commit()
    except Exception:
        db.rollback()

    return lr


def get_leave_request(leave_id: str, db: Session, tenant_id: str | None = None) -> LeaveRequest:
    query = db.query(LeaveRequest)
    if tenant_id:
        query = query.join(Employee, LeaveRequest.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    lr = query.filter(LeaveRequest.id == leave_id).first()
    if not lr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Leave request not found')
    return lr


def list_leave_requests(db: Session, tenant_id: str | None = None, employee_id: str | None = None, manager_id: str | None = None, status_filter: str | None = None, page: int = 1, size: int = 20):
    from app.db.models import Employee
    query = db.query(LeaveRequest)
    
    if tenant_id or manager_id:
        query = query.join(Employee, LeaveRequest.employee_id == Employee.id)
        
    if tenant_id:
        query = query.filter(Employee.tenant_id == tenant_id)
        
    if employee_id:
        query = query.filter(LeaveRequest.employee_id == employee_id)
    if manager_id:
        query = query.filter(Employee.manager_id == manager_id)
    if status_filter:
        if status_filter == 'pending_all':
            query = query.filter(LeaveRequest.status.in_(['pending', 'pending_manager', 'pending_hr']))
        else:
            query = query.filter(LeaveRequest.status == status_filter)

    total = query.with_entities(func.count(LeaveRequest.id)).scalar() or 0
    items = query.order_by(LeaveRequest.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return items, int(total)


def _get_or_create_balance(employee_id: str, leave_type_id: str, year: int, db: Session) -> LeaveBalance:
    db.scalar(select(Employee).where(Employee.id == employee_id).with_for_update(of=Employee))
    bal = db.query(LeaveBalance).filter(LeaveBalance.employee_id == employee_id, LeaveBalance.leave_type_id == leave_type_id, LeaveBalance.year == year).with_for_update().first()
    if bal:
        return bal
    # try to create from LeaveType default
    lt = db.query(LeaveType).filter(LeaveType.id == leave_type_id).first()
    default_days = lt.default_days_per_year if lt else 0
    bal = LeaveBalance(employee_id=employee_id, leave_type_id=leave_type_id, year=year, granted_days=default_days, balance_days=default_days)
    db.add(bal)
    db.flush()
    return bal


def approve_leave(leave_id: str, approver_id: str, approve: bool, db: Session, tenant_id: str | None = None) -> LeaveRequest:
    from app.db.models import User
    # Lock the request and balance so concurrent approvals cannot deduct twice.
    lr = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).with_for_update().first()
    if not lr or tenant_id and lr.tenant_id != tenant_id:
        raise HTTPException(404, 'Leave request not found')
    if lr.status not in ['pending', 'pending_manager', 'pending_hr']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Leave request is not pending')

    user = db.query(User).filter(User.id == approver_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Approver not found')

    from app.services.auth_service import resolve_employee_id
    employee = db.get(Employee, lr.employee_id)
    if user.role == 'Manager' and (not employee or employee.manager_id != resolve_employee_id(user, db)):
        raise HTTPException(403, 'Only the assigned manager can review this request')
    if user.role not in {'Manager','HR','Admin','CEO'}:
        raise HTTPException(403, 'Your role cannot approve leave')
    if resolve_employee_id(user, db) == lr.employee_id:
        raise HTTPException(403, 'You cannot approve your own leave')

    if approve:
        if lr.status in ['pending', 'pending_manager']:
            # Move to HR approval
            lr.status = 'pending_hr'
            lr.updated_at = datetime.now()
            db.add(lr)
            from app.services.workflow_notifications import notify_employee
            notify_employee(db,lr.employee_id,'leave_'+lr.status,'Your leave request is now '+lr.status+'.')
            if lr.status=='pending_hr': notify_employee(db,lr.employee_id,'leave_review_required','A leave request needs final HR review.',roles=('HR','Admin','CEO'))
            db.commit()
            db.refresh(lr)
        elif lr.status == 'pending_hr':
            if user.role not in ['HR', 'Admin', 'CEO']:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only HR or Admin can finally approve')

            from app.db.models import Payslip
            first = lr.start_date.year * 12 + lr.start_date.month
            last = lr.end_date.year * 12 + lr.end_date.month
            if db.scalar(select(Payslip.id).where(Payslip.employee_id == lr.employee_id,
                    (Payslip.year * 12 + Payslip.month) >= first,
                    (Payslip.year * 12 + Payslip.month) <= last)):
                raise HTTPException(409, 'Payroll already exists for this period. Review payroll before approving leave.')

            year = lr.start_date.year
            bal = _get_or_create_balance(lr.employee_id, lr.leave_type_id, year, db)
            kind = db.get(LeaveType, lr.leave_type_id)
            if kind.is_paid and bal.balance_days < lr.days_requested:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Insufficient leave balance')
            if kind.is_paid:
                bal.balance_days -= lr.days_requested
                lr.deducted_days = lr.days_requested
            bal.updated_at = datetime.now()
            lr.status = 'approved'
            lr.approver_id = approver_id
            lr.approved_at = datetime.now()
            lr.updated_at = datetime.now()
            db.add(bal)
            db.add(lr)
            from app.services.workflow_notifications import notify_employee
            notify_employee(db,lr.employee_id,'leave_'+lr.status,'Your leave request is now '+lr.status+'.')
            if lr.status=='pending_hr': notify_employee(db,lr.employee_id,'leave_review_required','A leave request needs final HR review.',roles=('HR','Admin','CEO'))
            db.commit()
            db.refresh(lr)
    else:
        lr.status = 'rejected'
        lr.approver_id = approver_id
        lr.approved_at = datetime.now()
        lr.updated_at = datetime.now()
        db.add(lr)
        from app.services.workflow_notifications import notify_employee
        notify_employee(db,lr.employee_id,'leave_rejected','Your leave request was rejected.')
        db.commit()
        db.refresh(lr)

    try:
        db.add(AuditLog(actor_id=approver_id, action='approve' if approve else 'reject', object_type='leave_request', object_id=lr.id, data=str({'status': lr.status})))
        db.commit()
    except Exception:
        db.rollback()

    return lr


def get_leave_balances(employee_id: str, db: Session, tenant_id: str | None = None) -> list[LeaveBalance]:
    query = db.query(LeaveBalance).filter(LeaveBalance.employee_id == employee_id)
    if tenant_id:
        query = query.join(Employee, LeaveBalance.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    return query.all()


def bulk_approve_leave(request_ids: list[str], approver_id: str, approve: bool, db: Session, tenant_id: str | None = None) -> dict:
    processed = 0
    approved = 0
    rejected = 0
    failed = 0
    failed_ids: list[str] = []

    for request_id in request_ids:
        try:
            approve_leave(request_id, approver_id, approve, db, tenant_id)
            processed += 1
            if approve:
                approved += 1
            else:
                rejected += 1
        except Exception:
            db.rollback()
            failed += 1
            failed_ids.append(request_id)

    return {
        'processed': processed,
        'approved': approved,
        'rejected': rejected,
        'failed': failed,
        'failed_ids': failed_ids,
    }


def list_holidays(db: Session, year: int | None = None, tenant_id: str | None = None) -> list[Holiday]:
    query = db.query(Holiday)
    if tenant_id:
        query = query.filter(Holiday.tenant_id == tenant_id)
    if year is not None:
        start = datetime(year, 1, 1).date()
        end = datetime(year, 12, 31).date()
        query = query.filter(Holiday.holiday_date >= start, Holiday.holiday_date <= end)
    return query.order_by(Holiday.holiday_date.asc()).all()


def create_holiday(name: str, holiday_date, is_public: bool, db: Session, tenant_id: str | None = None) -> Holiday:
    query = db.query(Holiday).filter(Holiday.holiday_date == holiday_date, Holiday.name == name)
    if tenant_id:
        query = query.filter(Holiday.tenant_id == tenant_id)
    existing = query.first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Holiday already exists')

    holiday = Holiday(name=name, holiday_date=holiday_date, is_public=is_public, tenant_id=tenant_id)
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


def delete_holiday(holiday_id: str, db: Session, tenant_id: str | None = None) -> None:
    query = db.query(Holiday).filter(Holiday.id == holiday_id)
    if tenant_id:
        query = query.filter(Holiday.tenant_id == tenant_id)
    holiday = query.first()
    if not holiday:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Holiday not found')
    db.delete(holiday)
    db.commit()


def cancel_leave(leave_id,user,db):
    from decimal import Decimal
    from sqlalchemy import or_,and_
    from app.db.models import Payslip
    from app.core.business_time import business_today
    from app.services.auth_service import resolve_employee_id
    from app.services.workflow_notifications import notify_employee
    request=db.scalar(select(LeaveRequest).where(LeaveRequest.id==leave_id).with_for_update(of=LeaveRequest).execution_options(populate_existing=True))
    if not request: raise HTTPException(404,'Leave request not found')
    own=request.employee_id==resolve_employee_id(user,db)
    hr=user.role in {'HR','Admin','CEO'}
    if not own and not hr: raise HTTPException(403,'Only the requester or HR can cancel leave')
    if request.status=='cancelled': return request
    if request.status not in {'pending','pending_manager','pending_hr','approved'}:
        raise HTTPException(409,'This leave cannot be cancelled')
    if request.status=='approved':
        if not hr and request.start_date<business_today(db,user.tenant_id):
            raise HTTPException(403,'Contact HR to reverse past approved leave')
        first=request.start_date.year*12+request.start_date.month
        last=request.end_date.year*12+request.end_date.month
        payroll=db.scalar(select(Payslip.id).where(Payslip.employee_id==request.employee_id,(Payslip.year*12+Payslip.month)>=first,(Payslip.year*12+Payslip.month)<=last))
        if payroll: raise HTTPException(409,'Payroll already exists for this period. Review payroll before reversing leave.')
        if request.deducted_days is None:
            raise HTTPException(409,'Historical leave deduction requires HR review before reversal')
        if request.deducted_days:
            balance=_get_or_create_balance(request.employee_id,request.leave_type_id,request.start_date.year,db)
            balance.balance_days=min(Decimal(str(balance.granted_days)),Decimal(str(balance.balance_days))+Decimal(str(request.deducted_days)))
        request.deducted_days=0
    request.status='cancelled'
    request.updated_at=datetime.now()
    notify_employee(db,request.employee_id,'leave_cancelled','Your leave request has been cancelled. Any deducted balance has been restored.')
    db.add(AuditLog(actor_id=user.id,action='cancel',object_type='leave_request',object_id=request.id,data='Balance reversal applied once'))
    db.commit();db.refresh(request)
    return request
