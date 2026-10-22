"""Service for managing attendance and applying attendance rules."""

from datetime import datetime, date as date_type, timezone, timedelta
import logging
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.db.models import Attendance, AttendanceRule, Employee, Shift
from app.schemas.attendance import (
    AttendanceCreate,
    AttendanceUpdate,
    CheckInRequest,
    CheckOutRequest,
    EmployeeAttendanceSummary,
)
from app.services.shift_service import get_employee_current_shift
from app.http import HTTPException, status


logger = logging.getLogger(__name__)


class AttendanceRuleEngine:
    """Engine for evaluating attendance rules and determining attendance status."""

    def __init__(self, db: Session, tenant_id: str | None = None):
        self.db = db
        self.tenant_id = tenant_id
        self.rules = self._load_rules()

    def _load_rules(self) -> dict[str, AttendanceRule]:
        """Load active attendance rules from database."""
        query = self.db.query(AttendanceRule).filter(AttendanceRule.is_active.is_(True))
        if self.tenant_id:
            query = query.filter(AttendanceRule.tenant_id == self.tenant_id)
        rules = query.all()
        return {rule.rule_type: rule for rule in rules}

    def calculate_late_minutes(self, check_in_time: datetime, shift: Shift) -> int:
        """Calculate late minutes based on shift start time and grace period."""
        if not shift or not check_in_time:
            return 0

        start = datetime.combine(check_in_time.date(), shift.start_time, tzinfo=check_in_time.tzinfo)
        if shift.end_time < shift.start_time and check_in_time.time() < shift.end_time:
            start -= timedelta(days=1)
        return max(0, int((check_in_time-start).total_seconds()/60)-shift.grace_period_minutes)

    def is_late_entry(self, late_minutes: int) -> bool:
        """Check if entry is considered late based on rules."""
        if 'late_entry' not in self.rules:
            return False
        threshold = self.rules['late_entry'].threshold_minutes
        return late_minutes > threshold

    def calculate_working_hours(self, check_in_time: datetime | None, check_out_time: datetime | None, breaks_duration_hours: float = 0.0) -> float:
        """Calculate total working hours in decimal format."""
        if not check_in_time or not check_out_time:
            return 0.0
        # Normalize naive/aware datetime mismatches (common with SQLite timezone behavior in tests).
        if check_in_time.tzinfo is None and check_out_time.tzinfo is not None:
            check_in_time = check_in_time.replace(tzinfo=timezone.utc)
        elif check_in_time.tzinfo is not None and check_out_time.tzinfo is None:
            check_out_time = check_out_time.replace(tzinfo=timezone.utc)
        duration = check_out_time - check_in_time
        return max(0.0, (duration.total_seconds() / 3600) - breaks_duration_hours)

    def is_half_day(self, working_hours: float) -> bool:
        """Check if attendance qualifies as half-day."""
        if 'half_day' not in self.rules:
            return False
        threshold_minutes = self.rules['half_day'].threshold_minutes
        threshold_hours = threshold_minutes / 60
        return working_hours < threshold_hours

    def is_early_exit(self, check_out_time: datetime, shift: Shift) -> bool:
        """Check if employee left early."""
        if not shift or not check_out_time:
            return False

        if 'early_exit' not in self.rules:
            return False

        check_out_time_only = check_out_time.time()
        shift_end = shift.end_time

        # Calculate minutes early
        check_out_minutes = check_out_time_only.hour * 60 + check_out_time_only.minute
        shift_end_minutes = shift_end.hour * 60 + shift_end.minute

        minutes_early = shift_end_minutes - check_out_minutes
        threshold = self.rules['early_exit'].threshold_minutes

        return minutes_early > threshold

    def determine_status(
        self,
        check_in_time: datetime | None,
        check_out_time: datetime | None,
        is_work_from_home: bool,
    ) -> str:
        """Determine attendance status based on check-in/check-out times."""
        if is_work_from_home:
            return 'work-from-home'

        if not check_in_time:
            return 'absent'

        if not check_out_time:
            return 'present'  # Checked in but not checked out (partial day)

        return 'present'


