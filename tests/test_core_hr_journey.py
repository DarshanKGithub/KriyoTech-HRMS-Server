"""Real API contracts using a foreign-key-enforced database and no HTTP mocks."""
from datetime import date, datetime, timedelta, timezone
from calendar import monthrange
import hashlib, hmac, json, os
import pytest
from sqlalchemy import create_engine, event, select
from app.db.database import OwnedSession as Session
from sqlalchemy.pool import StaticPool
from app.db.database import Base, get_db
from app.db.models import Tenant, User, Employee, Plan, Subscription, TenantFeature, Attendance, Salary, Payslip, LeaveRequest, LeaveBalance, Candidate
from app.core.security import hash_password, create_access_token
from app.http import override_dependencies
from app.testing import APIClient
from app.core.config import settings

@pytest.fixture
def api():
    target=os.environ.get('HRMS_TEST_DATABASE_URL','sqlite://')
    engine=create_engine(target,**({'connect_args':{'check_same_thread':False},'poolclass':StaticPool} if target.startswith('sqlite') else {}))
    if target.startswith('sqlite'):
        @event.listens_for(engine,'connect')
        def fk(connection,_): connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False,autoflush=False) as db:
        db.add_all([Tenant(id='a',name='Company A'),Tenant(id='b',name='Company B')]); db.flush()
        db.add(Plan(id='plan',name='Test plan',price_cents=1000)); db.flush()
        for tenant in ['a','b']:
            for role,key in [('CEO','owner'),('HR','hr'),('Manager','manager'),('Employee','employee'),('Employee','unrelated')]:
                identifier=f'{tenant}-{key}'
                db.add(User(id=identifier,tenant_id=tenant,full_name=identifier,email=f'{identifier}@example.test',role=role,password_hash=hash_password('TestPassword123!')))
                db.add(Employee(id=identifier,tenant_id=tenant,full_name=identifier,email=f'{identifier}@example.test',manager_id=None))
            db.add(Subscription(tenant_id=tenant,plan_id='plan',starts_at=date(2020,1,1),ends_at=date(2200,1,1),status='active'))
            for feature in ['attendance_module','payroll_module','document_module','performance_module','helpdesk_module']:
                db.add(TenantFeature(tenant_id=tenant,feature_key=feature,enabled=True))
        db.add(User(id='platform',full_name='Platform',email='platform@example.test',role='Super Admin',password_hash=hash_password('TestPassword123!')))
        db.commit()
        db.get(Employee,'a-employee').manager_id='a-manager'; db.commit()
        def database(): yield db
        with override_dependencies({get_db:database}): yield APIClient(),db
    if not target.startswith('sqlite'):
        Base.metadata.drop_all(engine)
    engine.dispose()

def auth(key): return {'Authorization':'Bearer '+create_access_token({'sub':f'{key}@example.test'})}

def test_public_registration_is_atomic_and_owner_can_sign_in(api):
    client,db=api
    response=client.post('/auth/register',json={'company_name':'New Company','admin_name':'New Owner','admin_email':'new@example.test','password':'TestPassword123!'})
    assert response.status_code==200,response.content
    assert client.post('/auth/login',json={'email':'new@example.test','password':'TestPassword123!'}).status_code==200
    assert client.post('/auth/register',json={'company_name':'Another','admin_name':'Owner','admin_email':'new@example.test','password':'TestPassword123!'}).status_code==409


def test_tenant_and_manager_queries_and_foreign_references_are_scoped(api):
    client,db=api
    created=client.post('/recruitment/candidates',headers=auth('b-hr'),json={'first_name':'Private','last_name':'Candidate','email':'private@example.test'})
    assert created.status_code==200,created.content
    listed=client.get('/recruitment/candidates',headers=auth('a-hr'))
    assert listed.status_code==200 and listed.json()==[]
    own=client.get('/employees/?size=100',headers=auth('a-manager'))
    assert own.status_code==200,own.content
    assert {item['id'] for item in own.json()['items']}=={'a-employee'}
    forbidden=client.post('/financials/salary-structures',headers=auth('a-hr'),json={'employee_id':'b-employee','base_salary':1000,'hra':0,'da':0,'special_allowance':0,'pf_percentage':0,'esi_percentage':0,'tax_bracket_percentage':0})
    assert forbidden.status_code==404,forbidden.content
    cross=client.post('/recruitment/applications',headers=auth('a-hr'),json={'job_id':'foreign-job','candidate_id':created.json()['id'],'status':'Applied'})
    assert cross.status_code in {403,404},cross.content


