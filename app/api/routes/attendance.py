from app.services.auth_service import resolve_employee_id
"""API routes for attendance and shift management."""

from datetime import date

from app.http import Router, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user, has_permission, require_permissions
from app.db.database import get_db
from app.db.models import User
from app.schemas.attendance import (
    ShiftCreate,
    ShiftPublic,
    PaginatedShifts,
    EmployeeShiftAssignmentCreate,
    EmployeeShiftAssignmentPublic,
    PaginatedEmployeeShiftAssignments,
    AttendanceCreate,
    AttendanceUpdate,
    AttendancePublic,
    PaginatedAttendance,
    CheckInRequest,
    CheckOutRequest,
    StartBreakRequest,
    EndBreakRequest,
    EmployeeAttendanceSummary,
)
from app.services.shift_service import (
    create_shift,
    get_shift,
    list_shifts,
    assign_shift_to_employee,
    get_employee_shift_assignment,
    list_employee_shift_assignments,
)
from app.services.attendance_service import (
    create_attendance,
    start_break,
    end_break,
    get_attendance,
    check_in,
    check_out,
    list_attendance,
    update_attendance,
    delete_attendance,
    get_employee_attendance_summary,
)
from app.http import StreamingResponse
import io
import csv
try:
    import openpyxl
except Exception:
    openpyxl = None
router = Router()


@router.get('/rules')
def attendance_rules(db: Session = Depends(get_db), user: User = Depends(require_permissions('manage_shifts'))):
    from sqlalchemy import select
    from app.db.models import AttendanceRule
    return [dict(id=row.id, name=row.name, rule_type=row.rule_type,
                 threshold_minutes=row.threshold_minutes, is_active=row.is_active)
            for row in db.scalars(select(AttendanceRule).where(AttendanceRule.tenant_id == user.tenant_id))]


from app.schemas.attendance import AttendanceRuleCreate


@router.post('/rules')
def save_attendance_rule(payload: AttendanceRuleCreate, db: Session = Depends(get_db), user: User = Depends(require_permissions('manage_shifts'))):
    from sqlalchemy import select
    from app.db.models import AttendanceRule, AuditLog
    if payload.rule_type not in {'late_entry', 'early_exit', 'half_day'}:
        raise HTTPException(400, 'Unsupported attendance rule type')
    if not payload.name.strip() or len(payload.name) > 120 or not 0 <= payload.threshold_minutes <= 1440:
        raise HTTPException(400, 'Provide a name and a threshold between 0 and 1440 minutes')
    row = db.scalar(select(AttendanceRule).where(AttendanceRule.tenant_id == user.tenant_id, AttendanceRule.rule_type == payload.rule_type).with_for_update(of=AttendanceRule))
    if row is None:
        row = AttendanceRule(tenant_id=user.tenant_id, **payload.model_dump())
        db.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    db.flush()
    db.add(AuditLog(actor_id=user.id, action='update', object_type='attendance_rule', object_id=row.id, data=payload.model_dump_json()))
    db.commit()
    return dict(id=row.id, name=row.name, rule_type=row.rule_type, threshold_minutes=row.threshold_minutes, is_active=row.is_active)


def _attendance_to_dict(a) -> dict:
    return {
        'id': a.id,
        'employee_id': a.employee_id,
        'attendance_date': a.attendance_date,
        'check_in_time': a.check_in_time,
        'check_in_latitude': getattr(a, 'check_in_latitude', None),
        'check_in_longitude': getattr(a, 'check_in_longitude', None),
        'check_out_time': a.check_out_time,
        'check_out_latitude': getattr(a, 'check_out_latitude', None),
        'check_out_longitude': getattr(a, 'check_out_longitude', None),
        'status': a.status,
        'is_late': a.is_late,
        'late_minutes': a.late_minutes,
        'is_half_day': a.is_half_day,
        'is_work_from_home': a.is_work_from_home,
        'notes': a.notes,
        'created_at': a.created_at,
        'updated_at': a.updated_at,
        'breaks': [
            {
                'id': b.id,
                'attendance_id': b.attendance_id,
                'break_type': b.break_type,
                'start_time': b.start_time,
                'end_time': b.end_time,
                'created_at': b.created_at,
            }
            for b in getattr(a, 'breaks', [])
        ],
    }


# ==================== Shift Routes ====================


