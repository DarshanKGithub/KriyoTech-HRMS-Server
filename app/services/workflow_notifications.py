"""Transactional workflow notifications with explicit recipient ownership."""
import json
from sqlalchemy import select
from app.db.models import Employee,User,Notification,NotificationPreference

def notify_employee(db,employee_id,event,message,roles=()):
    employee=db.execute(select(Employee.__table__.c.email,Employee.__table__.c.tenant_id).where(Employee.__table__.c.id==employee_id)).first()
    if not employee or not employee.tenant_id: return
    users=User.__table__
    clause=users.c.role.in_(roles) if roles else users.c.email==employee.email
    recipients=db.execute(select(users.c.id).where(users.c.tenant_id==employee.tenant_id,users.c.is_active.is_(True),clause)).scalars()
    for identifier in recipients:
        preference=db.execute(select(NotificationPreference.__table__.c.in_app_enabled).where(NotificationPreference.__table__.c.user_id==identifier,NotificationPreference.__table__.c.tenant_id==employee.tenant_id)).scalar()
        if preference is False: continue
        db.execute(Notification.__table__.insert().values(tenant_id=employee.tenant_id,recipient_id=identifier,event_type=event,channel='in_app',subject=event.replace('_',' ').title(),message=message,status='Sent',data=json.dumps({'employee_id':employee_id})))
