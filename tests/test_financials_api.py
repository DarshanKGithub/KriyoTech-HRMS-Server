from tests.company_fixtures import company_fixture
import pytest
from app.testing import APIClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.database import Base, get_db
from app.db.models import Employee, User
from app.http import override_dependencies


@pytest.fixture()
def db_session():
    engine = create_engine(
        'sqlite://',
        future=True,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()

    admin = User(full_name='Admin User', email='admin@test.com', role='Admin', password_hash=hash_password('password'))
    worker_id = 'worker-employee'
    worker = User(id=worker_id, full_name='Worker User', email='worker@test.com', role='Employee', password_hash=hash_password('password'))
    target_employee = Employee(id='target-employee', full_name='Target Employee', email='target@example.com')
    worker_employee = Employee(id=worker_id, full_name='Worker Employee', email='worker-employee@example.com')

    session.add_all([admin, worker, target_employee, worker_employee])
    company_fixture(session)
    session.commit()

    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        return db_session


    with override_dependencies({get_db: override_get_db}):
        test_client = APIClient()
        yield test_client



def auth_headers(email: str):
    token = create_access_token({'sub': email})
    return {'Authorization': f'Bearer {token}'}


def test_salary_structure_upsert_and_fetch(client):
    create_response = client.post(
        '/financials/salary-structures',
        headers=auth_headers('admin@test.com'),
        json={
            'employee_id': 'target-employee',
            'base_salary': 60000,
            'hra': 15000,
            'da': 5000,
            'special_allowance': 8000,
            'pf_percentage': 12,
            'esi_percentage': 0.75,
            'tax_bracket_percentage': 10,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['employee_id'] == 'target-employee'
    assert created['base_salary'] == 60000

    fetch_response = client.get(
        '/financials/salary-structures/target-employee',
        headers=auth_headers('admin@test.com'),
    )
    assert fetch_response.status_code == 200
    fetched = fetch_response.json()
    assert fetched['hra'] == 15000
    assert fetched['pf_percentage'] == 12

    update_response = client.post(
        '/financials/salary-structures',
        headers=auth_headers('admin@test.com'),
        json={
            'employee_id': 'target-employee',
            'base_salary': 70000,
            'hra': 18000,
            'da': 6000,
            'special_allowance': 9000,
            'pf_percentage': 12,
            'esi_percentage': 0.75,
            'tax_bracket_percentage': 12,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated['base_salary'] == 70000
    assert updated['tax_bracket_percentage'] == 12


def test_salary_structure_permissions(client):
    forbidden_create = client.post(
        '/financials/salary-structures',
        headers=auth_headers('worker@test.com'),
        json={
            'employee_id': 'worker-employee',
            'base_salary': 50000,
            'hra': 10000,
            'da': 3000,
            'special_allowance': 2000,
            'pf_percentage': 12,
            'esi_percentage': 0.75,
            'tax_bracket_percentage': 10,
        },
    )
    assert forbidden_create.status_code == 403

    client.post(
        '/financials/salary-structures',
        headers=auth_headers('admin@test.com'),
        json={
            'employee_id': 'worker-employee',
            'base_salary': 50000,
            'hra': 10000,
            'da': 3000,
            'special_allowance': 2000,
            'pf_percentage': 12,
            'esi_percentage': 0.75,
            'tax_bracket_percentage': 10,
        },
    )

    own_fetch = client.get(
        '/financials/salary-structures/worker-employee',
        headers=auth_headers('worker@test.com'),
    )
    assert own_fetch.status_code == 200

    other_fetch = client.get(
        '/financials/salary-structures/target-employee',
        headers=auth_headers('worker@test.com'),
    )
    assert other_fetch.status_code == 403