"""Account recovery, session revocation, reversal, offboarding and proof review."""
from datetime import date,datetime,timedelta,timezone
import re
import pytest
from sqlalchemy import select
from tests.test_core_hr_journey import api,auth
from tests.mailbox import mailbox
from app.core.config import settings
from app.db.models import User,Employee,AccountToken,MailMessage,Notification
from app.services.mail_service import deliver_pending

@pytest.fixture
def smtp(monkeypatch):
    with mailbox() as server:
        for key,value in {'mail_transport':'smtp','smtp_server':'127.0.0.1','smtp_port':server.server_address[1],'smtp_use_tls':False,'smtp_username':None,'smtp_password':None,'smtp_from':'test@kriyohr.local','smtp_allow_insecure_loopback':True,'public_app_url':'http://localhost:3011'}.items():monkeypatch.setattr(settings,key,value)
        yield server

def logged(client,company='a',role='employee',password='TestPassword123!'):
    response=client.post('/auth/login',json={'email':f'{company}-{role}@example.test','password':password})
    assert response.status_code==200,response.content
    return {'Authorization':'Bearer '+response.json()['access_token']}

def token_from(message):return re.search(r'#token=([A-Za-z0-9_-]+)',message['body']).group(1)

def test_recovery_real_smtp_replay_and_session_revocation(api,smtp):
    client,db=api
    old=logged(client)
    unknown=client.post('/auth/forgot-password',json={'email':'unknown@example.test'})
    eligible=client.post('/auth/forgot-password',json={'email':'a-employee@example.test'})
    assert unknown.status_code==eligible.status_code==200
    assert unknown.json()==eligible.json()
    db.info.pop('actor',None)
    result=deliver_pending(db);assert result['sent']==1,result
    message=smtp.messages[0];raw=token_from(message)
    assert raw not in db.scalar(select(MailMessage)).encrypted_body
    assert message['to']=='a-employee@example.test'
    done=client.post('/auth/reset-password',json={'token':raw,'password':'ReplacementPass123!'})
    assert done.status_code==200,done.content
    assert client.get('/auth/me',headers=old).status_code==401
    assert client.post('/auth/reset-password',json={'token':raw,'password':'AnotherPassword123!'}).status_code==400
    logged(client,password='ReplacementPass123!')
    assert db.get(User,'a-employee').email_verified is True

def test_invitation_is_single_use_and_cannot_revive_offboarded_employee(api,smtp):
    client,db=api
    assert client.post('/auth/invitations',headers=auth('b-hr'),json={'employee_id':'a-employee'}).status_code==404
    invited=client.post('/auth/invitations',headers=auth('a-hr'),json={'employee_id':'a-employee'})
    assert invited.status_code==200,invited.content
    db.info.pop('actor',None);result=deliver_pending(db);assert result['sent']==1,result
    raw=token_from(smtp.messages[-1])
    accepted=client.post('/auth/accept-invitation',json={'token':raw,'password':'InvitedPassword123!'})
    assert accepted.status_code==200,accepted.content
    assert client.post('/auth/accept-invitation',json={'token':raw,'password':'InvitedPassword123!'}).status_code==400
    logged(client,password='InvitedPassword123!')
    assert client.post('/auth/invitations',headers=auth('a-hr'),json={'employee_id':'a-employee'}).status_code==409
    db.info.pop('actor',None);db.get(Employee,'a-unrelated').is_active=False;db.commit()
    assert client.post('/auth/invitations',headers=auth('a-hr'),json={'employee_id':'a-unrelated'}).status_code==404

