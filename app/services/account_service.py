"""Single-use account links, persistent throttling and session revocation."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import secrets
from urllib.parse import urlencode,urlsplit
from sqlalchemy import select,update
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User,Employee,Tenant,AccountToken,AuthSession,AuthRateLimit,AuditLog
from app.http import HTTPException
from app.services.mail_service import require_mail,queue_mail


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def throttle(db, key, limit, minutes=15):
    now=datetime.now(timezone.utc)
    identifier=sha256(key.encode()).hexdigest()
    table=AuthRateLimit.__table__
    if db.bind.dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt=insert(table).values(id=identifier,window_start=now,attempts=1)
    from sqlalchemy import case
    expired=table.c.window_start <= now-timedelta(minutes=minutes)
    stmt=stmt.on_conflict_do_update(index_elements=[table.c.id],set_={'attempts':case((expired,1),else_=table.c.attempts+1),'window_start':case((expired,now),else_=table.c.window_start)}).returning(table.c.attempts)
    attempts=db.execute(stmt).scalar_one()
    db.commit()
    if attempts>limit:
        raise HTTPException(429,'Too many attempts. Please try again later.')


def revoke_all(user, db):
    user.auth_version=(user.auth_version or 0)+1
    db.execute(update(AuthSession).where(AuthSession.user_id==user.id,AuthSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))


def issue_link(user,purpose,db):
    require_mail()
    parts=urlsplit(settings.public_app_url)
    if parts.scheme not in {'https','http'} or not parts.netloc or (parts.scheme=='http' and parts.hostname not in {'localhost','127.0.0.1'}):
        raise HTTPException(503,'A secure public application URL is required')
    now=datetime.now(timezone.utc)
    db.execute(update(AccountToken).where(AccountToken.user_id==user.id,AccountToken.purpose==purpose,AccountToken.used_at.is_(None)).values(used_at=now))
    raw=secrets.token_urlsafe(32)
    duration=settings.invitation_token_minutes if purpose=='invite' else settings.account_token_minutes
    db.add(AccountToken(tenant_id=user.tenant_id,user_id=user.id,token_hash=sha256(raw.encode()).hexdigest(),purpose=purpose,expires_at=now+timedelta(minutes=duration),auth_version=user.auth_version or 0))
    path='/accept-invitation' if purpose=='invite' else '/reset-password'
    link=settings.public_app_url.rstrip('/')+path+'#'+urlencode({'token':raw})
    subject='Your KriyoHR invitation' if purpose=='invite' else 'Reset your KriyoHR password'
    queue_mail(db,user.email,subject,f'{subject}\n\nOpen this link to choose your password:\n{link}\n\nThis link expires in {duration} minutes and can be used only once. If you did not request it, you can ignore this email.',user.tenant_id)
    db.add(AuditLog(tenant_id=user.tenant_id,actor_id=user.id,action='account_link_requested',object_type='user',object_id=user.id,data=purpose))


def request_reset(email,db):
    require_mail()
    user=db.scalar(select(User).where(User.email==email.strip().lower()))
    if user and user.is_active:
        tenant=db.get(Tenant,user.tenant_id) if user.tenant_id else None
        employee=db.scalar(select(Employee).where(Employee.tenant_id==user.tenant_id,Employee.email==user.email))
        if (user.role=='Super Admin' or tenant and tenant.is_active) and (not employee or employee.is_active):
            issue_link(user,'reset',db)
    db.commit()
    return {'message':'If an eligible account exists, a password reset email has been queued.'}


def complete_link(raw,password,purpose,db):
    now=datetime.now(timezone.utc)
    token=db.scalar(select(AccountToken).where(AccountToken.token_hash==sha256(raw.encode()).hexdigest(),AccountToken.purpose==purpose).with_for_update(of=AccountToken))
    if not token or token.used_at or utc(token.expires_at)<=now:
        raise HTTPException(400,'This link is invalid or expired. Request a new one.')
    user=db.scalar(select(User).where(User.id==token.user_id).with_for_update(of=User))
    tenant=db.get(Tenant,user.tenant_id) if user.tenant_id else None
    employee=db.scalar(select(Employee).where(Employee.tenant_id==user.tenant_id,Employee.email==user.email))
    if (token.auth_version != (user.auth_version or 0) or purpose=='reset' and not user.is_active or user.role!='Super Admin' and (not tenant or not tenant.is_active) or employee and not employee.is_active):
        raise HTTPException(400,'This link is invalid or expired. Contact your administrator.')
    user.password_hash=hash_password(password)
    user.email_verified=True
    if purpose=='invite': user.is_active=True
    token.used_at=now
    revoke_all(user,db)
    db.add(AuditLog(tenant_id=user.tenant_id,actor_id=user.id,action='account_'+purpose+'_completed',object_type='user',object_id=user.id,data='Sessions revoked'))
    db.commit()
    return {'message':'Password saved. Please sign in with your new password.'}


def invite(employee_id,actor,db):
    require_mail()
    employee=db.get(Employee,employee_id)
    if not employee or not employee.is_active:
        raise HTTPException(404,'Active employee not found')
    user=db.scalar(select(User).where(User.email==employee.email.lower()))
    if user and (user.tenant_id!=actor.tenant_id or user.role=='Super Admin'):
        raise HTTPException(409,'This employee cannot be invited')
    if user and user.email_verified:
        raise HTTPException(409,'This account is already verified. Use password recovery instead.')
    if not user:
        existing=db.execute(select(User.__table__.c.id).where(User.__table__.c.email==employee.email.lower())).first()
        if existing: raise HTTPException(409,'This employee cannot be invited')
        user=User(id=employee.id,tenant_id=actor.tenant_id,full_name=employee.full_name,email=employee.email.lower(),role='Employee',password_hash=hash_password(secrets.token_urlsafe(32)),is_active=False)
        db.add(user);db.flush()
    issue_link(user,'invite',db)
    db.commit()
    return {'message':'Invitation email queued. The employee must open the link to verify their address and choose a password.'}
