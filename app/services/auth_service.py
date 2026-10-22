from datetime import datetime, timezone
from pathlib import Path

from app.http import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.models import User, Employee, Tenant, TenantFeature
from app.schemas.auth import LoginResponse, UserPublic


SEED_USERS = [
    ('Aditi Sharma', 'admin@hrms.com', 'Admin'),
    ('Riya Nair', 'hr@hrms.com', 'HR'),
    ('Arjun Mehta', 'manager@hrms.com', 'Manager'),
    ('Neha Kapoor', 'employee@hrms.com', 'Employee'),
    ('Vikram Rao', 'ceo@hrms.com', 'CEO'),
]

AVATAR_DIR = Path(__file__).resolve().parents[2] / 'uploads' / 'avatars'
MAX_AVATAR_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_AVATAR_CONTENT_TYPES = {'image/png', 'image/jpeg', 'image/webp'}


def _ensure_avatar_dir() -> None:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)


def _find_avatar_file(user_id: str) -> Path | None:
    _ensure_avatar_dir()
    for file in AVATAR_DIR.glob(f'{user_id}.*'):
        if file.is_file():
            return file
    return None


def get_avatar_url(user_id: str) -> str | None:
    avatar_file = _find_avatar_file(user_id)
    if avatar_file is None:
        return None
    return f'/uploads/avatars/{avatar_file.name}'


def save_user_avatar(user_id: str, filename: str, content_type: str | None, content: bytes) -> str:
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Avatar file is empty')

    if len(content) > MAX_AVATAR_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail='Avatar must be <= 5MB')

    if content_type and content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Unsupported image type. Use PNG, JPEG or WEBP')

    ext = 'jpg'
    lower_name = (filename or '').lower()
    if lower_name.endswith('.png'):
        ext = 'png'
    elif lower_name.endswith('.webp'):
        ext = 'webp'
    elif lower_name.endswith('.jpeg') or lower_name.endswith('.jpg'):
        ext = 'jpg'
    elif content_type == 'image/png':
        ext = 'png'
    elif content_type == 'image/webp':
        ext = 'webp'

    _ensure_avatar_dir()

    # Keep only one avatar per user.
    existing = _find_avatar_file(user_id)
    if existing is not None:
        existing.unlink(missing_ok=True)

    target = AVATAR_DIR / f'{user_id}.{ext}'
    target.write_bytes(content)
    return f'/uploads/avatars/{target.name}'


def delete_user_avatar(user_id: str) -> bool:
    existing = _find_avatar_file(user_id)
    if existing is None:
        return False
    existing.unlink(missing_ok=True)
    return True


def resolve_employee_id(user: User, db: Session) -> str | None:
    """Resolve employee record id for a user (shared id or email link)."""
    emp = db.scalar(select(Employee).where(Employee.id == user.id))
    if emp:
        return emp.id
    emp = db.scalar(select(Employee).where(Employee.email == user.email.lower()))
    return emp.id if emp else None


def to_public_user(user: User, db: Session | None = None) -> UserPublic:
    """Return public user payload including optional linked employee_id (if exists)."""
    emp_id: str | None = None
    if db is not None:
        try:
            emp_id = resolve_employee_id(user, db)
        except Exception:
            emp_id = None

    from datetime import date
    from app.db.models import Subscription
    tenant_id = user.tenant_id
    tenant_obj = None
    entitlements = []
    if db is not None and tenant_id:
        tenant = db.scalar(select(Tenant).where(Tenant.id==tenant_id))
        if tenant:
            tenant_obj={'id':tenant.id,'name':tenant.name,'domain':tenant.domain,'is_active':tenant.is_active,'timezone':tenant.timezone}
            active = db.scalar(select(Subscription.id).where(Subscription.tenant_id==tenant_id,Subscription.status=='active',Subscription.starts_at<=date.today(),(Subscription.ends_at.is_(None)|(Subscription.ends_at>=date.today()))))
            if active:
                entitlements=list(db.scalars(select(TenantFeature.feature_key).where(TenantFeature.tenant_id==tenant_id,TenantFeature.enabled.is_(True))))

    return UserPublic(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        employee_id=emp_id,
        avatar_url=get_avatar_url(user.id),
        tenant_id=tenant_id,
        tenant=tenant_obj,
        entitlements=entitlements,
    )


def authenticate_user(*, email: str, password: str, db: Session, role: str | None = None) -> User:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid email or password')

    if role and user.role.lower() != role.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Selected role does not match this account')

    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid email or password')

    return user


def create_login_response(user: User, db: Session | None = None) -> LoginResponse:
    from app.core.ownership import bind_actor
    bind_actor(db, user)
    access_token, expires_at = create_access_token(subject=user.email, user_id=user.id, role=user.role)
    expires_in = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    return LoginResponse(access_token=access_token, expires_in=max(expires_in, 1), user=to_public_user(user, db=db))


def get_user_from_token(token: str, db: Session) -> User:
    db.info.pop('actor', None)
    payload = decode_token_payload(token)
    subject = payload.get('sub')
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token missing subject')

    user = db.scalar(select(User).where(User.email == str(subject).lower()))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='User not found')

    from app.core.ownership import bind_actor
    bind_actor(db, user)
    return user


def decode_token_payload(token: str) -> dict:
    try:
        from app.core.security import decode_access_token

        return decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def update_user_profile(user: User, full_name: str, *, db: Session) -> User:
    user.full_name = full_name.strip()
    db.commit()
    db.refresh(user)
    return user


def change_password(user: User, old_password: str, new_password: str, *, db: Session) -> None:
    from app.core.security import hash_password

    if not verify_password(old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Old password is incorrect')

    if old_password == new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='New password must be different from old password')

    user.password_hash = hash_password(new_password)
    db.commit()

def register_tenant(payload, db: Session) -> User:
    from app.services.company_service import provision_company
    tenant, user = provision_company(payload.company_name, None, payload.admin_name, payload.admin_email, payload.password, db)
    return user