def create_attendance(payload: AttendanceCreate, db: Session, tenant_id: str | None = None) -> Attendance:
    """Create or update attendance record."""
    # Verify employee exists
    query = db.query(Employee).filter(Employee.id == payload.employee_id)
    if tenant_id:
        query = query.filter(Employee.tenant_id == tenant_id)
    employee = query.first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee not found')

    # Check if attendance already exists for this date
    existing = db.query(Attendance).filter(
        and_(
            Attendance.employee_id == payload.employee_id,
            Attendance.attendance_date == payload.attendance_date,
        )
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Attendance record already exists for this date',
        )

    # Initialize rule engine
    rule_engine = AttendanceRuleEngine(db, tenant_id)

    # Get employee's shift for the date
    shift = get_employee_current_shift(payload.employee_id, payload.attendance_date, db)

    # Set default times if not provided
    check_in_time = payload.check_in_time or datetime.now(timezone.utc)
    check_out_time = payload.check_out_time

    # Calculate metrics
    from app.core.business_time import local_time
    rule_time = local_time(check_in_time, db, tenant_id) if tenant_id else check_in_time
    late_minutes = rule_engine.calculate_late_minutes(rule_time, shift) if check_in_time else 0
    is_late = rule_engine.is_late_entry(late_minutes)

    working_hours = rule_engine.calculate_working_hours(check_in_time, check_out_time)
    is_half_day = rule_engine.is_half_day(working_hours)

    status_value = rule_engine.determine_status(check_in_time, check_out_time, payload.is_work_from_home or False)

    # Create attendance record
    attendance = Attendance(
        employee_id=payload.employee_id,
        attendance_date=payload.attendance_date,
        check_in_time=check_in_time,
        check_out_time=check_out_time,
        status=status_value,
        is_late=is_late,
        late_minutes=late_minutes,
        is_half_day=is_half_day,
        is_work_from_home=payload.is_work_from_home or False,
        notes=payload.notes,
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)

    # Write audit log
    _write_attendance_audit_log(db, 'CREATE', attendance)

    return attendance


