import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Candidate, Employee
from app.schemas.lifecycle import AssetCreate, ExitCreate, OnboardingCreate, OfferCreate
from app.schemas.lifecycle import AssetUpdate, ExitUpdate, OnboardingUpdate, OfferUpdate
from app.services.lifecycle_service import (
    create_asset,
    create_exit_case,
    create_onboarding,
    create_offer,
    lifecycle_counts,
    update_asset,
    update_exit_case,
    update_onboarding,
    update_offer,
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


def seed_employee(session):
    employee = Employee(full_name='Lifecycle Employee', email='lifecycle@example.com')
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


def seed_candidate(session):
    candidate = Candidate(first_name='Life', last_name='Cycle', email='candidate@example.com')
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def test_lifecycle_counts_and_offer_flow(db_session):
    employee = seed_employee(db_session)
    candidate = seed_candidate(db_session)

    offer = create_offer(
        db_session,
        OfferCreate(
            employee_id=employee.id,
            candidate_id=candidate.id,
            title='Software Engineer Offer',
            salary_amount=850000,
            status='Draft',
        ),
    )
    assert offer.status == 'Draft'

    updated_offer = update_offer(db_session, offer.id, OfferUpdate(status='Sent'))
    assert updated_offer.status == 'Sent'

    counts = lifecycle_counts(db_session)
    assert counts['offers'] == 1
    assert counts['onboarding'] == 0
    assert counts['exits'] == 0
    assert counts['assets'] == 0


def test_onboarding_exit_and_asset_flows(db_session):
    employee = seed_employee(db_session)

    onboarding = create_onboarding(
        db_session,
        OnboardingCreate(employee_id=employee.id, checklist='["Laptop", "Email account"]', status='Initiated'),
    )
    assert onboarding.status == 'Initiated'
    updated_onboarding = update_onboarding(db_session, onboarding.id, OnboardingUpdate(status='Completed'))
    assert updated_onboarding.status == 'Completed'

    exit_case = create_exit_case(
        db_session,
        ExitCreate(employee_id=employee.id, exit_type='Resignation', status='Requested', settlement_amount=12000),
    )
    assert exit_case.exit_type == 'Resignation'
    updated_exit = update_exit_case(db_session, exit_case.id, ExitUpdate(status='Approved'))
    assert updated_exit.status == 'Approved'

    asset = create_asset(
        db_session,
        AssetCreate(asset_tag='LAP-001', name='Developer Laptop', category='IT Equipment', employee_id=employee.id),
    )
    assert asset.status == 'Assigned'
    updated_asset = update_asset(db_session, asset.id, AssetUpdate(status='Assigned', employee_id=employee.id))
    assert updated_asset.status == 'Assigned'
    assert updated_asset.employee_id == employee.id