@router.post('/shifts', response_model=ShiftPublic)
def create_shift_endpoint(
    payload: ShiftCreate,
    _user: User = Depends(require_permissions('manage_shifts')),
    db: Session = Depends(get_db),
) -> ShiftPublic:
    """Create a new shift (Admin/HR only)."""
    shift = create_shift(payload, db)
    return ShiftPublic.model_validate(shift, from_attributes=True)


@router.get('/shifts/{shift_id}', response_model=ShiftPublic)
def get_shift_endpoint(
    shift_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShiftPublic:
    """Retrieve a shift by ID."""
    shift = get_shift(shift_id, db)
    return ShiftPublic.model_validate(shift, from_attributes=True)


@router.get('/shifts', response_model=PaginatedShifts)
def list_shifts_endpoint(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedShifts:
    """List all shifts with pagination."""
    shifts, total = list_shifts(db, page=page, size=size)
    return PaginatedShifts(
        items=[ShiftPublic.model_validate(s, from_attributes=True) for s in shifts],
        total=total,
        page=page,
        size=size,
    )


# ==================== Employee Shift Assignment Routes ====================


@router.post('/employees/{employee_id}/shift-assignment', response_model=EmployeeShiftAssignmentPublic)
def assign_shift_endpoint(
    employee_id: str,
    payload: EmployeeShiftAssignmentCreate,
    _user: User = Depends(require_permissions('manage_shifts')),
    db: Session = Depends(get_db),
) -> EmployeeShiftAssignmentPublic:
    """Assign a shift to an employee (Admin/HR only)."""
    # Ensure employee_id matches payload
    if payload.employee_id != employee_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Employee ID mismatch')

    assignment = assign_shift_to_employee(payload, db)
    return EmployeeShiftAssignmentPublic.model_validate(assignment, from_attributes=True)


@router.get('/employees/{employee_id}/shift-assignments', response_model=PaginatedEmployeeShiftAssignments)
def list_employee_shift_assignments_endpoint(
    employee_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedEmployeeShiftAssignments:
    """List shift assignments for an employee."""
    assignments, total = list_employee_shift_assignments(db, employee_id=employee_id, page=page, size=size)
    return PaginatedEmployeeShiftAssignments(
        items=[EmployeeShiftAssignmentPublic.model_validate(a, from_attributes=True) for a in assignments],
        total=total,
        page=page,
        size=size,
    )


# ==================== Attendance Routes ====================


@router.post('/check-in', response_model=AttendancePublic)
def check_in_endpoint(
    payload: CheckInRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttendancePublic:
    """Record check-in for an employee."""
    # Allow self check-in for employees/workers. Others require elevated attendance permission.
    if payload.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'approve_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot check in for other employees')

    attendance = check_in(payload, db, tenant_id=user.tenant_id)
    return AttendancePublic.model_validate(_attendance_to_dict(attendance))


@router.post('/check-out', response_model=AttendancePublic)
def check_out_endpoint(
    payload: CheckOutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttendancePublic:
    """Record check-out for an employee."""
    # Allow self check-out for employees/workers. Others require elevated attendance permission.
    if payload.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'approve_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot check out for other employees')

    attendance = check_out(payload, db, tenant_id=user.tenant_id)
    return AttendancePublic.model_validate(_attendance_to_dict(attendance))


@router.post('/start-break', response_model=AttendancePublic)
def start_break_endpoint(
    payload: StartBreakRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttendancePublic:
    """Record break start for an employee."""
    if payload.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'approve_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot start break for other employees')

    attendance = start_break(payload, db, tenant_id=user.tenant_id)
    return AttendancePublic.model_validate(_attendance_to_dict(attendance))


@router.post('/end-break', response_model=AttendancePublic)
def end_break_endpoint(
    payload: EndBreakRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttendancePublic:
    """Record break end for an employee."""
    if payload.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'approve_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot end break for other employees')

    attendance = end_break(payload, db, tenant_id=user.tenant_id)
    return AttendancePublic.model_validate(_attendance_to_dict(attendance))


@router.get('/', response_model=PaginatedAttendance)
def list_attendance_endpoint(
    employee_id: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedAttendance:
    """List attendance records with optional filters."""
    # Non-elevated users can only view their own attendance.
    if employee_id and employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees attendance')

    if not employee_id and not has_permission(user.role, 'view_attendance'):
        employee_id = resolve_employee_id(user, db)

    records, total = list_attendance(db, tenant_id=user.tenant_id, employee_id=employee_id, start_date=start_date, end_date=end_date, page=page, size=size)
    return PaginatedAttendance(
        items=[AttendancePublic.model_validate(_attendance_to_dict(r)) for r in records],
        total=total,
        page=page,
        size=size,
    )


@router.get('/summary/{employee_id}', response_model=EmployeeAttendanceSummary)
def get_attendance_summary_endpoint(
    employee_id: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmployeeAttendanceSummary:
    """Get attendance summary for an employee."""
    if employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees attendance')

    if start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='start_date must be before end_date')

    return get_employee_attendance_summary(employee_id, start_date, end_date, db, tenant_id=user.tenant_id)


@router.get('/{attendance_id}', response_model=AttendancePublic)
def get_attendance_endpoint(
    attendance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttendancePublic:
    """Retrieve an attendance record by ID."""
    attendance = get_attendance(attendance_id, db, tenant_id=user.tenant_id)
    if attendance.employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employees attendance')
    return AttendancePublic.model_validate(_attendance_to_dict(attendance))


@router.patch('/{attendance_id}', response_model=AttendancePublic)
def update_attendance_endpoint(
    attendance_id: str,
    payload: AttendanceUpdate,
    _user: User = Depends(require_permissions('manage_attendance_records')),
    db: Session = Depends(get_db),
) -> AttendancePublic:
    """Adjust an attendance record (Admin/HR only)."""
    attendance = update_attendance(attendance_id, payload, db, tenant_id=_user.tenant_id)
    return AttendancePublic.model_validate(_attendance_to_dict(attendance))


@router.delete('/{attendance_id}', response_model=AttendancePublic)
def delete_attendance_endpoint(
    attendance_id: str,
    _user: User = Depends(require_permissions('manage_attendance_records')),
    db: Session = Depends(get_db),
) -> AttendancePublic:
    """Delete an attendance record (Admin/HR only)."""
    attendance = delete_attendance(attendance_id, db, tenant_id=_user.tenant_id)
    return AttendancePublic.model_validate(_attendance_to_dict(attendance))


@router.get('/export', responses={200: {'content': {'text/csv': {}}}})
def export_attendance_endpoint(
    employee_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    fmt: str = Query('csv'),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export monthly attendance for an employee. Supports CSV and XLSX (if openpyxl installed)."""
    if employee_id != resolve_employee_id(user, db) and not has_permission(user.role, 'view_attendance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot export other employee reports')

    # build start and end dates for month
    from calendar import monthrange
    start_date = date(year, month, 1)
    end_date = date(year, month, monthrange(year, month)[1])

    summary = get_employee_attendance_summary(employee_id, start_date, end_date, db, tenant_id=user.tenant_id)

    filename = f"Attendance_{summary.employee_id}_{start_date.strftime('%B%Y')}"

    if fmt == 'xlsx' and openpyxl is not None:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Attendance'
        headers = ['Date', 'Status', 'Check In', 'Check Out', 'Hours', 'Is Late', 'Is Half Day']
        ws.append(headers)
        for r in summary.records:
            hours = 0
            if r.check_in_time and r.check_out_time:
                try:
                    delta = r.check_out_time - r.check_in_time
                    hours = round(delta.total_seconds() / 3600, 2)
                except Exception:
                    hours = 0
            ws.append([
                r.date.isoformat(),
                r.status,
                getattr(r.check_in_time, 'isoformat', lambda: '')() if r.check_in_time else '',
                getattr(r.check_out_time, 'isoformat', lambda: '')() if r.check_out_time else '',
                hours,
                'Yes' if r.is_late else 'No',
                'Yes' if r.is_half_day else 'No',
            ])
        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)
        return StreamingResponse(stream, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={
            'Content-Disposition': f'attachment; filename="{filename}.xlsx"'
        })

    # default CSV
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Date', 'Status', 'Check In', 'Check Out', 'Hours', 'Is Late', 'Is Half Day'])
    for r in summary.records:
        hours = 0
        if r.check_in_time and r.check_out_time:
            try:
                delta = r.check_out_time - r.check_in_time
                hours = round(delta.total_seconds() / 3600, 2)
            except Exception:
                hours = 0
        writer.writerow([
            r.date.isoformat(),
            r.status,
            r.check_in_time.isoformat() if r.check_in_time else '',
            r.check_out_time.isoformat() if r.check_out_time else '',
            hours,
            'Yes' if r.is_late else 'No',
            'Yes' if r.is_half_day else 'No',
        ])
    out.seek(0)
    return StreamingResponse(io.BytesIO(out.getvalue().encode('utf-8')), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{filename}.csv"'})