def get_attendance(attendance_id: str, db: Session, tenant_id: str | None = None) -> Attendance:
    """Retrieve an attendance record by ID."""
    query = db.query(Attendance)
    if tenant_id:
        query = query.join(Employee, Attendance.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    attendance = query.filter(Attendance.id == attendance_id).first()
    if not attendance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Attendance record not found')
    return attendance


def check_in(payload: CheckInRequest, db: Session, tenant_id: str | None = None) -> Attendance:
    """Record check-in for an employee."""
    # Verify employee exists
    query = db.query(Employee).filter(Employee.id == payload.employee_id)
    if tenant_id:
        query = query.filter(Employee.tenant_id == tenant_id)
    employee = query.first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee not found')

    # Check if attendance exists for today
    existing = db.query(Attendance).filter(
        and_(
            Attendance.employee_id == payload.employee_id,
            Attendance.attendance_date == payload.attendance_date,
        )
    ).first()

    # Initialize rule engine
    rule_engine = AttendanceRuleEngine(db, tenant_id)

    # Get employee's shift
    shift = get_employee_current_shift(payload.employee_id, payload.attendance_date, db)

    check_in_time = payload.check_in_time or datetime.now(timezone.utc)
    from app.core.business_time import local_time
    rule_time = local_time(check_in_time, db, tenant_id) if tenant_id else check_in_time
    late_minutes = rule_engine.calculate_late_minutes(rule_time, shift)
    # is_late marks late beyond grace period; separate policy thresholds can be handled elsewhere.
    is_late = late_minutes > 0

    if existing and existing.check_in_time:
        raise HTTPException(409, 'Attendance is already checked in; use a correction request')
    if existing:
        # Update existing record
        existing.check_in_time = check_in_time
        existing.is_late = is_late
        existing.late_minutes = late_minutes
        if payload.latitude is not None:
            existing.check_in_latitude = payload.latitude
        if payload.longitude is not None:
            existing.check_in_longitude = payload.longitude
        existing.status = 'present'
        existing.updated_at = datetime.now(timezone.utc)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        if existing.check_in_time and existing.check_in_time.tzinfo is None:
            existing.check_in_time = existing.check_in_time.replace(tzinfo=timezone.utc)
        _write_attendance_audit_log(db, 'UPDATE', existing)
        return existing
    else:
        # Create new record
        attendance = Attendance(
            employee_id=payload.employee_id,
            attendance_date=payload.attendance_date,
            check_in_time=check_in_time,
            status='present',
            is_late=is_late,
            late_minutes=late_minutes,
            check_in_latitude=payload.latitude,
            check_in_longitude=payload.longitude,
        )
        db.add(attendance)
        db.commit()
        db.refresh(attendance)
        if attendance.check_in_time and attendance.check_in_time.tzinfo is None:
            attendance.check_in_time = attendance.check_in_time.replace(tzinfo=timezone.utc)
        _write_attendance_audit_log(db, 'CREATE', attendance)
        return attendance


def check_out(payload: CheckOutRequest, db: Session, tenant_id: str | None = None) -> Attendance:
    """Record check-out for an employee."""
    # Get attendance record for today
    query = db.query(Attendance)
    if tenant_id:
        query = query.join(Employee, Attendance.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    
    attendance = query.filter(
        and_(
            Attendance.employee_id == payload.employee_id,
            Attendance.attendance_date == payload.attendance_date,
        )
    ).first()

    if not attendance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='No check-in record found for today. Please check-in first.',
        )

    if attendance.check_out_time:
        raise HTTPException(409, 'Attendance is already checked out')
    if any(b.end_time is None for b in attendance.breaks):
        raise HTTPException(409, 'End your active break before checking out')
    # Initialize rule engine
    rule_engine = AttendanceRuleEngine(db, tenant_id)
    shift = get_employee_current_shift(payload.employee_id, payload.attendance_date, db)
    check_out_time = payload.check_out_time or datetime.now(timezone.utc)

    normalized_in = attendance.check_in_time.replace(tzinfo=timezone.utc) if attendance.check_in_time.tzinfo is None else attendance.check_in_time
    normalized_out = check_out_time.replace(tzinfo=timezone.utc) if check_out_time.tzinfo is None else check_out_time
    if normalized_out <= normalized_in:
        raise HTTPException(400, 'Check-out must be after check-in')
    # Calculate total break duration
    breaks_duration_hours = 0.0
    for b in attendance.breaks:
        if b.start_time and b.end_time:
            breaks_duration_hours += (b.end_time - b.start_time).total_seconds() / 3600.0

    # Calculate working hours and half-day status
    working_hours = rule_engine.calculate_working_hours(attendance.check_in_time, check_out_time, breaks_duration_hours)
    is_half_day = rule_engine.is_half_day(working_hours)

    # Check for early exit
    from app.core.business_time import local_time
    is_early_exit = rule_engine.is_early_exit(local_time(check_out_time, db, tenant_id) if tenant_id else check_out_time, shift)

    # Update attendance
    attendance.check_out_time = check_out_time
    attendance.is_half_day = is_half_day
    if payload.latitude is not None:
        attendance.check_out_latitude = payload.latitude
    if payload.longitude is not None:
        attendance.check_out_longitude = payload.longitude
    attendance.updated_at = datetime.now(timezone.utc)
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    if attendance.check_out_time and attendance.check_out_time.tzinfo is None:
        attendance.check_out_time = attendance.check_out_time.replace(tzinfo=timezone.utc)
    if attendance.check_in_time and attendance.check_in_time.tzinfo is None:
        attendance.check_in_time = attendance.check_in_time.replace(tzinfo=timezone.utc)
    _write_attendance_audit_log(db, 'UPDATE', attendance)

    return attendance


def list_attendance(
    db: Session,
    tenant_id: str | None = None,
    employee_id: str | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Attendance], int]:
    """List attendance records with optional filters."""
    query = db.query(Attendance)

    if tenant_id:
        query = query.join(Employee, Attendance.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)

    if employee_id:
        query = query.filter(Attendance.employee_id == employee_id)
    if start_date:
        query = query.filter(Attendance.attendance_date >= start_date)
    if end_date:
        query = query.filter(Attendance.attendance_date <= end_date)

    total = query.with_entities(func.count(Attendance.id)).scalar() or 0
    records = query.order_by(Attendance.attendance_date.desc()).offset((page - 1) * size).limit(size).all()

    return records, int(total)


