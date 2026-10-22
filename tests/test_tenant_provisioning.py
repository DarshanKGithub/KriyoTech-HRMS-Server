"""Client provisioning must honor real database foreign keys and remain atomic."""
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.database import Base, get_db
from app.db.models import Tenant, Employee, User
from app.http import override_dependencies
from app.testing import APIClient


@pytest.fixture
def provisioning():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
        db.add(User(id='platform', full_name='Platform Admin', email='platform@example.test', role='Super Admin', password_hash=hash_password('TestPassword123!')))
        db.commit()
        def database():
            yield db
        with override_dependencies({get_db: database}):
            yield APIClient(), db, {'Authorization': 'Bearer ' + create_access_token({'sub': 'platform@example.test'})}
    engine.dispose()


def payload(**changes):
    return {'name': 'Test Organization', 'domain': 'client.example.test', 'admin_name': 'Client Owner', 'admin_email': 'owner@example.test', 'admin_password': 'TestPassword123!', **changes}


def test_tenant_creation_inserts_parent_before_employee_and_links_login(provisioning):
    client, db, headers = provisioning
    response = client.post('/admin/tenants', headers=headers, json=payload())
    assert response.status_code == 200, response.content
    tenant_id = response.json()['id']
    owner = db.scalar(select(User).where(User.email == 'owner@example.test'))
    employee = db.scalar(select(Employee).where(Employee.email == owner.email))
    assert owner.tenant_id == employee.tenant_id == tenant_id
    assert owner.role == 'CEO' and owner.id == employee.id
    login = client.post('/auth/login', json={'email': owner.email, 'password': 'TestPassword123!'})
    assert login.status_code == 200
    assert login.json()['user']['employee_id'] == employee.id


@pytest.mark.parametrize('changes', [
    {'domain': 'other.example.test'},
    {'admin_email': 'other@example.test'},
])
def test_duplicate_email_or_domain_returns_conflict_without_partial_records(provisioning, changes):
    client, db, headers = provisioning
    assert client.post('/admin/tenants', headers=headers, json=payload()).status_code == 200
    response = client.post('/admin/tenants', headers=headers, json=payload(**changes))
    assert response.status_code == 409, response.content
    assert db.scalar(select(func.count(Tenant.id))) == 1
    assert db.scalar(select(func.count(Employee.id))) == 1
    assert db.scalar(select(func.count(User.id))) == 2

def test_commit_conflict_rolls_back_the_new_tenant(provisioning, monkeypatch):
    import sqlite3
    from sqlalchemy.exc import IntegrityError
    client, db, headers = provisioning
    def conflicting_commit():
        raise IntegrityError('INSERT INTO users', {}, sqlite3.IntegrityError('UNIQUE constraint failed: users.email'))
    monkeypatch.setattr(db, 'commit', conflicting_commit)
    response = client.post('/admin/tenants', headers=headers, json=payload())
    assert response.status_code == 409
    assert db.scalar(select(func.count(Tenant.id))) == 0
    assert db.scalar(select(func.count(Employee.id))) == 0
    assert db.scalar(select(func.count(User.id))) == 1
