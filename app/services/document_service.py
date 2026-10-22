"""Ownership and tenant checks shared by both document API entry points."""
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from app.core.rbac import has_permission
from app.db.models import Employee, EmployeeDocument, User
from app.http import HTTPException
from app.services.auth_service import resolve_employee_id

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / 'uploads'
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.doc', '.docx', '.txt'}


def employee_document_access(employee_id, user: User, db, *, write=False):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(404, 'Employee not found')
    if user.role == 'Super Admin':
        return employee
    own_id = resolve_employee_id(user, db)
    own = employee_id == own_id
    if user.tenant_id and employee.tenant_id != user.tenant_id or not user.tenant_id and not own:
        raise HTTPException(404, 'Employee not found')
    if own:
        return employee
    if write and not has_permission(user.role, 'edit_employee'):
        raise HTTPException(403, 'Cannot upload documents for this employee')
    if not write and not has_permission(user.role, 'view_employee'):
        raise HTTPException(403, 'Cannot view documents for this employee')
    if user.role == 'Manager' and employee.manager_id != own_id:
        raise HTTPException(403, 'Only direct-report documents are available')
    return employee


def list_employee_documents(employee_id, user, db):
    employee_document_access(employee_id, user, db)
    return db.scalars(select(EmployeeDocument).where(EmployeeDocument.employee_id == employee_id).order_by(EmployeeDocument.uploaded_at.desc())).all()


def save_employee_document(employee_id, document_type, file, user, db):
    employee_document_access(employee_id, user, db, write=True)
    name = Path(file.filename or '').name
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, 'Use PDF, image, Word or text documents')
    if not document_type.strip() or len(document_type) > 100:
        raise HTTPException(422, 'Document type must contain 1 to 100 characters')
    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    if not content:
        raise HTTPException(400, 'Document is empty')
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, 'Document must be 10 MB or smaller')
    directory = UPLOAD_ROOT / 'documents'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f'{uuid4().hex}{extension}'
    target.write_bytes(content)
    try:
        document = EmployeeDocument(employee_id=employee_id, document_type=document_type.strip(), file_name=name[:255], file_path=str(target), uploaded_by=user.id)
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise


def downloadable_document(document_id, user, db):
    document = db.get(EmployeeDocument, document_id)
    if not document:
        raise HTTPException(404, 'Document not found')
    employee_document_access(document.employee_id, user, db)
    path = Path(document.file_path)
    if not path.is_absolute():
        path = UPLOAD_ROOT.parent / path
    path = path.resolve()
    if not path.is_relative_to(UPLOAD_ROOT.resolve()) or not path.is_file():
        raise HTTPException(404, 'Document file not found')
    return document, path