def update_attendance(attendance_id: str, payload: AttendanceUpdate, db: Session, tenant_id: str | None = None) -> Attendance:
    """Update an attendance record."""
    attendance = get_attendance(attendance_id, db, tenant_id)

    # Initialize rule engine for recalculation
    rule_engine = AttendanceRuleEngine(db, tenant_id)

    # Get employee's shift if needed for recalculation
    shift = get_employee_current_shift(attendance.employee_id, attendance.attendance_date, db)

    if payload.check_in_time is not None:
        attendance.check_in_time = payload.check_in_time
        late_minutes = rule_engine.calculate_late_minutes(payload.check_in_time, shift)
        attendance.is_late = rule_engine.is_late_entry(late_minutes)
        attendance.late_minutes = late_minutes

    if payload.check_out_time is not None:
        attendance.check_out_time = payload.check_out_time
        breaks_duration_hours = 0.0
        for b in attendance.breaks:
            if b.start_time and b.end_time:
                breaks_duration_hours += (b.end_time - b.start_time).total_seconds() / 3600.0
        working_hours = rule_engine.calculate_working_hours(attendance.check_in_time, payload.check_out_time, breaks_duration_hours)
        attendance.is_half_day = rule_engine.is_half_day(working_hours)

    if payload.status is not None:
        attendance.status = payload.status

    if payload.is_work_from_home is not None:
        attendance.is_work_from_home = payload.is_work_from_home

    if payload.notes is not None:
        attendance.notes = payload.notes

    attendance.updated_at = datetime.now(timezone.utc)
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    _write_attendance_audit_log(db, 'UPDATE', attendance)

    return attendance


def delete_attendance(attendance_id: str, db: Session, tenant_id: str | None = None) -> Attendance:
    """Delete an attendance record."""
    attendance = get_attendance(attendance_id, db, tenant_id)
    db.delete(attendance)
    db.commit()
    _write_attendance_audit_log(db, 'DELETE', attendance)
    return attendance


def get_employee_attendance_summary(
    employee_id: str,
    start_date: date_type,
    end_date: date_type,
    db: Session,
    tenant_id: str | None = None,
) -> EmployeeAttendanceSummary:
    """Get attendance summary for an employee within a date range."""
    # Verify employee exists
    query = db.query(Employee).filter(Employee.id == employee_id)
    if tenant_id:
        query = query.filter(Employee.tenant_id == tenant_id)
    employee = query.first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee not found')

    # Get all attendance records
    records = db.query(Attendance).filter(
        and_(
            Attendance.employee_id == employee_id,
            Attendance.attendance_date >= start_date,
            Attendance.attendance_date <= end_date,
        )
    ).order_by(Attendance.attendance_date).all()

    # Calculate summary
    total_days = (end_date - start_date).days + 1
    present_days = len([r for r in records if r.status == 'present'])
    absent_days = len([r for r in records if r.status == 'absent'])
    half_days = len([r for r in records if r.is_half_day])
    work_from_home_days = len([r for r in records if r.is_work_from_home])
    late_days = len([r for r in records if r.is_late])

    from app.schemas.attendance import AttendanceSummaryItem

    summary_items = [
        AttendanceSummaryItem(
            date=r.attendance_date,
            status=r.status,
            check_in_time=r.check_in_time,
            check_out_time=r.check_out_time,
            is_late=r.is_late,
            is_half_day=r.is_half_day,
            is_work_from_home=r.is_work_from_home,
        )
        for r in records
    ]

    return EmployeeAttendanceSummary(
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
        total_days=total_days,
        present_days=present_days,
        absent_days=absent_days,
        half_days=half_days,
        work_from_home_days=work_from_home_days,
        late_days=late_days,
        records=summary_items,
    )


def _write_attendance_audit_log(db: Session, action: str, attendance: Attendance) -> None:
    """Write attendance operation to audit log."""
    from app.db.models import AuditLog
    import json

    try:
        log = AuditLog(
            actor_id=db.info['actor'].id if db.info.get('actor') else None,
            tenant_id=attendance.tenant_id,
            action=action,
            object_type='Attendance',
            object_id=attendance.id,
            data=json.dumps({
                'employee_id': attendance.employee_id,
                'attendance_date': attendance.attendance_date.isoformat(),
                'status': attendance.status,
                'is_late': attendance.is_late,
                'is_half_day': attendance.is_half_day,
            }),
        )
        db.add(log)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception('Failed to write attendance audit log for %s %s', action, attendance.id)


