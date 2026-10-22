from app.http import Router, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.rbac import get_current_user, require_permissions
from app.db.database import get_db
from app.db.models import User, FormTemplate, WorkflowTemplate, WorkflowInstance
from app.services.workflow_service import (
    FormTemplateCreate,
    WorkflowTemplateCreate,
    create_form_template,
    list_form_templates,
    create_workflow_template,
    list_workflow_templates,
    trigger_workflow,
    advance_workflow
)
from pydantic import BaseModel
from datetime import datetime

router = Router()

# --- Schemas ---
class FormTemplatePublic(BaseModel):
    id: str
    name: str
    description: Optional[str]
    schema_json: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class WorkflowTemplatePublic(BaseModel):
    id: str
    name: str
    trigger_event: str
    steps_json: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class WorkflowInstancePublic(BaseModel):
    id: str
    template_id: str
    target_id: str
    current_step: int
    status: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# --- Endpoints ---

@router.post('/forms', response_model=FormTemplatePublic)
def api_create_form_template(
    payload: FormTemplateCreate,
    user: User = Depends(require_permissions('manage_workflows')),
    db: Session = Depends(get_db)
):
    try:
        return create_form_template(payload, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get('/forms', response_model=List[FormTemplatePublic])
def api_list_form_templates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return list_form_templates(db)

@router.post('/templates', response_model=WorkflowTemplatePublic)
def api_create_workflow_template(
    payload: WorkflowTemplateCreate,
    user: User = Depends(require_permissions('manage_workflows')),
    db: Session = Depends(get_db)
):
    try:
        return create_workflow_template(payload, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get('/templates', response_model=List[WorkflowTemplatePublic])
def api_list_workflow_templates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return list_workflow_templates(db)

@router.post('/trigger/{event_name}', response_model=List[WorkflowInstancePublic])
def api_trigger_workflow(
    event_name: str,
    target_id: str = Query(...),
    user: User = Depends(require_permissions('manage_workflows')),
    db: Session = Depends(get_db)
):
    return trigger_workflow(event_name, target_id, db)

@router.post('/instances/{instance_id}/advance', response_model=WorkflowInstancePublic)
def api_advance_workflow(
    instance_id: str,
    user: User = Depends(require_permissions('manage_workflows')),
    db: Session = Depends(get_db)
):
    inst = advance_workflow(instance_id, db)
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")
    return inst
