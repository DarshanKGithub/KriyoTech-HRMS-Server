from app.http import Router, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.core.rbac import require_permissions
from app.db.database import get_db
from app.db.models import User, EmployeeDocument, Employee
from app.schemas.document import EmployeeDocumentPublic
from app.services.document_service import save_employee_document
from app.services.auth_service import resolve_employee_id

router = Router()

class DocumentWithEmployeePublic(EmployeeDocumentPublic):
    employee_name: str

@router.get('/', response_model=list[DocumentWithEmployeePublic])
def get_all_documents(user: User = Depends(require_permissions('view_employee')), db: Session = Depends(get_db)):
    query = db.query(EmployeeDocument, Employee).join(Employee, EmployeeDocument.employee_id == Employee.id)
    if user.role != 'Super Admin':
        # Unassigned accounts never gain an unscoped organization document query.
        query = query.filter(Employee.tenant_id == user.tenant_id) if user.tenant_id else query.filter(Employee.id == user.id)
        if user.role == 'Manager':
            query = query.filter(Employee.manager_id == resolve_employee_id(user, db))
    return [DocumentWithEmployeePublic(**EmployeeDocumentPublic.model_validate(doc, from_attributes=True).model_dump(), employee_name=employee.full_name) for doc, employee in query.all()]

@router.post('/', response_model=EmployeeDocumentPublic)
def upload_document(employee_id: str = Form(...), document_type: str = Form(...), file: UploadFile = File(...), user: User = Depends(require_permissions('manage_employee')), db: Session = Depends(get_db)):
    return save_employee_document(employee_id, document_type, file, user, db)
