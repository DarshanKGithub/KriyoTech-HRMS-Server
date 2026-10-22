"""Service for managing shifts."""

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import Shift, EmployeeShiftAssignment, Employee
from app.schemas.attendance import (
    ShiftCreate,
    ShiftUpdate,
    EmployeeShiftAssignmentCreate,
    EmployeeShiftAssignmentUpdate,
)
from app.http import HTTPException, status


def create_shift(payload: ShiftCreate, db: Session) -> Shift:
    """Create a new shift."""
    # Check if shift name already exists
    existing = db.query(Shift).filter(Shift.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Shift '{payload.name}' already exists",
        )

    shift = Shift(
        name=payload.name,
        start_time=payload.start_time,
        end_time=payload.end_time,
        grace_period_minutes=payload.grace_period_minutes,
        is_active=payload.is_active,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


def get_shift(shift_id: str, db: Session) -> Shift:
    """Retrieve a shift by ID."""
    shift = db.query(Shift).filter(Shift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Shift not found')
    return shift


def list_shifts(db: Session, page: int = 1, size: int = 20) -> tuple[list[Shift], int]:
    """List all shifts with pagination."""
    query = db.query(Shift).order_by(Shift.name)
    total = db.query(func.count(Shift.id)).scalar() or 0
    shifts = query.offset((page - 1) * size).limit(size).all()
    return shifts, int(total)


def update_shift(shift_id: str, payload: ShiftUpdate, db: Session) -> Shift:
    """Update a shift."""
    shift = get_shift(shift_id, db)

    # If name is being changed, check for duplicates
    if payload.name and payload.name != shift.name:
        existing = db.query(Shift).filter(Shift.name == payload.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Shift '{payload.name}' already exists",
            )

    # Update fields
    if payload.name is not None:
        shift.name = payload.name
    if payload.start_time is not None:
        shift.start_time = payload.start_time
    if payload.end_time is not None:
        shift.end_time = payload.end_time
    if payload.grace_period_minutes is not None:
        shift.grace_period_minutes = payload.grace_period_minutes
    if payload.is_active is not None:
        shift.is_active = payload.is_active

    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


def delete_shift(shift_id: str, db: Session) -> Shift:
    """Delete a shift."""
    shift = get_shift(shift_id, db)

    # Check if shift is assigned to any employees
    assigned = db.query(EmployeeShiftAssignment).filter(
        EmployeeShiftAssignment.shift_id == shift_id,
        EmployeeShiftAssignment.is_active.is_(True),
    ).first()

    if assigned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot delete shift with active employee assignments',
        )

    db.delete(shift)
    db.commit()
    return shift


# ==================== Employee Shift Assignment ====================


def assign_shift_to_employee(payload: EmployeeShiftAssignmentCreate, db: Session) -> EmployeeShiftAssignment:
    """Assign a shift to an employee."""
    # Verify employee exists
    employee = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee not found')

    # Verify shift exists
    shift = db.query(Shift).filter(Shift.id == payload.shift_id).first()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Shift not found')

    # Check for overlapping active assignments on same date
    overlapping = db.query(EmployeeShiftAssignment).filter(
        EmployeeShiftAssignment.employee_id == payload.employee_id,
        EmployeeShiftAssignment.start_date <= payload.start_date,
        (EmployeeShiftAssignment.end_date.is_(None) | (EmployeeShiftAssignment.end_date >= payload.start_date)),
        EmployeeShiftAssignment.is_active.is_(True),
    ).first()

    if overlapping:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Employee already has an active shift assignment overlapping this date',
        )

    assignment = EmployeeShiftAssignment(
        employee_id=payload.employee_id,
        shift_id=payload.shift_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_active=payload.is_active,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def get_employee_shift_assignment(assignment_id: str, db: Session) -> EmployeeShiftAssignment:
    """Retrieve an employee shift assignment by ID."""
    assignment = db.query(EmployeeShiftAssignment).filter(EmployeeShiftAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Shift assignment not found')
    return assignment


def list_employee_shift_assignments(
    db: Session,
    employee_id: str | None = None,
    shift_id: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[EmployeeShiftAssignment], int]:
    """List employee shift assignments with optional filters."""
    query = db.query(EmployeeShiftAssignment)

    if employee_id:
        query = query.filter(EmployeeShiftAssignment.employee_id == employee_id)
    if shift_id:
        query = query.filter(EmployeeShiftAssignment.shift_id == shift_id)

    total = query.with_entities(func.count(EmployeeShiftAssignment.id)).scalar() or 0
    assignments = query.order_by(EmployeeShiftAssignment.start_date).offset((page - 1) * size).limit(size).all()
    return assignments, int(total)


def update_employee_shift_assignment(
    assignment_id: str,
    payload: EmployeeShiftAssignmentUpdate,
    db: Session,
) -> EmployeeShiftAssignment:
    """Update an employee shift assignment."""
    assignment = get_employee_shift_assignment(assignment_id, db)

    if payload.shift_id is not None:
        # Verify new shift exists
        shift = db.query(Shift).filter(Shift.id == payload.shift_id).first()
        if not shift:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Shift not found')
        assignment.shift_id = payload.shift_id

    if payload.end_date is not None:
        assignment.end_date = payload.end_date

    if payload.is_active is not None:
        assignment.is_active = payload.is_active

    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def delete_employee_shift_assignment(assignment_id: str, db: Session) -> EmployeeShiftAssignment:
    """Delete an employee shift assignment."""
    assignment = get_employee_shift_assignment(assignment_id, db)
    db.delete(assignment)
    db.commit()
    return assignment


def get_employee_current_shift(employee_id: str, target_date, db: Session) -> Shift | None:
    """Get the active shift assignment for an employee on a specific date."""
    from datetime import date as date_type

    if isinstance(target_date, str):
        target_date = date_type.fromisoformat(target_date)

    assignment = db.query(EmployeeShiftAssignment).filter(
        EmployeeShiftAssignment.employee_id == employee_id,
        EmployeeShiftAssignment.start_date <= target_date,
        (EmployeeShiftAssignment.end_date.is_(None) | (EmployeeShiftAssignment.end_date >= target_date)),
        EmployeeShiftAssignment.is_active.is_(True),
    ).first()

    if not assignment:
        return None

    shift = db.query(Shift).filter(Shift.id == assignment.shift_id).first()
    return shift
