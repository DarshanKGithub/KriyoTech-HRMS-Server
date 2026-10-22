"""Tests for the advanced attendance regularization workflow."""

from datetime import date, datetime, timezone

import pytest
from app.http import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Attendance, AttendanceRegularization, Employee
from app.schemas.advanced_attendance import AttendanceRegularizationCreate
from app.services.advanced_attendance_service import (
    approve_regularization,
    create_attendance_regularization,
    get_regularizations,
    reject_regularization,
)


@pytest.fixture()
def db_session():
    engine = create_engine('sqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_create_regularization_links_existing_attendance(db_session):
    employee = Employee(full_name='Alice', email='alice@example.com')
    db_session.add(employee)
    db_session.commit()
    db_session.refresh(employee)

    attendance = Attendance(
        employee_id=employee.id,
        attendance_date=date(2026, 5, 7),
        status='absent',
    )
    db_session.add(attendance)
    db_session.commit()

    payload = AttendanceRegularizationCreate(
        employee_id=employee.id,
        attendance_id=None,
        date=date(2026, 5, 7),
        reason='Missed punch due to network issue',
        requested_check_in=datetime(2026, 5, 7, 9, 5, tzinfo=timezone.utc),
        requested_check_out=datetime(2026, 5, 7, 18, 0, tzinfo=timezone.utc),
    )

    reg = create_attendance_regularization(payload, db_session)

    assert reg.attendance_id == attendance.id
    assert reg.status == 'Pending'


def test_create_regularization_rejects_duplicate_pending_request(db_session):
    employee = Employee(full_name='Bob', email='bob@example.com')
    db_session.add(employee)
    db_session.commit()
    db_session.refresh(employee)

    payload = AttendanceRegularizationCreate(
        employee_id=employee.id,
        attendance_id=None,
        date=date(2026, 5, 7),
        reason='Need correction',
    )
    create_attendance_regularization(payload, db_session)

    with pytest.raises(HTTPException) as exc_info:
        create_attendance_regularization(payload, db_session)

    assert exc_info.value.status_code == 400


def test_approve_regularization_updates_attendance(db_session):
    employee = Employee(full_name='Cara', email='cara@example.com')
    approver = Employee(full_name='Manager', email='manager@example.com')
    db_session.add_all([employee, approver])
    db_session.commit()
    db_session.refresh(employee)
    db_session.refresh(approver)

    attendance = Attendance(
        employee_id=employee.id,
        attendance_date=date(2026, 5, 7),
        status='absent',
        is_late=True,
        late_minutes=25,
        is_half_day=True,
        is_work_from_home=False,
    )
    db_session.add(attendance)
    db_session.commit()
    db_session.refresh(attendance)

    regularization = AttendanceRegularization(
        employee_id=employee.id,
        attendance_id=attendance.id,
        date=date(2026, 5, 7),
        reason='Traffic delay',
        requested_check_in=datetime(2026, 5, 7, 9, 10, tzinfo=timezone.utc),
        requested_check_out=datetime(2026, 5, 7, 18, 0, tzinfo=timezone.utc),
    )
    db_session.add(regularization)
    db_session.commit()
    db_session.refresh(regularization)

    approved = approve_regularization(regularization.id, approver.id, db_session)

    db_session.refresh(attendance)

    assert approved.status == 'Approved'
    assert approved.approver_id == approver.id
    assert attendance.status == 'present'
    assert attendance.check_in_time.replace(tzinfo=timezone.utc) == datetime(2026, 5, 7, 9, 10, tzinfo=timezone.utc)
    assert attendance.check_out_time.replace(tzinfo=timezone.utc) == datetime(2026, 5, 7, 18, 0, tzinfo=timezone.utc)
    assert attendance.is_late is False
    assert attendance.late_minutes == 0
    assert attendance.is_half_day is False


def test_reject_regularization_changes_status(db_session):
    employee = Employee(full_name='Dan', email='dan@example.com')
    approver = Employee(full_name='Hr', email='hr@example.com')
    db_session.add_all([employee, approver])
    db_session.commit()
    db_session.refresh(employee)
    db_session.refresh(approver)

    regularization = AttendanceRegularization(
        employee_id=employee.id,
        date=date(2026, 5, 7),
        reason='Correction',
    )
    db_session.add(regularization)
    db_session.commit()
    db_session.refresh(regularization)

    rejected = reject_regularization(regularization.id, approver.id, db_session)

    assert rejected.status == 'Rejected'
    assert rejected.approver_id == approver.id


def test_get_regularizations_filters_by_employee_and_status(db_session):
    employee = Employee(full_name='Eve', email='eve@example.com')
    other = Employee(full_name='Finn', email='finn@example.com')
    db_session.add_all([employee, other])
    db_session.commit()
    db_session.refresh(employee)
    db_session.refresh(other)

    pending = AttendanceRegularization(
        employee_id=employee.id,
        date=date(2026, 5, 7),
        reason='Pending one',
    )
    approved = AttendanceRegularization(
        employee_id=employee.id,
        date=date(2026, 5, 6),
        reason='Approved one',
        status='Approved',
    )
    other_employee = AttendanceRegularization(
        employee_id=other.id,
        date=date(2026, 5, 7),
        reason='Other employee',
    )
    db_session.add_all([pending, approved, other_employee])
    db_session.commit()

    items, total = get_regularizations(db_session, employee_id=employee.id, status_filter='Approved', page=1, size=20)

    assert total == 1
    assert len(items) == 1
    assert items[0].reason == 'Approved one'