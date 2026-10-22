"""Regression coverage for tenant, platform and personal-workspace boundaries."""
from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.testing import APIClient
from app.http import HTTPException, override_dependencies
from app.db.database import Base, get_db
from app.db.models import Tenant, User, Employee, Department, LeaveType, LeaveBalance
from app.core.security import hash_password, create_access_token
from app.schemas.employee import EmployeeCreateWithAccount, EmployeeUpdate
from app.services.employee_service import create_employee, update_employee
from app.services.workspace_service import workspace_dashboard
from app.services.document_service import save_employee_document, downloadable_document
from app.services.auth_service import get_user_from_token


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        session.add_all([Tenant(id='a', name='Organization A'), Tenant(id='b', name='Organization B')])
        session.flush()
        for tenant, role, key in [('a', 'HR', 'hr-a'), ('a', 'Employee', 'employee-a'), ('b', 'Employee', 'employee-b'), (None, 'Super Admin', 'platform')]:
            session.add(User(id=key, tenant_id=tenant, full_name=key, email=f'{key}@test.example', role=role, password_hash=hash_password('test-password')))
            if tenant:
                session.add(Employee(id=key, tenant_id=tenant, full_name=key, email=f'{key}@test.example'))
        session.commit()
        yield session
    engine.dispose()


def test_employee_provisioning_preserves_tenant(db):
    payload = EmployeeCreateWithAccount(full_name='New Hire', email='new@test.example', password='Secure123!', role='Employee')
    employee = create_employee(payload, db, actor_id='hr-a', tenant_id='a')
    assert employee.tenant_id == 'a'
    assert db.get(User, employee.id).tenant_id == 'a'


def test_cross_tenant_manager_assignment_is_rejected(db):
    payload = EmployeeCreateWithAccount(full_name='New Hire', email='new@test.example', password='Secure123!', role='Employee', manager_id='employee-b')
    with pytest.raises(HTTPException) as exc:
        create_employee(payload, db, tenant_id='a')
    assert exc.value.status_code == 400
    assert db.scalar(select(User).where(User.email == payload.email)) is None


def test_nullable_employment_fields_can_be_cleared(db):
    employee = db.get(Employee, 'employee-a')
    employee.manager_id = 'hr-a'
    db.commit()
    updated = update_employee(employee.id, EmployeeUpdate(manager_id=None), db, tenant_id='a')
    assert updated.manager_id is None


def test_workspace_scopes_hr_and_employee_data(db):
    hr = workspace_dashboard(db.get(User, 'hr-a'), db)
    assert hr['scope'] == 'organization'
    assert next(metric['value'] for metric in hr['metrics'] if metric['key'] == 'employees') == 2
    assert workspace_dashboard(db.get(User, 'employee-b'), db)['scope'] == 'personal'
    platform = workspace_dashboard(db.get(User, 'platform'), db)
    assert platform['scope'] == 'platform'
    assert platform['attendance'] is None and platform['latest_payslip'] is None


def test_disabled_user_token_is_rejected(db):
    user = db.get(User, 'employee-a')
    user.is_active = False
    db.commit()
    with pytest.raises(HTTPException) as exc:
        get_user_from_token(create_access_token({'sub': user.email}), db)
    assert exc.value.status_code == 401


def test_documents_are_persisted_and_cannot_cross_tenants(db, tmp_path, monkeypatch):
    import app.services.document_service as service
    monkeypatch.setattr(service, 'UPLOAD_ROOT', tmp_path)
    file = SimpleNamespace(filename='employment.txt', file=BytesIO(b'private employee document'))
    document = save_employee_document('employee-a', 'Employment', file, db.get(User, 'hr-a'), db)
    assert document.uploaded_by == 'hr-a'
    assert downloadable_document(document.id, db.get(User, 'employee-a'), db)[1].read_bytes() == b'private employee document'
    with pytest.raises(HTTPException):
        downloadable_document(document.id, db.get(User, 'employee-b'), db)


def test_platform_admin_api_rejects_tenant_hr_and_allows_super_admin(db):
    def database():
        yield db
    with override_dependencies({get_db: database}):
        client = APIClient()
        assert client.get('/admin/tenants', headers={'Authorization': 'Bearer ' + create_access_token({'sub': 'hr-a@test.example'})}).status_code == 403
        assert client.get('/admin/tenants', headers={'Authorization': 'Bearer ' + create_access_token({'sub': 'platform@test.example'})}).status_code == 200


def test_employee_pagination_and_tenant_filter(db):
    def database():
        yield db
    auth = {'Authorization': 'Bearer ' + create_access_token({'sub': 'hr-a@test.example'})}
    with override_dependencies({get_db: database}):
        client = APIClient()
        response = client.get('/employees/?size=1&sort_by=full_name&sort_dir=desc', headers=auth)
        assert response.status_code == 200
        assert response.json()['total'] == 2
        assert len(response.json()['items']) == 1
        assert client.get('/employees/?page=0', headers=auth).status_code == 422

def test_organization_lookups_require_auth_and_remain_tenant_scoped(db):
    db.add_all([Department(id='dept-a', name='Engineering A', tenant_id='a'), Department(id='dept-b', name='Engineering B', tenant_id='b')])
    db.commit()
    def database():
        yield db
    with override_dependencies({get_db: database}):
        client = APIClient()
        assert client.get('/org/departments').status_code == 401
        auth = {'Authorization': 'Bearer ' + create_access_token({'sub': 'hr-a@test.example'})}
        response = client.get('/org/departments', headers=auth)
        assert response.status_code == 200
        assert [item['id'] for item in response.json()] == ['dept-a']
        platform = {'Authorization': 'Bearer ' + create_access_token({'sub': 'platform@test.example'})}
        assert client.get('/org/departments', headers=platform).status_code == 403


def test_manager_workspace_excludes_other_tenants_and_unassigned_employees(db):
    manager = db.get(User, 'hr-a')
    manager.role = 'Manager'
    db.get(Employee, 'employee-a').manager_id = 'hr-a'
    db.get(Employee, 'employee-b').manager_id = 'hr-a'
    db.commit()
    result = workspace_dashboard(manager, db)
    assert result['scope'] == 'team'
    assert next(metric['value'] for metric in result['metrics'] if metric['key'] == 'employees') == 1