def test_inactive_tenant_and_expired_or_disabled_modules_are_rejected(api):
    client,db=api
    db.get(Tenant,'b').is_active=False; db.commit()
    assert client.get('/auth/me',headers=auth('b-owner')).status_code==403
    assert client.post('/auth/login',json={'email':'b-owner@example.test','password':'TestPassword123!'}).status_code==403
    db.info.pop('actor',None)
    for row in db.scalars(select(Subscription).where(Subscription.tenant_id=='a')): row.ends_at=date(2020,1,1)
    db.commit()
    assert client.get('/payroll/components',headers=auth('a-hr')).status_code==403
    db.info.pop('actor',None)
    for row in db.scalars(select(Subscription).where(Subscription.tenant_id=='a')): row.ends_at=date(2200,1,1)
    for row in db.scalars(select(TenantFeature).where(TenantFeature.tenant_id=='a',TenantFeature.feature_key=='attendance_module')): row.enabled=False
    db.commit()
    assert client.get('/attendance/shifts',headers=auth('a-employee')).status_code==403


def test_company_setup_leave_approval_and_payroll_pdf_journey(api):
    client,db=api
    assert client.put('/org/settings',headers=auth('a-owner'),json={'timezone':'Asia/Kolkata','working_days':[0,1,2,3,4]}).status_code==200
    assert client.post('/org/departments',headers=auth('a-owner'),json={'name':'Engineering'}).status_code==200
    policy=client.post('/org/leave-types',headers=auth('a-hr'),json={'name':'Annual leave','default_days_per_year':10,'is_paid':True})
    assert policy.status_code==200,policy.content
    leave_type=policy.json()['id']
    balance=client.put('/org/leave-balances',headers=auth('a-hr'),json={'employee_id':'a-employee','leave_type_id':leave_type,'year':2026,'granted_days':10})
    assert balance.status_code==200,balance.content
    request=client.post('/leave/requests',headers=auth('a-employee'),json={'leave_type_id':leave_type,'start_date':'2026-09-02','end_date':'2026-09-02','reason':'Annual leave'})
    assert request.status_code==200,request.content
    identifier=request.json()['id']
    assert request.json()['status']=='pending_manager'
    assert client.post(f'/leave/requests/{identifier}/approve',headers=auth('b-manager'),json={'approve':True}).status_code in {403,404}
    assert client.post(f'/leave/requests/{identifier}/approve',headers=auth('a-manager'),json={'approve':True}).json()['status']=='pending_hr'
    assert client.post(f'/leave/requests/{identifier}/approve',headers=auth('a-hr'),json={'approve':True}).json()['status']=='approved'
    assert client.post(f'/leave/requests/{identifier}/approve',headers=auth('a-hr'),json={'approve':True}).status_code==400
    balances=client.get('/leave/balances',headers=auth('a-employee')).json()
    assert balances[0]['balance_days']==9
    salary=client.post('/financials/salary-structures',headers=auth('a-hr'),json={'employee_id':'a-employee','base_salary':22000,'hra':0,'da':0,'special_allowance':0,'pf_percentage':0,'esi_percentage':0,'tax_bracket_percentage':0,'effective_from':'2026-09-01'})
    assert salary.status_code==200,salary.content
    db.info.pop('actor',None)
    db.add(Attendance(tenant_id='a',employee_id='a-employee',attendance_date=date(2026,9,1),check_in_time=datetime(2026,9,1,4,tzinfo=timezone.utc),is_half_day=True,status='half-day')); db.commit()
    slip=client.post('/payroll/payslips',headers=auth('a-hr'),json={'employee_id':'a-employee','month':9,'year':2026})
    assert slip.status_code==200,slip.content
    assert slip.json()['days_worked']==.5
    assert slip.json()['net_salary']==1500 # 22 weekdays: half day attendance + one paid leave
    identifier=slip.json()['id']
    assert client.post(f'/payroll/payslips/{identifier}/approve',headers=auth('a-hr')).status_code==200
    pdf=client.get(f'/payroll/payslips/{identifier}/pdf',headers=auth('a-employee'))
    assert pdf.status_code==200,pdf.content if not pdf.streaming else 'stream'
    assert b''.join(pdf.streaming_content).startswith(b'%PDF-')
    assert client.get(f'/payroll/payslips/{identifier}/pdf',headers=auth('b-employee')).status_code in {403,404}
    assert client.post('/payroll/payslips',headers=auth('a-hr'),json={'employee_id':'a-employee','month':9,'year':2026}).status_code==409


