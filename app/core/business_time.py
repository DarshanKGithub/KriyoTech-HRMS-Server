"""Business dates shared by attendance, leave, payroll and scheduled jobs."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
from app.db.models import Tenant

def tenant_zone(db, tenant_id):
    tenant = db.get(Tenant, tenant_id) if tenant_id else None
    return ZoneInfo(tenant.timezone if tenant else 'Asia/Kolkata')

def local_time(value, db, tenant_id):
    zone = tenant_zone(db, tenant_id)
    return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)

def business_today(db, tenant_id):
    return datetime.now(timezone.utc).astimezone(tenant_zone(db, tenant_id)).date()

def working_days(db, tenant_id):
    tenant = db.get(Tenant, tenant_id) if tenant_id else None
    return set(json.loads(tenant.working_days_json)) if tenant else {0,1,2,3,4}
