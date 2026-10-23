"""Migration contracts exercised through Django, using an isolated database."""
import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.testing import APIClient
from app.http import Depends, File, Form, Query, Router, StreamingResponse, UploadFile, override_dependencies, url_patterns
from app.db.database import Base, get_db
from app.db.models import Employee, User, Tenant
from app.core.security import hash_password


@pytest.fixture
def api():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        db.add(Tenant(id='django-tenant', name='Django Test'))
        db.flush()
        user = User(id='django-user', tenant_id='django-tenant', full_name='Django Admin', email='django@example.com', role='Admin', password_hash=hash_password('StrongPass123'))
        db.add(user)
        db.add(Employee(id=user.id, tenant_id='django-tenant', full_name=user.full_name, email=user.email))
        db.commit()

        def database():
            yield db

        with override_dependencies({get_db: database}):
            yield APIClient()
    engine.dispose()


def headers(api):
    response = api.post('/auth/login', json={'email': 'django@example.com', 'password': 'StrongPass123'})
    assert response.status_code == 200, response.content
    body = response.json()
    assert body['token_type'] == 'bearer'
    assert 'password_hash' not in body['user']
    return {'Authorization': f"Bearer {body['access_token']}"}


def test_login_profile_permissions_and_employee_list(api):
    auth = headers(api)
    assert api.get('/auth/me', headers=auth).json()['id'] == 'django-user'
    assert '*' in api.get('/auth/me/permissions', headers=auth).json()['permissions']
    for path in ('/employees', '/employees/'):
        response = api.get(path, headers=auth)
        assert response.status_code == 200
        assert response.json()['total'] == 1


def test_login_and_validation_errors(api):
    assert api.post('/auth/login', json={'email': 'django@example.com', 'password': 'WrongPass123'}).status_code == 401
    assert api.post('/auth/login', json={}).status_code == 422
    response = api.post('/auth/login', data='{broken', content_type='application/json')
    assert response.status_code == 422
    assert response.json()['error_code'] == 'VALIDATION_ERROR'
    assert api.get('/auth/me').status_code == 401
    assert api.get('/auth/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401


def test_cors_health_not_found_and_method_handling(api):
    assert api.get('/health').json() == {'status': 'ok'}
    assert api.get('/health/').status_code == 200
    assert api.get('/missing-api').status_code == 404
    response = api.get('/auth/login')
    assert response.status_code == 405
    assert response['Allow'] == 'POST'
    response = api.options('/auth/login', headers={
        'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization,content-type',
    })
    assert response.status_code == 204
    assert response['Access-Control-Allow-Origin'] == 'http://localhost:3000'
    assert api.options('/auth/login', headers={'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'POST'}).status_code == 403


def test_all_existing_routes_are_registered():
    from config.urls import ROUTERS
    from importlib import import_module
    routers = [import_module(f'app.api.routes.{name}').router for name, _ in ROUTERS]
    assert len(routers) == 21
    assert sum(len(router.routes) for router in routers) >= 245


def test_dependency_cache_cleanup_query_parsing_and_response_filtering():
    calls = []

    def resource():
        calls.append('open')
        try:
            yield object()
        finally:
            calls.append('close')

    class Public(BaseModel):
        count: int
        day: date

    router = Router()

    @router.get('/report', response_model=Public)
    def report(count: int = Query(1, ge=1, le=10), day: date = Query(...), first=Depends(resource), second=Depends(resource)):
        assert first is second
        return {'count': count, 'day': day, 'secret': 'must not serialize'}

    view = url_patterns([('', router)])[0].callback
    factory = RequestFactory()
    result = view(factory.get('/report?count=3&day=2026-10-22'))
    import json
    assert json.loads(result.content) == {'count': 3, 'day': '2026-10-22'}
    assert calls == ['open', 'close']
    assert view(factory.get('/report?count=0&day=2026-10-22')).status_code == 422
    assert view(factory.get('/report?day=invalid')).status_code == 422


def test_multipart_and_binary_download():
    router = Router()

    @router.post('/upload')
    def upload(document_type: str = Form(...), file: UploadFile = File(...)):
        return {'name': file.filename, 'type': document_type, 'size': len(file.file.read())}

    @router.get('/download')
    def download():
        return StreamingResponse(io.BytesIO(b'a,b\n1,2\n'), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="report.csv"'})

    patterns = url_patterns([('', router)])
    factory = RequestFactory()
    uploaded = SimpleUploadedFile('test.txt', b'hello', content_type='text/plain')
    response = patterns[0].callback(factory.post('/upload', {'document_type': 'ID', 'file': uploaded}))
    import json
    assert json.loads(response.content) == {'name': 'test.txt', 'type': 'ID', 'size': 5}
    response = patterns[1].callback(factory.get('/download'))
    assert response['Content-Type'] == 'text/csv'
    assert b''.join(response.streaming_content) == b'a,b\n1,2\n'


def test_raw_django_request_body_for_webhooks(api):
    # Verify raw request handling reaches signature validation rather than failing
    # on the old await request.body() interface.
    assert api.post('/api/webhooks/razorpay', json={'event': 'ignored'}).status_code == 503