def start_break(payload, db: Session, tenant_id: str | None = None):
    from app.db.models import AttendanceBreak

    # Get attendance record
    query = db.query(Attendance)
    if tenant_id:
        query = query.join(Employee, Attendance.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    attendance = query.filter(
        and_(
            Attendance.employee_id == payload.employee_id,
            Attendance.attendance_date == payload.attendance_date,
        )
    ).first()

    if not attendance:
        raise HTTPException(status_code=404, detail="No check-in record found for today.")

    if attendance.check_out_time:
        raise HTTPException(status_code=400, detail="Already checked out.")

    # Check for active break
    active_break = next((b for b in attendance.breaks if not b.end_time), None)
    if active_break:
        raise HTTPException(status_code=400, detail="Break already in progress.")

    new_break = AttendanceBreak(
        attendance_id=attendance.id,
        break_type=payload.break_type,
        start_time=payload.start_time or datetime.now(timezone.utc)
    )
    db.add(new_break)
    db.commit()
    db.refresh(attendance)
    return attendance


def end_break(payload, db: Session, tenant_id: str | None = None):
    from app.db.models import AttendanceBreak

    # Get attendance record
    query = db.query(Attendance)
    if tenant_id:
        query = query.join(Employee, Attendance.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    attendance = query.filter(
        and_(
            Attendance.employee_id == payload.employee_id,
            Attendance.attendance_date == payload.attendance_date,
        )
    ).first()

    if not attendance:
        raise HTTPException(status_code=404, detail="No check-in record found for today.")

    # Check for active break
    active_break = next((b for b in attendance.breaks if not b.end_time), None)
    if not active_break:
        raise HTTPException(status_code=400, detail="No active break to end.")

    end = payload.end_time or datetime.now(timezone.utc)
    start = active_break.start_time
    left = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
    right = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
    if right <= left:
        raise HTTPException(400, 'Break end must be after break start')
    active_break.end_time = end
    db.commit()
    db.refresh(attendance)
    return attendance


def run_auto_checkout_job(db: Session):
    """Close only shifts whose local end has passed, including overnight shifts."""
    from app.core.business_time import tenant_zone
    from app.db.models import AttendanceBreak
    now=datetime.now(timezone.utc)
    records=db.query(Attendance).filter(Attendance.check_in_time.isnot(None),Attendance.check_out_time.is_(None)).all()
    for attendance in records:
        employee=db.get(Employee,attendance.employee_id)
        if not employee or not employee.tenant_id:
            continue
        zone=tenant_zone(db,employee.tenant_id)
        shift=get_employee_current_shift(employee.id,attendance.attendance_date,db)
        if shift:
            end_date=attendance.attendance_date+timedelta(days=1 if shift.end_time<=shift.start_time else 0)
            cutoff=datetime.combine(end_date,shift.end_time,tzinfo=zone)
        else:
            from datetime import time
            cutoff=datetime.combine(attendance.attendance_date,time(23,59),tzinfo=zone)
        if cutoff.astimezone(timezone.utc)>now:
            continue
        attendance.check_out_time=cutoff.astimezone(timezone.utc)
        for item in attendance.breaks:
            if item.end_time is None: item.end_time=attendance.check_out_time
        rules=AttendanceRuleEngine(db,employee.tenant_id)
        duration=sum(rules.calculate_working_hours(item.start_time,item.end_time) for item in attendance.breaks if item.start_time and item.end_time)
        hours=rules.calculate_working_hours(attendance.check_in_time,attendance.check_out_time,duration)
        attendance.is_half_day=rules.is_half_day(hours)
        attendance.notes=((attendance.notes+' | ') if attendance.notes else '')+'System: checked out at scheduled shift end.'
        attendance.updated_at=now
        db.commit()
        _write_attendance_audit_log(db,'AUTO_CHECKOUT',attendance)
