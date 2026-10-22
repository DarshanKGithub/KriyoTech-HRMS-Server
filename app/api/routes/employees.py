from app.http import Router, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions
from app.db.database import get_db
from app.db.models import User
from app.schemas.employee import (
    EmployeeCreateWithAccount,
    EmployeePublic,
    EmployeePublicWithAccount,
    EmployeeUpdate,
    PaginatedEmployees,
)
from app.schemas.auth import RoleUpdateRequest
from app.services.employee_service import search_employees, create_employee, get_employee, update_employee, delete_employee
from app.services.employee_service import get_manager_chain
from app.services.audit_service import create_audit_log

router = Router()


def _require_employee_tenant(user):
    if user.role != 'Super Admin' and not user.tenant_id:
        raise HTTPException(403, 'An organization assignment is required')
    return user.tenant_id


@router.get('/', response_model=PaginatedEmployees)
def employees(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), q: str | None = None, department_id: str | None = None,
              designation_id: str | None = None, sort_by: str = 'full_name', sort_dir: str = 'asc', is_active: bool | None = None,
              db: Session = Depends(get_db), user: User = Depends(require_permissions('view_employee'))):
    is_super_admin = user.role == 'Super Admin'
    _require_employee_tenant(user)
    from app.services.auth_service import resolve_employee_id
    manager_id = resolve_employee_id(user, db) if user.role == 'Manager' else None
    if user.role == 'Manager' and not manager_id:
        raise HTTPException(403, 'A linked employee record is required')
    items, total = search_employees(db=db, page=page, size=size, q=q, department_id=department_id, designation_id=designation_id, tenant_id=user.tenant_id, is_super_admin=is_super_admin, sort_by=sort_by, sort_dir=sort_dir, is_active=is_active, manager_id=manager_id)
    return PaginatedEmployees(
        items=[EmployeePublic(
            id=e.id,
            full_name=e.full_name,
            email=e.email,
            department_id=e.department_id,
            designation_id=e.designation_id,
            manager_id=e.manager_id,
            is_active=e.is_active,
        ) for e in items],
        total=total,
        page=page,
        size=size,
    )


def _to_employee_public(employee) -> EmployeePublic:
    return EmployeePublic.model_validate(employee, from_attributes=True)


@router.post('/', response_model=EmployeePublicWithAccount)
def create(
    payload: EmployeeCreateWithAccount,
    user: User = Depends(require_permissions('create_employee')),
    db: Session = Depends(get_db),
):
    e = create_employee(payload=payload, db=db, actor_id=user.id, tenant_id=_require_employee_tenant(user))
    linked_user = db.scalar(select(User).where(User.id == e.id))
    public = _to_employee_public(e)
    return EmployeePublicWithAccount(
        **public.model_dump(),
        role=linked_user.role if linked_user else payload.role,
        login_created=linked_user is not None,
    )


@router.get('/{employee_id}', response_model=EmployeePublic)
def get_one(employee_id: str, db: Session = Depends(get_db), user: User = Depends(require_permissions('view_employee'))):
    e = get_employee(employee_id, db=db, tenant_id=_require_employee_tenant(user))
    from app.services.auth_service import resolve_employee_id
    from app.core.rbac import has_permission
    own_id = resolve_employee_id(user, db)
    if user.role == 'Manager' and e.id != own_id and e.manager_id != own_id:
        raise HTTPException(403, 'Only direct-report profiles are available')
    public = EmployeePublic.model_validate(e, from_attributes=True)
    if e.id != own_id and not has_permission(user.role, 'process_payroll'):
        for field in ('bank_account_number', 'bank_ifsc_code', 'pan_number', 'aadhar_number'):
            setattr(public, field, None)
    return public


@router.patch('/{employee_id}', response_model=EmployeePublic)
def patch(
    employee_id: str,
    payload: EmployeeUpdate,
    user: User = Depends(require_permissions('edit_employee')),
    db: Session = Depends(get_db),
):

    e = update_employee(employee_id, payload=payload, db=db, actor_id=user.id, tenant_id=_require_employee_tenant(user))
    return EmployeePublic(
        id=e.id,
        full_name=e.full_name,
        email=e.email,
        department_id=e.department_id,
        designation_id=e.designation_id,
        manager_id=e.manager_id,
        is_active=e.is_active,
    )


@router.delete('/{employee_id}')
def remove(employee_id: str, user: User = Depends(require_permissions('delete_employee')), db: Session = Depends(get_db)):

    delete_employee(employee_id, db=db, actor_id=user.id, tenant_id=_require_employee_tenant(user))
    return {'detail': 'deleted'}


@router.patch('/{employee_id}/role', response_model=EmployeePublicWithAccount)
def update_role(
    employee_id: str,
    payload: RoleUpdateRequest,
    user: User = Depends(require_permissions('manage_roles')),
    db: Session = Depends(get_db),
):
    # Ensure employee is in same tenant
    e = get_employee(employee_id, db=db, tenant_id=user.tenant_id)
    
    linked_user = db.scalar(select(User).where(User.id == e.id))
    if not linked_user:
        from app.http import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee does not have a user account")

    allowed_roles = {'Worker', 'Employee', 'Manager', 'HR', 'Admin', 'CEO'}
    new_role = payload.role.strip()
    if new_role not in allowed_roles:
        from app.http import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid role')

    if user.id == linked_user.id:
        from app.http import HTTPException, status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot change your own role')

    old_role = linked_user.role
    if old_role != new_role:
        linked_user.role = new_role
        create_audit_log(
            db,
            actor_id=user.id,
            action='ROLE_UPDATED',
            object_type='User',
            object_id=linked_user.id,
            data={
                'old_role': old_role,
                'new_role': new_role,
            },
        )
        db.commit()
        db.refresh(linked_user)

    public = _to_employee_public(e)
    return EmployeePublicWithAccount(
        **public.model_dump(),
        role=linked_user.role,
        login_created=True,
    )


@router.get('/{employee_id}/manager-chain')
def manager_chain(employee_id: str, db: Session = Depends(get_db), user: User = Depends(require_permissions('view_employee'))):
    chain = get_manager_chain(employee_id=employee_id, db=db, tenant_id=user.tenant_id)
    return chain

from app.http import UploadFile, File, Form, FileResponse
from app.db.models import EmployeeDocument
from app.schemas.document import EmployeeDocumentPublic
from app.core.rbac import get_current_user
from app.services.document_service import save_employee_document, list_employee_documents, downloadable_document


@router.post('/{employee_id}/documents', response_model=EmployeeDocumentPublic)
def upload_document(employee_id: str, document_type: str = Form(...), file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_employee_document(employee_id, document_type, file, user, db)


@router.get('/{employee_id}/documents', response_model=list[EmployeeDocumentPublic])
def list_documents(employee_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_employee_documents(employee_id, user, db)


@router.get('/documents/{doc_id}/download')
def download_document(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document, path = downloadable_document(doc_id, user, db)
    return FileResponse(path, filename=document.file_name)