def test_login_throttling_and_session_logout(api,monkeypatch):
    client,db=api
    monkeypatch.setattr(settings,'login_attempt_limit',3)
    for _ in range(3): assert client.post('/auth/login',json={'email':'a-unrelated@example.test','password':'wrong'}).status_code==401
    assert client.post('/auth/login',json={'email':'a-unrelated@example.test','password':'TestPassword123!'}).status_code==429
    first=logged(client);second=logged(client)
    rows=client.get('/auth/sessions',headers=first).json();assert len(rows)==2
    assert client.post('/auth/sessions/'+rows[0]['id']+'/revoke',headers=auth('b-employee')).status_code==404
    assert client.post('/auth/logout',headers=first).status_code==200
    assert client.get('/auth/me',headers=first).status_code==401
    assert client.get('/auth/me',headers=second).status_code==200
    assert client.post('/auth/sessions/revoke-all',headers=second).status_code==200
    assert client.get('/auth/me',headers=second).status_code==401
    assert client.get('/auth/me',headers=auth('a-employee')).status_code==401 # no legacy-token bypass

def test_leave_reversal_once_and_notification_ownership(api):
    client,db=api
    policy=client.post('/org/leave-types',headers=auth('a-hr'),json={'name':'Reversal policy','default_days_per_year':10}).json()['id']
    request=client.post('/leave/requests',headers=auth('a-employee'),json={'leave_type_id':policy,'start_date':'2026-09-02','end_date':'2026-09-02'}).json()['id']
    for actor in ['a-manager','a-hr']: assert client.post(f'/leave/requests/{request}/approve',headers=auth(actor),json={'approve':True}).status_code==200
    assert client.get('/leave/balances',headers=auth('a-employee')).json()[0]['balance_days']==9
    assert client.post(f'/leave/requests/{request}/cancel',headers=auth('b-hr')).status_code==404
    assert client.post(f'/leave/requests/{request}/cancel',headers=auth('a-hr')).status_code==200
    assert client.post(f'/leave/requests/{request}/cancel',headers=auth('a-hr')).status_code==200
    assert client.get('/leave/balances',headers=auth('a-employee')).json()[0]['balance_days']==10
    own=client.get('/notifications/user/me/notifications',headers=auth('a-employee'))
    assert own.status_code==200,own.content
    db.info.pop('actor',None)
    assert db.scalar(select(Notification.id).where(Notification.recipient_id=='a-employee',Notification.event_type=='leave_cancelled'))
    foreign=client.get('/notifications/user/me/notifications',headers=auth('b-employee'))
    assert 'leave_cancelled' not in foreign.content.decode()

def test_leave_approval_after_payroll_preserves_pending_state_and_balance(api):
    from app.db.models import Payslip, LeaveRequest
    client, db = api
    policy = client.post('/org/leave-types', headers=auth('a-hr'), json={'name':'Payroll locked leave','default_days_per_year':10}).json()['id']
    assert client.put('/org/leave-balances', headers=auth('a-hr'), json={'employee_id':'a-employee','leave_type_id':policy,'year':2026,'granted_days':10}).status_code == 200
    request = client.post('/leave/requests', headers=auth('a-employee'), json={'leave_type_id':policy,'start_date':'2026-09-03','end_date':'2026-09-03'}).json()['id']
    assert client.post(f'/leave/requests/{request}/approve', headers=auth('a-manager'), json={'approve':True}).status_code == 200
    db.info.pop('actor', None)
    db.add(Payslip(tenant_id='a', employee_id='a-employee', month=9, year=2026, base_salary=1000, gross_salary=1000, net_salary=1000))
    db.commit()
    response = client.post(f'/leave/requests/{request}/approve', headers=auth('a-hr'), json={'approve':True})
    assert response.status_code == 409, response.content
    assert db.get(LeaveRequest, request).status == 'pending_hr'
    assert client.get('/leave/balances', headers=auth('a-employee')).json()[0]['balance_days'] == 10


def test_attendance_rule_setup_permissions_and_company_scope(api):
    client, db = api
    payload = {'name':'Half day','rule_type':'half_day','threshold_minutes':240,'is_active':True}
    assert client.post('/attendance/rules', headers=auth('a-employee'), json=payload).status_code == 403
    saved = client.post('/attendance/rules', headers=auth('a-hr'), json=payload)
    assert saved.status_code == 200, saved.content
    assert client.get('/attendance/rules', headers=auth('b-hr')).json() == []
    updated = client.post('/attendance/rules', headers=auth('a-hr'), json={**payload,'threshold_minutes':180})
    assert updated.json()['id'] == saved.json()['id']
    assert len(client.get('/attendance/rules', headers=auth('a-hr')).json()) == 1
    assert client.post('/attendance/rules', headers=auth('a-hr'), json={**payload,'threshold_minutes':-1}).status_code == 400


