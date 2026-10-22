import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Employee
from app.services.employee_service import create_employee, update_employee
from app.schemas.employee import EmployeeCreate, EmployeeUpdate
from app.http import HTTPException


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


def test_create_with_missing_manager_fails(db_session):
    payload = EmployeeCreate(full_name='Alice', email='alice@example.com', manager_id='non-existent')
    with pytest.raises(HTTPException) as exc:
        create_employee(payload, db_session)
    assert exc.value.status_code == 400
    assert 'Manager not found' in exc.value.detail


def test_update_detects_cycle(db_session):
    # create two employees A and B where B.manager = A
    a = Employee(full_name='A', email='a@example.com')
    db_session.add(a)
    db_session.commit()
    db_session.refresh(a)

    b = Employee(full_name='B', email='b@example.com', manager_id=a.id)
    db_session.add(b)
    db_session.commit()
    db_session.refresh(b)

    # attempt to set A.manager = B should raise due to cycle
    payload = EmployeeUpdate(manager_id=b.id)
    with pytest.raises(HTTPException) as exc:
        update_employee(a.id, payload, db_session)
    assert exc.value.status_code == 400
    assert 'create a cycle' in exc.value.detail
