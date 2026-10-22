from tests.company_fixtures import company_fixture
import pytest
from app.testing import APIClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.database import Base, get_db
from app.db.models import Candidate, Employee, User
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
    employee = Employee(full_name='Lifecycle Employee', email='lifecycle@example.com')
    candidate = Candidate(first_name='Life', last_name='Cycle', email='candidate@example.com')
    session.add_all([admin, employee, candidate])
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



def auth_headers():
    token = create_access_token({'sub': 'admin@test.com'})
    return {'Authorization': f'Bearer {token}'}


def test_lifecycle_endpoints_flow(client, db_session):
    employee = db_session.query(Employee).filter(Employee.email == 'lifecycle@example.com').first()
    candidate = db_session.query(Candidate).filter(Candidate.email == 'candidate@example.com').first()

    offer_res = client.post(
        '/lifecycle/offers',
        headers=auth_headers(),
        json={
            'employee_id': employee.id,
            'candidate_id': candidate.id,
            'title': 'Software Engineer Offer',
            'salary_amount': 900000,
            'joining_date': '2026-06-01',
            'status': 'Draft',
            'notes': 'Priority hire',
        },
    )
    assert offer_res.status_code == 200
    offer = offer_res.json()

    offer_update = client.put(
        f"/lifecycle/offers/{offer['id']}",
        headers=auth_headers(),
        json={'status': 'Sent'},
    )
    assert offer_update.status_code == 200
    assert offer_update.json()['status'] == 'Sent'

    onboarding_res = client.post(
        '/lifecycle/onboarding',
        headers=auth_headers(),
        json={
            'employee_id': employee.id,
            'probation_end_date': '2026-09-01',
            'checklist': '["Laptop", "Email account"]',
            'status': 'Initiated',
        },
    )
    assert onboarding_res.status_code == 200
    onboarding = onboarding_res.json()

    onboarding_update = client.put(
        f"/lifecycle/onboarding/{onboarding['id']}",
        headers=auth_headers(),
        json={'status': 'Completed'},
    )
    assert onboarding_update.status_code == 200
    assert onboarding_update.json()['status'] == 'Completed'

    exit_res = client.post(
        '/lifecycle/exits',
        headers=auth_headers(),
        json={
            'employee_id': employee.id,
            'exit_type': 'Resignation',
            'status': 'Requested',
            'settlement_amount': 15000,
        },
    )
    assert exit_res.status_code == 200
    exit_case = exit_res.json()

    exit_update = client.put(
        f"/lifecycle/exits/{exit_case['id']}",
        headers=auth_headers(),
        json={'status': 'Approved'},
    )
    assert exit_update.status_code == 200
    assert exit_update.json()['status'] == 'Approved'

    asset_res = client.post(
        '/lifecycle/assets',
        headers=auth_headers(),
        json={
            'asset_tag': 'LAP-001',
            'name': 'Developer Laptop',
            'category': 'IT Equipment',
            'employee_id': employee.id,
            'status': 'Available',
        },
    )
    assert asset_res.status_code == 200
    asset = asset_res.json()

    asset_update = client.put(
        f"/lifecycle/assets/{asset['id']}",
        headers=auth_headers(),
        json={'status': 'Assigned'},
    )
    assert asset_update.status_code == 200
    assert asset_update.json()['status'] == 'Assigned'

    summary_res = client.get('/lifecycle/summary', headers=auth_headers())
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary['offers'] == 1
    assert summary['onboarding'] == 1
    assert summary['exits'] == 1
    assert summary['assets'] == 1