def test_exit_requires_asset_return_then_revokes_access(api):
    client,db=api
    session=logged(client)
    onboarding=client.post('/lifecycle/onboarding',headers=auth('a-hr'),json={'employee_id':'a-employee','checklist':'[{"label":"ID verified","done":false}]'}).json()['id']
    assert client.put(f'/lifecycle/onboarding/{onboarding}',headers=auth('a-hr'),json={'status':'Completed'}).status_code==409
    assert client.put(f'/lifecycle/onboarding/{onboarding}',headers=auth('a-hr'),json={'status':'Completed','checklist':'[{"label":"ID verified","done":true}]'}).status_code==200
    asset=client.post('/lifecycle/assets',headers=auth('a-hr'),json={'asset_tag':'HR-001','name':'Laptop','category':'IT','employee_id':'a-employee'}).json()['id']
    exit_case=client.post('/lifecycle/exits',headers=auth('a-hr'),json={'employee_id':'a-employee','exit_type':'Resignation','last_working_day':'2026-09-30'}).json()['id']
    assert client.put(f'/lifecycle/exits/{exit_case}',headers=auth('a-hr'),json={'status':'Closed'}).status_code==409
    returned=client.put(f'/lifecycle/assets/{asset}',headers=auth('a-hr'),json={'status':'Available'})
    assert returned.status_code==200 and returned.json()['employee_id'] is None,returned.content
    closed=client.put(f'/lifecycle/exits/{exit_case}',headers=auth('a-hr'),json={'status':'Closed'})
    assert closed.status_code==200,closed.content
    assert client.get('/auth/me',headers=session).status_code in {401,403}
    assert client.post('/auth/login',json={'email':'a-employee@example.test','password':'TestPassword123!'}).status_code==401
    assert client.get('/auth/me',headers=auth('b-employee')).status_code==200