def test_bulk_approval_rejects_unrelated_manager_and_billing_fails_closed(api,monkeypatch):
    client,db=api
    policy=client.post('/org/leave-types',headers=auth('a-hr'),json={'name':'Paid leave','default_days_per_year':10}).json()['id']
    request=client.post('/leave/requests',headers=auth('a-unrelated'),json={'leave_type_id':policy,'start_date':'2026-09-03','end_date':'2026-09-03'}).json()['id']
    result=client.post('/leave/requests/bulk-approve',headers=auth('a-manager'),json={'request_ids':[request],'approve':True})
    assert result.status_code==200,result.content
    assert result.json()['failed']==1
    assert client.post('/billing/create-order',json={'tenant_id':'a','plan_id':'plan'}).status_code==401
    monkeypatch.setattr(settings,'razorpay_webhook_secret',None)
    assert client.post('/billing/webhook',json={'event':'order.paid'}).status_code==503
    monkeypatch.setattr(settings,'razorpay_webhook_secret','test-webhook-secret')
    assert client.post('/billing/webhook',json={'event':'order.paid'},headers={'X-Razorpay-Signature':'invalid'}).status_code==400

def test_attendance_breaks_business_timezone_and_half_day_policy(api):
    client,db=api
    shift=client.post('/attendance/shifts',headers=auth('a-hr'),json={'name':'Day shift','start_time':'09:00:00','end_time':'18:00:00','grace_period_minutes':5})
    assert shift.status_code==200,shift.content
    assignment=client.post('/attendance/employees/a-employee/shift-assignment',headers=auth('a-hr'),json={'employee_id':'a-employee','shift_id':shift.json()['id'],'start_date':'2026-01-01','is_active':True})
    assert assignment.status_code==200,assignment.content
    payload={'employee_id':'a-employee','attendance_date':'2026-09-01','check_in_time':'2026-09-01T03:30:00Z'}
    checked=client.post('/attendance/check-in',headers=auth('a-employee'),json=payload)
    assert checked.status_code==200,checked.content
    assert checked.json()['late_minutes']==0 # 09:00 in Asia/Kolkata
    assert client.post('/attendance/check-in',headers=auth('a-employee'),json=payload).status_code==409
    base={'employee_id':'a-employee','attendance_date':'2026-09-01'}
    started=client.post('/attendance/start-break',headers=auth('a-employee'),json={**base,'start_time':'2026-09-01T07:00:00Z','break_type':'lunch'})
    assert started.status_code==200,started.content
    assert client.post('/attendance/check-out',headers=auth('a-employee'),json={**base,'check_out_time':'2026-09-01T12:30:00Z'}).status_code==409
    assert client.post('/attendance/end-break',headers=auth('a-employee'),json={**base,'end_time':'2026-09-01T07:30:00Z'}).status_code==200
    assert client.post('/attendance/check-out',headers=auth('a-employee'),json={**base,'check_out_time':'2026-09-01T12:30:00Z'}).status_code==200
    assert client.post('/attendance/check-out',headers=auth('a-employee'),json={**base,'check_out_time':'2026-09-01T12:30:00Z'}).status_code==409


