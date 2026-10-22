"""Explicit company fixtures for authenticated API integration tests."""
from datetime import date, timedelta
from app.db.models import Tenant, Plan, Subscription, TenantFeature, TENANT_MODELS

def company_fixture(db, tenant_id='test-company'):
    for row in db.new:
        if isinstance(row,tuple(TENANT_MODELS)) and not row.tenant_id:
            row.tenant_id=tenant_id
    if db.get(Tenant, tenant_id) is None:
        db.add(Tenant(id=tenant_id, name='Test Company')); db.flush()
    plan = db.get(Plan, 'fixture-plan')
    if plan is None:
        plan=Plan(id='fixture-plan',name='Fixture Plan',price_cents=0); db.add(plan); db.flush()
    db.add(Subscription(tenant_id=tenant_id,plan_id=plan.id,starts_at=date.today()-timedelta(days=1),ends_at=date.today()+timedelta(days=30),status='active'))
    for feature in ['attendance_module','leave_module','payroll_module','document_module','performance_module','helpdesk_module']:
        db.add(TenantFeature(tenant_id=tenant_id,feature_key=feature,enabled=True))
    for row in db.new:
        if isinstance(row,tuple(TENANT_MODELS)) and not row.tenant_id:
            row.tenant_id=tenant_id
    for model in TENANT_MODELS:
        for row in db.query(model).filter(model.tenant_id.is_(None)):
            row.tenant_id=tenant_id
    db.commit()
    return tenant_id
