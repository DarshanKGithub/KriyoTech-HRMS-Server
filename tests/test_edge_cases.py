"""Comprehensive edge case tests for employee, dashboard, and audit services."""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Employee, Department, User, AuditLog
from app.services.employee_service import create_employee, update_employee, delete_employee
from app.services.dashboard_service import get_dashboard_summary
from app.services.audit_service import list_audit_logs
from app.schemas.employee import EmployeeCreate, EmployeeUpdate
from app.http import HTTPException


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite test database."""
    engine = create_engine('sqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


# ==================== Employee Service Edge Cases ====================


def test_create_employee_with_all_fields(db_session):
    """Test creating an employee with all optional fields populated."""
    dept = Department(name='Engineering')
    db_session.add(dept)
    db_session.commit()
    db_session.refresh(dept)

    payload = EmployeeCreate(
        full_name='Alice Engineer',
        email='alice@example.com',
        department_id=dept.id,
        designation_id=None,
        manager_id=None,
    )
    emp = create_employee(payload, db_session)

    assert emp.full_name == 'Alice Engineer'
    assert emp.email == 'alice@example.com'
    assert emp.department_id == dept.id
    assert emp.is_active is True


def test_create_employee_duplicate_email_fails(db_session):
    """Test that duplicate emails are rejected."""
    emp1 = Employee(full_name='Alice', email='alice@example.com')
    db_session.add(emp1)
    db_session.commit()

    payload = EmployeeCreate(
        full_name='Alice Clone',
        email='alice@example.com',  # Same email
    )
    with pytest.raises(Exception):  # SQLAlchemy IntegrityError
        create_employee(payload, db_session)


def test_update_employee_only_name(db_session):
    """Test partial update with only name field."""
    emp = Employee(full_name='Alice', email='alice@example.com')
    db_session.add(emp)
    db_session.commit()
    db_session.refresh(emp)

    payload = EmployeeUpdate(full_name='Alicia')
    result = update_employee(emp.id, payload, db_session)

    assert result.full_name == 'Alicia'
    assert result.email == 'alice@example.com'  # Unchanged


def test_update_employee_set_inactive(db_session):
    """Test deactivating an employee."""
    emp = Employee(full_name='Alice', email='alice@example.com', is_active=True)
    db_session.add(emp)
    db_session.commit()
    db_session.refresh(emp)

    payload = EmployeeUpdate(is_active=False)
    result = update_employee(emp.id, payload, db_session)

    assert result.is_active is False


def test_update_employee_nonexistent_fails(db_session):
    """Test updating a non-existent employee."""
    payload = EmployeeUpdate(full_name='Ghost')
    with pytest.raises(HTTPException) as exc:
        update_employee('nonexistent-id', payload, db_session)
    assert exc.value.status_code == 404


def test_delete_employee_success(db_session):
    """Test deleting an employee."""
    emp = Employee(full_name='Alice', email='alice@example.com')
    db_session.add(emp)
    db_session.commit()
    emp_id = emp.id

    result = delete_employee(emp_id, db_session)
    assert result.id == emp_id

    # Verify employee is gone
    deleted = db_session.query(Employee).filter_by(id=emp_id).first()
    assert deleted is None


def test_delete_nonexistent_employee_fails(db_session):
    """Test deleting a non-existent employee."""
    with pytest.raises(HTTPException) as exc:
        delete_employee('nonexistent-id', db_session)
    assert exc.value.status_code == 404


def test_self_manager_reference_fails(db_session):
    """Test that an employee cannot be their own manager."""
    emp = Employee(full_name='Alice', email='alice@example.com')
    db_session.add(emp)
    db_session.commit()
    db_session.refresh(emp)

    payload = EmployeeUpdate(manager_id=emp.id)
    with pytest.raises(HTTPException) as exc:
        update_employee(emp.id, payload, db_session)
    assert 'cycle' in exc.value.detail.lower()


def test_deep_manager_chain(db_session):
    """Test a valid deep manager chain: A -> B -> C -> D."""
    emp_a = Employee(full_name='A', email='a@example.com')
    emp_b = Employee(full_name='B', email='b@example.com', manager_id=None)
    emp_c = Employee(full_name='C', email='c@example.com', manager_id=None)
    emp_d = Employee(full_name='D', email='d@example.com', manager_id=None)

    db_session.add_all([emp_a, emp_b, emp_c, emp_d])
    db_session.commit()
    db_session.refresh(emp_a)
    db_session.refresh(emp_b)
    db_session.refresh(emp_c)
    db_session.refresh(emp_d)

    # Set up chain: A <- B <- C <- D
    update_employee(emp_b.id, EmployeeUpdate(manager_id=emp_a.id), db_session)
    update_employee(emp_c.id, EmployeeUpdate(manager_id=emp_b.id), db_session)
    update_employee(emp_d.id, EmployeeUpdate(manager_id=emp_c.id), db_session)

    # Verify chain
    db_session.refresh(emp_b)
    db_session.refresh(emp_c)
    db_session.refresh(emp_d)
    assert emp_b.manager_id == emp_a.id
    assert emp_c.manager_id == emp_b.id
    assert emp_d.manager_id == emp_c.id


# ==================== Dashboard Service Edge Cases ====================


def test_dashboard_with_empty_database(db_session):
    """Test dashboard summary with no employees."""
    summary = get_dashboard_summary(db=db_session)

    assert summary.kpis.total_employees == 0
    assert summary.kpis.active_employees == 0
    assert summary.kpis.inactive_employees == 0
    assert summary.kpis.departments_count == 0
    assert len(summary.department_breakdown) == 0


def test_dashboard_with_only_unassigned_employees(db_session):
    """Test dashboard with employees but no department assignments."""
    emp1 = Employee(full_name='A', email='a@example.com', is_active=True)
    emp2 = Employee(full_name='B', email='b@example.com', is_active=False)
    db_session.add_all([emp1, emp2])
    db_session.commit()

    summary = get_dashboard_summary(db=db_session)

    assert summary.kpis.total_employees == 2
    assert summary.kpis.active_employees == 1
    assert summary.kpis.inactive_employees == 1
    assert len([d for d in summary.department_breakdown if d.department_name == 'Unassigned']) > 0


def test_dashboard_with_department_filter(db_session):
    """Test dashboard summary with department filter."""
    dept_eng = Department(name='Engineering')
    dept_hr = Department(name='HR')
    db_session.add_all([dept_eng, dept_hr])
    db_session.commit()
    db_session.refresh(dept_eng)
    db_session.refresh(dept_hr)

    emp1 = Employee(full_name='Alice', email='alice@example.com', department_id=dept_eng.id, is_active=True)
    emp2 = Employee(full_name='Bob', email='bob@example.com', department_id=dept_eng.id, is_active=True)
    emp3 = Employee(full_name='Cara', email='cara@example.com', department_id=dept_hr.id, is_active=True)
    db_session.add_all([emp1, emp2, emp3])
    db_session.commit()

    # Filter by Engineering
    summary = get_dashboard_summary(db=db_session, department_id=dept_eng.id)

    assert summary.kpis.total_employees == 2
    assert summary.kpis.active_employees == 2
    assert summary.kpis.departments_count == 1
    assert len(summary.department_breakdown) == 1
    assert summary.department_breakdown[0].department_name == 'Engineering'


def test_dashboard_breakdown_accuracy(db_session):
    """Test department breakdown calculation accuracy."""
    dept1 = Department(name='Engineering')
    dept2 = Department(name='Sales')
    db_session.add_all([dept1, dept2])
    db_session.commit()
    db_session.refresh(dept1)
    db_session.refresh(dept2)

    # Engineering: 3 active, 1 inactive
    for i, active in enumerate([True, True, True, False]):
        emp = Employee(
            full_name=f'Engineer {i}',
            email=f'eng{i}@example.com',
            department_id=dept1.id,
            is_active=active,
        )
        db_session.add(emp)

    # Sales: 2 active, 0 inactive
    for i in range(2):
        emp = Employee(
            full_name=f'Sales {i}',
            email=f'sales{i}@example.com',
            department_id=dept2.id,
            is_active=True,
        )
        db_session.add(emp)

    db_session.commit()

    summary = get_dashboard_summary(db=db_session)

    by_name = {item.department_name: item for item in summary.department_breakdown}

    assert by_name['Engineering'].total_employees == 4
    assert by_name['Engineering'].active_employees == 3
    assert by_name['Engineering'].inactive_employees == 1

    assert by_name['Sales'].total_employees == 2
    assert by_name['Sales'].active_employees == 2
    assert by_name['Sales'].inactive_employees == 0


# ==================== Audit Service Edge Cases ====================


def test_audit_log_listing_pagination(db_session):
    """Test audit log pagination."""
    # Create 25 audit logs
    for i in range(25):
        log = AuditLog(
            actor_id='admin-1',
            action='CREATE' if i % 3 == 0 else 'UPDATE',
            object_type='Employee',
            object_id=f'emp-{i}',
            data=f'{{"name": "Employee {i}"}}',
        )
        db_session.add(log)
    db_session.commit()

    # Page 1: 20 items
    items_p1, total_p1 = list_audit_logs(db=db_session, page=1, size=20)
    assert len(items_p1) == 20
    assert total_p1 == 25

    # Page 2: 5 items
    items_p2, total_p2 = list_audit_logs(db=db_session, page=2, size=20)
    assert len(items_p2) == 5
    assert total_p2 == 25


def test_audit_log_filter_by_object_type(db_session):
    """Test audit log filtering by object type."""
    for i in range(10):
        log = AuditLog(
            actor_id='admin-1',
            action='CREATE',
            object_type='Employee' if i % 2 == 0 else 'Department',
            object_id=f'id-{i}',
        )
        db_session.add(log)
    db_session.commit()

    items, total = list_audit_logs(db=db_session, object_type='Employee')
    assert len(items) == 5
    assert total == 5
    assert all(log.object_type == 'Employee' for log in items)


def test_audit_log_filter_by_actor_id(db_session):
    """Test audit log filtering by actor ID."""
    for i in range(10):
        log = AuditLog(
            actor_id=f'actor-{i % 3}',
            action='CREATE',
            object_type='Employee',
            object_id=f'id-{i}',
        )
        db_session.add(log)
    db_session.commit()

    items, total = list_audit_logs(db=db_session, actor_id='actor-0')
    assert total == 4  # 0, 3, 6, 9
    assert all(log.actor_id == 'actor-0' for log in items)


def test_audit_log_ordering_newest_first(db_session):
    """Test that audit logs are ordered with newest first."""
    # Explicit times avoid equal clock ticks on Windows and fast batch inserts.
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    log1 = AuditLog(actor_id='a', action='CREATE', object_type='Employee', object_id='1', created_at=start)
    log2 = AuditLog(actor_id='a', action='UPDATE', object_type='Employee', object_id='1', created_at=start + timedelta(seconds=1))
    log3 = AuditLog(actor_id='a', action='DELETE', object_type='Employee', object_id='1', created_at=start + timedelta(seconds=2))

    db_session.add_all([log1, log2, log3])
    db_session.commit()

    items, _ = list_audit_logs(db=db_session, size=10)
    # Most recent should be first
    assert items[0].action == 'DELETE'
    assert items[1].action == 'UPDATE'
    assert items[2].action == 'CREATE'


def test_audit_log_combined_filters(db_session):
    """Test audit logs with combined object_type and actor_id filters."""
    for i in range(20):
        log = AuditLog(
            actor_id=f'actor-{i % 2}',
            action='CREATE' if i % 3 == 0 else 'UPDATE',
            object_type='Employee' if i % 2 == 0 else 'Department',
            object_id=f'id-{i}',
        )
        db_session.add(log)
    db_session.commit()

    # Filter: Employee type AND actor-0
    items, total = list_audit_logs(db=db_session, object_type='Employee', actor_id='actor-0')

    assert total > 0
    assert all(log.object_type == 'Employee' and log.actor_id == 'actor-0' for log in items)
