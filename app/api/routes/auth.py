from app.http import Router, Depends, File, HTTPException, UploadFile, status, Request
from app.http import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    AvatarDeleteResponse,
    AvatarUploadResponse,
    PasswordChangeResponse,
    ProfileUpdateRequest,
    UserPublic,
    PermissionsResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.services.auth_service import (
    authenticate_user,
    change_password,
    create_login_response,
    delete_user_avatar,
    get_user_from_token,
    save_user_avatar,
    to_public_user,
    update_user_profile,
)
from app.core.rbac import get_permissions_for_role

router = Router()
security = HTTPBearer(auto_error=False)


@router.post('/login', response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    from app.services.account_service import throttle
    from app.core.config import settings
    throttle(db,'login-ip:'+request.META.get('REMOTE_ADDR','unknown'),50,settings.login_window_minutes)
    throttle(db,'login-email:'+payload.email.strip().lower(),settings.login_attempt_limit,settings.login_window_minutes)
    user = authenticate_user(email=payload.email, password=payload.password, role=payload.role, db=db)
    from sqlalchemy import delete
    from hashlib import sha256
    from app.db.models import AuthRateLimit
    db.execute(delete(AuthRateLimit.__table__).where(AuthRateLimit.id==sha256(('login-email:'+payload.email.strip().lower()).encode()).hexdigest()))
    return create_login_response(user, db=db)


@router.post('/register', response_model=RegisterResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    from app.services.auth_service import register_tenant
    user = register_tenant(payload, db=db)
    return RegisterResponse(message='Registration successful', user=to_public_user(user, db=db))


@router.get('/me', response_model=UserPublic)
def me(credentials: HTTPAuthorizationCredentials | None = Depends(security), db: Session = Depends(get_db)) -> UserPublic:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    user = get_user_from_token(credentials.credentials, db=db)
    return to_public_user(user, db=db)


@router.patch('/me', response_model=UserPublic)
def update_me(
    payload: ProfileUpdateRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> UserPublic:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    user = get_user_from_token(credentials.credentials, db=db)
    updated_user = update_user_profile(user, payload.full_name, db=db)
    return to_public_user(updated_user)


@router.post('/me/avatar', response_model=AvatarUploadResponse)
def upload_me_avatar(
    avatar: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> AvatarUploadResponse:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    user = get_user_from_token(credentials.credentials, db=db)
    content = avatar.file.read()
    avatar_url = save_user_avatar(user.id, avatar.filename or '', avatar.content_type, content)
    return AvatarUploadResponse(avatar_url=avatar_url)


@router.delete('/me/avatar', response_model=AvatarDeleteResponse)
def delete_me_avatar(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> AvatarDeleteResponse:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    user = get_user_from_token(credentials.credentials, db=db)
    delete_user_avatar(user.id)
    return AvatarDeleteResponse(message='Avatar removed successfully')


@router.post('/change-password', response_model=PasswordChangeResponse)
def change_pwd(
    payload: ChangePasswordRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> PasswordChangeResponse:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    user = get_user_from_token(credentials.credentials, db=db)
    change_password(user, payload.old_password, payload.new_password, db=db)
    return PasswordChangeResponse(message='Password changed successfully')


@router.get('/me/permissions', response_model=PermissionsResponse)
def get_me_permissions(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> PermissionsResponse:
    """Get current user's role and permissions."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    user = get_user_from_token(credentials.credentials, db=db)
    permissions = list(get_permissions_for_role(user.role))
    return PermissionsResponse(role=user.role, permissions=permissions)


from pydantic import BaseModel, Field
from app.core.rbac import get_current_user, require_permissions
from app.services import account_service
from sqlalchemy import select
from app.db.models import AuthSession
from datetime import datetime, timezone

class RecoveryRequest(BaseModel):
    email: str = Field(min_length=3,max_length=255)
class CompleteAccount(BaseModel):
    token: str = Field(min_length=20,max_length=200)
    password: str = Field(min_length=8,max_length=128)
class InvitationRequest(BaseModel):
    employee_id: str

@router.post('/forgot-password')
def forgot_password(payload: RecoveryRequest, request: Request, db: Session = Depends(get_db)):
    account_service.throttle(db,'reset-ip:'+request.META.get('REMOTE_ADDR','unknown'),20)
    account_service.throttle(db,'reset-email:'+payload.email.strip().lower(),3)
    return account_service.request_reset(payload.email,db)

@router.post('/reset-password')
def reset_password(payload: CompleteAccount, request: Request, db: Session = Depends(get_db)):
    account_service.throttle(db,'complete-ip:'+request.META.get('REMOTE_ADDR','unknown'),20)
    return account_service.complete_link(payload.token,payload.password,'reset',db)

@router.post('/accept-invitation')
def accept_invitation(payload: CompleteAccount, request: Request, db: Session = Depends(get_db)):
    account_service.throttle(db,'invite-complete-ip:'+request.META.get('REMOTE_ADDR','unknown'),20)
    return account_service.complete_link(payload.token,payload.password,'invite',db)

@router.post('/invitations')
def send_invitation(payload: InvitationRequest, user=Depends(require_permissions('create_employee')), db: Session = Depends(get_db)):
    account_service.throttle(db,'invite-actor:'+user.id,20)
    return account_service.invite(payload.employee_id,user,db)

@router.get('/sessions')
def list_sessions(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows=db.scalars(select(AuthSession).where(AuthSession.user_id==user.id,AuthSession.revoked_at.is_(None),AuthSession.expires_at>datetime.now(timezone.utc)).order_by(AuthSession.created_at.desc()))
    return [{'id':row.id,'created_at':row.created_at.isoformat(),'expires_at':row.expires_at.isoformat()} for row in rows]

@router.post('/sessions/{session_id}/revoke')
def revoke_session(session_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row=db.scalar(select(AuthSession).where(AuthSession.id==session_id,AuthSession.user_id==user.id).with_for_update(of=AuthSession))
    if not row: raise HTTPException(404,'Session not found')
    row.revoked_at=datetime.now(timezone.utc);db.commit()
    return {'message':'Session revoked'}

@router.post('/sessions/revoke-all')
def revoke_all_sessions(user=Depends(get_current_user), db: Session = Depends(get_db)):
    account_service.revoke_all(user,db);db.commit()
    return {'message':'All sessions revoked. Please sign in again.'}

@router.post('/logout')
def logout(credentials: HTTPAuthorizationCredentials = Depends(security), user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.auth_service import decode_token_payload
    payload=decode_token_payload(credentials.credentials)
    if payload.get('sid'):
        row=db.scalar(select(AuthSession).where(AuthSession.id==payload['sid'],AuthSession.user_id==user.id))
        if row: row.revoked_at=datetime.now(timezone.utc)
    else:
        account_service.revoke_all(user,db)
    db.commit()
    return {'message':'Signed out'}
