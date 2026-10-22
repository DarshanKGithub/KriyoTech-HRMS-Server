from datetime import date
from typing import Tuple, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.http import HTTPException, status

from app.db.models import (
    Timesheet,
    OvertimeRequest,
    AttendanceRegularization,
    CompOffRequest,
    BiometricDevice,
    BiometricLog,
    Roster,
    RosterEntry,
    Attendance
)
from app.schemas.advanced_attendance import (
    TimesheetCreate,
    OvertimeRequestCreate,
    AttendanceRegularizationCreate,
    CompOffRequestCreate,
    BiometricDeviceCreate,
    BiometricLogCreate,
    RosterCreate,
    RosterEntryCreate
)


# --- Attendance Regularization ---

def _normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()

def create_attendance_regularization(payload: AttendanceRegularizationCreate, db: Session) -> AttendanceRegularization:
    existing = (
        db.query(AttendanceRegularization)
        .filter(
            AttendanceRegularization.employee_id == payload.employee_id,
            AttendanceRegularization.date == payload.date,
            AttendanceRegularization.status == 'Pending',
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='A pending regularization already exists for this date',
        )

    if payload.attendance_id:
        linked = db.get(Attendance, payload.attendance_id)
        if not linked or linked.employee_id != payload.employee_id or linked.attendance_date != payload.date:
            raise HTTPException(400, 'Attendance must match the employee and date')
    if payload.requested_check_in and payload.requested_check_out and payload.requested_check_out <= payload.requested_check_in:
        raise HTTPException(400, 'Checkout must follow check-in')
    payload_data = payload.model_dump()
    if payload_data.get('attendance_id') is None:
        attendance = (
            db.query(Attendance)
            .filter(
                Attendance.employee_id == payload.employee_id,
                Attendance.attendance_date == payload.date,
            )
            .first()
        )
        if attendance:
            payload_data['attendance_id'] = attendance.id

    reg = AttendanceRegularization(**payload_data)
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return reg


def get_regularizations(
    db: Session,
    employee_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    size: int = 20
) -> Tuple[List[AttendanceRegularization], int]:
    query = db.query(AttendanceRegularization)
    if employee_id:
        query = query.filter(AttendanceRegularization.employee_id == employee_id)
    if status_filter:
        query = query.filter(AttendanceRegularization.status == status_filter)
    
    total = query.count()
    items = query.order_by(desc(AttendanceRegularization.created_at)).offset((page - 1) * size).limit(size).all()
    return items, total


def approve_regularization(reg_id: str, approver_id: str, db: Session) -> AttendanceRegularization:
    reg = db.query(AttendanceRegularization).filter(AttendanceRegularization.id == reg_id).with_for_update().populate_existing().first()
    if not reg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regularization not found")
    
    if reg.status != 'Pending':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be approved")
    
    actor = db.info.get('actor')
    if actor and reg.employee_id == actor.employee_id:
        raise HTTPException(403, 'You cannot approve your own correction')
    reg.status = 'Approved' 
    reg.approver_id = approver_id
    
    # Update the actual attendance record
    if reg.attendance_id:
        attendance = db.query(Attendance).filter(Attendance.id == reg.attendance_id).first()
    else:
        # Create a new attendance record for that date
        attendance = db.query(Attendance).filter(
            Attendance.employee_id == reg.employee_id,
            Attendance.attendance_date == reg.date
        ).first()
        if not attendance:
            attendance = Attendance(
                employee_id=reg.employee_id,
                attendance_date=reg.date,
                status='present'
            )
            db.add(attendance)
            db.flush()
            reg.attendance_id = attendance.id

    if attendance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    if attendance.employee_id != reg.employee_id or attendance.attendance_date != reg.date:
        raise HTTPException(400, 'Attendance must match the employee and date')
    start = reg.requested_check_in or attendance.check_in_time
    end = reg.requested_check_out or attendance.check_out_time
    if start and end:
        from datetime import timezone
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
        end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
        if end <= start:
            raise HTTPException(400, 'Checkout must follow check-in')
    if reg.requested_check_in:
        attendance.check_in_time = reg.requested_check_in
    if reg.requested_check_out:
        attendance.check_out_time = reg.requested_check_out
    from app.services.attendance_service import AttendanceRuleEngine
    from app.services.shift_service import get_employee_current_shift
    from app.core.business_time import local_time
    rules = AttendanceRuleEngine(db, reg.tenant_id)
    shift = get_employee_current_shift(reg.employee_id, reg.date, db)
    if attendance.check_in_time:
        minutes = rules.calculate_late_minutes(local_time(attendance.check_in_time, db, reg.tenant_id), shift)
        attendance.late_minutes = minutes
        attendance.is_late = rules.is_late_entry(minutes)
        attendance.status = 'present'
    if attendance.check_in_time and attendance.check_out_time:
        breaks = sum(rules.calculate_working_hours(item.start_time, item.end_time) for item in attendance.breaks if item.end_time)
        hours = rules.calculate_working_hours(attendance.check_in_time, attendance.check_out_time, breaks)
        attendance.is_half_day = rules.is_half_day(hours)
    db.commit()
    db.refresh(reg)
    return reg


def reject_regularization(reg_id: str, approver_id: str, db: Session) -> AttendanceRegularization:
    reg = db.query(AttendanceRegularization).filter(AttendanceRegularization.id == reg_id).with_for_update().populate_existing().first()
    if not reg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regularization not found")
    
    if reg.status != 'Pending':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be rejected")
    
    reg.status = 'Rejected'
    reg.approver_id = approver_id
    db.commit()
    db.refresh(reg)
    return reg


# --- Scaffolds for other Step 3 functionalities ---

def create_timesheet(payload: TimesheetCreate, db: Session) -> Timesheet:
    ts = Timesheet(**payload.model_dump())
    db.add(ts)
    db.commit()
    db.refresh(ts)
    return ts


def get_timesheets(
    db: Session,
    employee_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    size: int = 20
) -> Tuple[List[Timesheet], int]:
    query = db.query(Timesheet)
    if employee_id:
        query = query.filter(Timesheet.employee_id == employee_id)
    if status_filter:
        query = query.filter(Timesheet.status == status_filter)
    
    total = query.count()
    items = query.order_by(desc(Timesheet.created_at)).offset((page - 1) * size).limit(size).all()
    return items, total


def update_timesheet(ts_id: str, payload: TimesheetCreate, user_id: str, db: Session) -> Timesheet:
    ts = db.query(Timesheet).filter(Timesheet.id == ts_id).first()
    if not ts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timesheet not found")
    
    if ts.status != 'Draft':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only draft timesheets can be updated")
    
    for key, value in payload.model_dump().items():
        setattr(ts, key, value)
    
    db.commit()
    db.refresh(ts)
    return ts


def create_overtime_request(payload: OvertimeRequestCreate, db: Session) -> OvertimeRequest:
    ot = OvertimeRequest(**payload.model_dump())
    db.add(ot)
    db.commit()
    db.refresh(ot)
    return ot


def get_overtime_requests(
    db: Session,
    employee_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    size: int = 20
) -> Tuple[List[OvertimeRequest], int]:
    query = db.query(OvertimeRequest)
    if employee_id:
        query = query.filter(OvertimeRequest.employee_id == employee_id)
    if status_filter:
        query = query.filter(OvertimeRequest.status == status_filter)
    
    total = query.count()
    items = query.order_by(desc(OvertimeRequest.created_at)).offset((page - 1) * size).limit(size).all()
    return items, total


def approve_overtime(ot_id: str, approver_id: str, db: Session) -> OvertimeRequest:
    ot = db.query(OvertimeRequest).filter(OvertimeRequest.id == ot_id).first()
    if not ot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Overtime request not found")
    
    if ot.status != 'Pending':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be approved")
    
    ot.status = 'Approved'
    ot.approver_id = approver_id
    db.commit()
    db.refresh(ot)
    return ot


def reject_overtime(ot_id: str, approver_id: str, db: Session) -> OvertimeRequest:
    ot = db.query(OvertimeRequest).filter(OvertimeRequest.id == ot_id).first()
    if not ot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Overtime request not found")
    
    if ot.status != 'Pending':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be rejected")
    
    ot.status = 'Rejected'
    ot.approver_id = approver_id
    db.commit()
    db.refresh(ot)
    return ot


def create_comp_off_request(payload: CompOffRequestCreate, db: Session) -> CompOffRequest:
    co = CompOffRequest(**payload.model_dump())
    db.add(co)
    db.commit()
    db.refresh(co)
    return co


def get_comp_off_requests(
    db: Session,
    employee_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    size: int = 20
) -> Tuple[List[CompOffRequest], int]:
    query = db.query(CompOffRequest)
    if employee_id:
        query = query.filter(CompOffRequest.employee_id == employee_id)
    if status_filter:
        query = query.filter(CompOffRequest.status == status_filter)
    
    total = query.count()
    items = query.order_by(desc(CompOffRequest.created_at)).offset((page - 1) * size).limit(size).all()
    return items, total


def approve_comp_off(co_id: str, approver_id: str, db: Session) -> CompOffRequest:
    co = db.query(CompOffRequest).filter(CompOffRequest.id == co_id).first()
    if not co:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comp-off request not found")
    
    if co.status != 'Pending':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be approved")
    
    co.status = 'Approved'
    co.approver_id = approver_id
    db.commit()
    db.refresh(co)
    return co


def reject_comp_off(co_id: str, approver_id: str, db: Session) -> CompOffRequest:
    co = db.query(CompOffRequest).filter(CompOffRequest.id == co_id).first()
    if not co:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comp-off request not found")
    
    if co.status != 'Pending':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending requests can be rejected")
    
    co.status = 'Rejected'
    co.approver_id = approver_id
    db.commit()
    db.refresh(co)
    return co

def create_comp_off_request(payload: CompOffRequestCreate, db: Session) -> CompOffRequest:
    co = CompOffRequest(**payload.model_dump())
    db.add(co)
    db.commit()
    db.refresh(co)
    return co

def assign_roster_entry(payload: RosterEntryCreate, db: Session) -> RosterEntry:
    entry = RosterEntry(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
