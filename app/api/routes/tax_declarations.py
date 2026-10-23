"""Employee declarations and proof review; no statutory tax calculation."""
from datetime import datetime,timezone
from decimal import Decimal
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.http import Depends,HTTPException
from app.core.rbac import get_current_user,require_permissions
from app.db.database import get_db
from app.db.models import TaxDeclaration,EmployeeDocument,Employee,AuditLog
from app.services.auth_service import resolve_employee_id
from app.services.workflow_notifications import notify_employee

class DeclarationInput(BaseModel):
    financial_year:int=Field(ge=2000,le=2200)
    category:str=Field(min_length=2,max_length=120)
    declared_amount:Decimal=Field(gt=0,le=9999999999)
    proof_document_id:str|None=None
class DeclarationReview(BaseModel):
    approve:bool
    approved_amount:Decimal|None=Field(default=None,ge=0)
    note:str=Field(min_length=2,max_length=1000)


def public(item,db):
    employee=db.get(Employee,item.employee_id)
    return {'id':item.id,'employee_id':item.employee_id,'employee_name':employee.full_name if employee else '', 'financial_year':item.financial_year,'category':item.category,'declared_amount':float(item.declared_amount),'approved_amount':float(item.approved_amount) if item.approved_amount is not None else None,'proof_document_id':item.proof_document_id,'status':item.status,'review_note':item.review_note}


def proof_for(db,proof_id,employee_id):
    if proof_id:
        proof=db.get(EmployeeDocument,proof_id)
        if not proof or proof.employee_id!=employee_id:
            raise HTTPException(404,'Proof document not found for this employee')
        from pathlib import Path
        from app.services.document_service import UPLOAD_ROOT
        path=Path(proof.file_path).resolve()
        if not path.is_relative_to(UPLOAD_ROOT.resolve()) or not path.is_file():
            raise HTTPException(409,'The proof file is unavailable. Upload it again.')


def mount(router):
    @router.get('/tax-declarations')
    def list_declarations(year:int|None=None,user=Depends(get_current_user),db:Session=Depends(get_db)):
        query=select(TaxDeclaration)
        if user.role not in {'HR','Admin','CEO'}: query=query.where(TaxDeclaration.employee_id==resolve_employee_id(user,db))
        if year: query=query.where(TaxDeclaration.financial_year==year)
        return [public(item,db) for item in db.scalars(query.order_by(TaxDeclaration.created_at.desc()).limit(500))]

    @router.post('/tax-declarations')
    def create_declaration(payload:DeclarationInput,user=Depends(get_current_user),db:Session=Depends(get_db)):
        employee_id=resolve_employee_id(user,db)
        if not employee_id: raise HTTPException(403,'An employee profile is required')
        proof_for(db,payload.proof_document_id,employee_id)
        item=TaxDeclaration(employee_id=employee_id,**payload.model_dump())
        db.add(item);db.commit();db.refresh(item)
        return public(item,db)

    @router.put('/tax-declarations/{declaration_id}')
    def edit_declaration(declaration_id:str,payload:DeclarationInput,user=Depends(get_current_user),db:Session=Depends(get_db)):
        item=db.scalar(select(TaxDeclaration).where(TaxDeclaration.id==declaration_id).with_for_update(of=TaxDeclaration))
        if not item: raise HTTPException(404,'Declaration not found')
        if item.employee_id!=resolve_employee_id(user,db): raise HTTPException(403,'Only the employee can edit this declaration')
        if item.status not in {'Draft','Rejected'}: raise HTTPException(409,'Only drafts and rejected declarations can be edited')
        proof_for(db,payload.proof_document_id,item.employee_id)
        for key,value in payload.model_dump().items(): setattr(item,key,value)
        item.status='Draft';item.approved_amount=None;item.reviewer_id=None;item.review_note=None;item.updated_at=datetime.now(timezone.utc)
        db.commit();return public(item,db)

    @router.post('/tax-declarations/{declaration_id}/submit')
    def submit_declaration(declaration_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
        item=db.scalar(select(TaxDeclaration).where(TaxDeclaration.id==declaration_id).with_for_update(of=TaxDeclaration))
        if not item: raise HTTPException(404,'Declaration not found')
        if item.employee_id!=resolve_employee_id(user,db): raise HTTPException(403,'Only the employee can submit this declaration')
        if item.status!='Draft': raise HTTPException(409,'Only draft declarations can be submitted')
        proof_for(db,item.proof_document_id,item.employee_id)
        item.status='Submitted';item.updated_at=datetime.now(timezone.utc)
        notify_employee(db,item.employee_id,'tax_review_required','An investment declaration needs review.',roles=('HR','Admin','CEO'))
        db.commit();return public(item,db)

    @router.post('/tax-declarations/{declaration_id}/review')
    def review_declaration(declaration_id:str,payload:DeclarationReview,user=Depends(require_permissions('process_payroll')),db:Session=Depends(get_db)):
        item=db.scalar(select(TaxDeclaration).where(TaxDeclaration.id==declaration_id).with_for_update(of=TaxDeclaration))
        if not item: raise HTTPException(404,'Declaration not found')
        if item.employee_id==resolve_employee_id(user,db): raise HTTPException(403,'Another HR reviewer must review your declaration')
        if item.status!='Submitted': raise HTTPException(409,'Only submitted declarations can be reviewed')
        if payload.approve and not item.proof_document_id: raise HTTPException(409,'A proof document is required before approval')
        proof_for(db,item.proof_document_id,item.employee_id)
        amount=payload.approved_amount if payload.approved_amount is not None else item.declared_amount
        if amount>item.declared_amount: raise HTTPException(422,'Approved amount cannot exceed the declaration')
        item.status='Approved' if payload.approve else 'Rejected';item.approved_amount=amount if payload.approve else 0
        item.review_note=payload.note;item.reviewer_id=user.id;item.updated_at=datetime.now(timezone.utc)
        notify_employee(db,item.employee_id,'tax_'+item.status.lower(),'Your investment declaration was '+item.status.lower()+'. '+payload.note)
        db.add(AuditLog(actor_id=user.id,action='tax_review',object_type='tax_declaration',object_id=item.id,data=item.status))
        db.commit();return public(item,db)