def test_half_day_leave_overlap_rejection_and_pending_dashboard(api):
    client,db=api
    kind=client.post('/org/leave-types',headers=auth('a-hr'),json={'name':'Half-day policy','default_days_per_year':4}).json()['id']
    request=client.post('/leave/requests',headers=auth('a-employee'),json={'leave_type_id':kind,'start_date':'2026-09-04','end_date':'2026-09-04','session_from':'Session 1','session_to':'Session 1'})
    assert request.status_code==200,request.content
    assert request.json()['days_requested']==.5
    overlapping=client.post('/leave/requests',headers=auth('a-employee'),json={'leave_type_id':kind,'start_date':'2026-09-04','end_date':'2026-09-04'})
    assert overlapping.status_code==409
    dashboard=client.get('/dashboard/workspace',headers=auth('a-manager'))
    assert dashboard.status_code==200,dashboard.content
    assert any(item['id']==request.json()['id'] for item in dashboard.json()['pending_leaves'])
    assert client.post('/leave/requests/'+request.json()['id']+'/approve',headers=auth('a-manager'),json={'approve':False}).json()['status']=='rejected'
    assert client.get('/leave/balances',headers=auth('a-employee')).json()==[]


def test_verified_payment_replay_and_amount_mismatch(api,monkeypatch):
    client,db=api
    db.info.pop('actor',None)
    db.add(Subscription(id='pending',tenant_id='a',plan_id='plan',starts_at=date.today(),status='pending_payment',price_paid_cents=1000,external_order_id='order_test'))
    db.commit()
    monkeypatch.setattr(settings,'razorpay_webhook_secret','local-test-secret')
    def send(amount):
        payload={'event':'payment.captured','payload':{'payment':{'entity':{'order_id':'order_test','amount':amount,'currency':'INR','status':'captured'}}}}
        raw=json.dumps(payload).encode()
        signature=hmac.new(b'local-test-secret',raw,hashlib.sha256).hexdigest()
        return client.post('/billing/webhook',data=raw,content_type='application/json',headers={'X-Razorpay-Signature':signature,'Content-Type':'application/json'})
    assert send(1).status_code==400
    assert send(1000).status_code==200
    end=db.get(Subscription,'pending').ends_at
    assert send(1000).status_code==200
    assert db.get(Subscription,'pending').ends_at==end
    assert client.patch('/admin/users/a-employee/tenant?tenant_id=b',headers=auth('platform')).status_code==409


def test_correction_preserves_half_days_and_blocks_foreign_links(api):
    client,db=api
    db.info.pop('actor',None)
    from app.db.models import AttendanceRule
    db.add(AttendanceRule(tenant_id='a',name='Half day',rule_type='half_day',threshold_minutes=240,is_active=True))
    db.add(Attendance(id='other-attendance',tenant_id='a',employee_id='a-unrelated',attendance_date=date(2026,9,3),status='present'))
    db.commit()
    body={'employee_id':'a-employee','date':'2026-09-03','reason':'Missing punch','requested_check_in':'2026-09-03T03:30:00Z','requested_check_out':'2026-09-03T05:30:00Z'}
    foreign=client.post('/advanced-attendance/regularizations',headers=auth('a-employee'),json={**body,'attendance_id':'other-attendance'})
    assert foreign.status_code==400,foreign.content
    created=client.post('/advanced-attendance/regularizations',headers=auth('a-employee'),json=body)
    assert created.status_code==200,created.content
    identifier=created.json()['id']
    assert client.post(f'/advanced-attendance/regularizations/{identifier}/approve',headers=auth('b-hr')).status_code==404
    approved=client.post(f'/advanced-attendance/regularizations/{identifier}/approve',headers=auth('a-hr'))
    assert approved.status_code==200,approved.content
    rows=client.get('/attendance/?employee_id=a-employee&start_date=2026-09-03&end_date=2026-09-03',headers=auth('a-hr'))
    assert rows.status_code==200,rows.content
    assert rows.json()['items'][0]['is_half_day'] is True