def test_cross_module_recruitment_performance_helpdesk_proofs_reports(api,monkeypatch,tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from app.services import document_service
    monkeypatch.setattr(document_service,'UPLOAD_ROOT',tmp_path)
    client,db=api
    job=client.post('/recruitment/jobs',headers=auth('a-hr'),json={'title':'Software engineer','description':'Build HR products'})
    assert job.status_code==200,job.content
    candidate=client.post('/recruitment/candidates',headers=auth('a-hr'),json={'first_name':'New','last_name':'Hire','email':'hire@example.test'})
    assert candidate.status_code==200,candidate.content
    application=client.post('/recruitment/applications',headers=auth('a-hr'),json={'job_id':job.json()['id'],'candidate_id':candidate.json()['id']})
    assert application.status_code==200,application.content
    assert client.put('/recruitment/applications/'+application.json()['id']+'/status',headers=auth('a-hr'),json={'status':'Hired'}).status_code==200
    offer=client.post('/lifecycle/offers',headers=auth('a-hr'),json={'employee_id':'a-employee','candidate_id':candidate.json()['id'],'title':'Engineer offer','salary_amount':22000,'status':'Accepted'})
    assert offer.status_code==200,offer.content
    goal=client.post('/performance/goals',headers=auth('a-hr'),json={'employee_id':'a-employee','title':'Complete onboarding','start_date':'2026-09-01','end_date':'2026-12-31','target_value':100})
    assert goal.status_code==200,goal.content
    assert client.put('/performance/goals/'+goal.json()['id'],headers=auth('a-hr'),json={'achieved_value':100,'status':'Completed'}).status_code==200
    ticket=client.post('/engagement/tickets',headers=auth('a-employee'),json={'employee_id':'a-employee','subject':'New laptop access','description':'Set up account'})
    assert ticket.status_code==200,ticket.content
    assert client.put('/engagement/tickets/'+ticket.json()['id']+'/status',headers=auth('a-hr'),json={'status':'Resolved'}).status_code==200
    document=client.post('/employees/a-employee/documents',headers=auth('a-employee'),data={'document_type':'Investment proof','file':SimpleUploadedFile('investment.txt',b'Test-only investment evidence',content_type='text/plain')})
    assert document.status_code==200,document.content
    proof=document.json()['id']
    declaration=client.post('/financials/tax-declarations',headers=auth('a-employee'),json={'financial_year':2026,'category':'Employee investment','declared_amount':10000,'proof_document_id':proof})
    assert declaration.status_code==200,declaration.content
    identifier=declaration.json()['id']
    assert client.post(f'/financials/tax-declarations/{identifier}/submit',headers=auth('a-employee')).status_code==200
    assert client.post(f'/financials/tax-declarations/{identifier}/review',headers=auth('a-manager'),json={'approve':True,'note':'Manager cannot approve'}).status_code==403
    assert client.post(f'/financials/tax-declarations/{identifier}/review',headers=auth('b-hr'),json={'approve':True,'note':'Foreign reviewer'}).status_code==404
    reviewed=client.post(f'/financials/tax-declarations/{identifier}/review',headers=auth('a-hr'),json={'approve':True,'approved_amount':9000,'note':'Proof verified'})
    assert reviewed.status_code==200,reviewed.content
    assert reviewed.json()['approved_amount']==9000
    assert client.post(f'/financials/tax-declarations/{identifier}/review',headers=auth('a-hr'),json={'approve':False,'note':'Duplicate review'}).status_code==409
    assert client.get('/financials/tax-declarations',headers=auth('b-hr')).json()==[]
    assert client.get(f'/employees/documents/{proof}/download',headers=auth('b-employee')).status_code==404
    file=client.get(f'/employees/documents/{proof}/download',headers=auth('a-employee'))
    assert file.status_code==200 and b''.join(file.streaming_content)==b'Test-only investment evidence'
    own=client.get('/dashboard/reports/core',headers=auth('a-hr'))
    other=client.get('/dashboard/reports/core',headers=auth('b-hr'))
    assert own.status_code==other.status_code==200
    assert own.json()['counts']['candidates']==1 and other.json()['counts']['candidates']==0
    assert own.json()['counts']['tax_declarations']==1 and other.json()['counts']['tax_declarations']==0
    assert client.get('/dashboard/reports/core',headers=auth('a-manager')).status_code==403
    export=client.get('/dashboard/reports/core.csv',headers=auth('b-hr'))
    assert export.status_code==200 and b'candidates,0' in export.content


def test_recovery_expiry_resend_and_disabled_company(api,smtp):
    client,db=api
    for _ in range(2):
        assert client.post('/auth/forgot-password',json={'email':'a-employee@example.test'}).status_code==200
        db.info.pop('actor',None);assert deliver_pending(db)['sent']==1
    first=token_from(smtp.messages[0]);second=token_from(smtp.messages[1])
    assert client.post('/auth/reset-password',json={'token':first,'password':'ReplacementPass123!'}).status_code==400
    db.info.pop('actor',None)
    from hashlib import sha256
    row=db.scalar(select(AccountToken).where(AccountToken.token_hash==sha256(second.encode()).hexdigest()))
    row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert client.post('/auth/reset-password',json={'token':second,'password':'ReplacementPass123!'}).status_code==400
    assert client.patch('/admin/tenants/a',headers=auth('platform'),json={'is_active':False}).status_code==200
    assert client.post('/auth/forgot-password',json={'email':'a-employee@example.test'}).status_code==200
    db.info.pop('actor',None);assert deliver_pending(db)['processed']==0


def test_release_migration_is_repeatable_and_preserves_existing_rows(tmp_path):
    from sqlalchemy import create_engine,inspect,text
    from app.db.models import Base
    from app.db.release_migration import upgrade_release
    engine=create_engine('sqlite:///'+str(tmp_path/'upgrade.sqlite'))
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.execute(text("INSERT INTO users (id,full_name,email,role,password_hash,is_active,created_at,auth_version,email_verified) VALUES ('legacy','Legacy Admin','legacy@example.test','Super Admin','test-only',true,CURRENT_TIMESTAMP,0,false)"))
        conn.exec_driver_sql('ALTER TABLE users DROP COLUMN auth_version')
        conn.exec_driver_sql('ALTER TABLE users DROP COLUMN email_verified')
        conn.exec_driver_sql('ALTER TABLE leave_requests DROP COLUMN deducted_days')
        upgrade_release(conn);upgrade_release(conn)
        assert {'auth_version','email_verified'}<={item['name'] for item in inspect(conn).get_columns('users')}
        assert conn.scalar(text("SELECT auth_version FROM users WHERE id='legacy'"))==0
        assert 'tax_declarations' in inspect(conn).get_table_names()
    engine.dispose()


def test_jwt_rejects_missing_expiry_unsigned_and_forged_tokens(api):
    import jwt
    client,db=api
    valid={'sub':'a-employee@example.test','exp':datetime.now(timezone.utc)+timedelta(minutes=10)}
    tokens=[jwt.encode({'sub':valid['sub']},settings.secret_key,algorithm='HS256'),jwt.encode(valid,'',algorithm='none'),jwt.encode(valid,'different-test-signing-key-at-least-32-characters',algorithm='HS256')]
    for token in tokens:assert client.get('/auth/me',headers={'Authorization':'Bearer '+token}).status_code==401


def test_mail_retry_and_email_notification_delivery_state(api,smtp,monkeypatch):
    from app.schemas.notifications import NotificationCreate
    from app.services.notification_service import NotificationService
    import app.services.mail_service as service
    client,db=api
    notification=NotificationService.send_notification(db,NotificationCreate(recipient_id='a-employee',event_type='release_test',channel='email',subject='Release notification',message='Test delivery'))
    assert notification.status=='Pending'
    original_smtp=service.smtplib.SMTP
    def fail(*args,**kwargs):raise OSError('Test-only temporary delivery failure')
    monkeypatch.setattr(service.smtplib,'SMTP',fail)
    result=deliver_pending(db)
    assert result=={'processed':1,'sent':0,'failed':0}
    row=db.scalar(select(MailMessage));assert row.status=='retry' and row.attempts==1
    assert deliver_pending(db)['processed']==0
    row.available_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    monkeypatch.setattr(service.smtplib,'SMTP',original_smtp)
    assert deliver_pending(db)['sent']==1
    db.refresh(notification);assert notification.status=='Sent'
    assert smtp.messages[-1]['subject']=='Release notification'


def test_separate_imported_employee_identity_across_modules(api):
    from app.core.security import create_access_token,hash_password
    client,db=api
    db.add(User(id='import-login',tenant_id='a',email='imported@example.test',full_name='Imported user',role='Employee',password_hash=hash_password('TestPassword123!')))
    db.add(Employee(id='import-profile',tenant_id='a',email='imported@example.test',full_name='Imported employee'))
    db.commit()
    headers={'Authorization':'Bearer '+create_access_token({'sub':'imported@example.test'})}
    ticket=client.post('/engagement/tickets',headers=headers,json={'employee_id':'import-profile','subject':'Imported employee support','description':'Different user and employee IDs'})
    assert ticket.status_code==200,ticket.content
    goal=client.post('/performance/goals',headers=auth('a-hr'),json={'employee_id':'import-profile','title':'Imported user goal','start_date':'2026-01-01','end_date':'2026-12-31'})
    assert goal.status_code==200,goal.content
    assert client.get('/performance/goals/'+goal.json()['id'],headers=headers).status_code==200
    inbox=client.get('/notifications/user/me/notifications',headers=headers)
    assert inbox.status_code==200 and any(item['event_type']=='ticket_created' for item in inbox.json())
