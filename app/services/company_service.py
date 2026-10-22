"""Atomic company provisioning shared by admin creation and public registration."""
from uuid import uuid4
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.db.models import Tenant, User, Employee
from app.core.security import hash_password
from app.http import HTTPException

def provision_company(name, domain, admin_name, email, password, db):
    email = email.strip().lower()
    domain = (domain or '').strip().lower() or None
    if not name.strip() or not admin_name.strip() or '@' not in email or len(password) < 8:
        raise HTTPException(422, 'Provide organization name, administrator name, valid email and an 8-character password')
    if db.scalar(select(User.id).where(func.lower(User.email) == email)) or db.scalar(select(Employee.id).where(func.lower(Employee.email) == email)):
        raise HTTPException(409, 'Administrator email is already registered')
    if domain and db.scalar(select(Tenant.id).where(func.lower(Tenant.domain) == domain)):
        raise HTTPException(409, 'An organization with this domain already exists')
    tenant = Tenant(id=str(uuid4()), name=name.strip(), domain=domain)
    user_id = str(uuid4())
    user = User(id=user_id, tenant_id=tenant.id, full_name=admin_name.strip(), email=email, password_hash=hash_password(password), role='CEO')
    try:
        db.add(tenant); db.flush()
        db.add(user)
        db.add(Employee(id=user_id, tenant_id=tenant.id, full_name=admin_name.strip(), email=email))
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if getattr(error.orig, 'sqlstate', None) == '23505' or 'UNIQUE constraint failed' in str(error.orig):
            raise HTTPException(409, 'Administrator email or organization domain is already registered') from error
        raise
    return tenant, user
