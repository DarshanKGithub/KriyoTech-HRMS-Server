from app.http import Router, Depends, File, HTTPException, UploadFile, status
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
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = authenticate_user(email=payload.email, password=payload.password, role=payload.role, db=db)
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
