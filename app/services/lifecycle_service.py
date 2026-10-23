from __future__ import annotations

from datetime import datetime, timezone
import json
from sqlalchemy import select,or_
from app.db.models import Employee,User,AuditLog
from app.services.workflow_notifications import notify_employee
from app.services.account_service import revoke_all
from app.core.business_time import business_today

from app.http import HTTPException
from sqlalchemy.orm import Session

from app.db.models import AssetInventory, ExitCase, OnboardingPlan, OfferLetter
from app.schemas.lifecycle import (
    AssetCreate,
    AssetUpdate,
    ExitCreate,
    ExitUpdate,
    OnboardingCreate,
    OnboardingUpdate,
    OfferCreate,
    OfferUpdate,
)


def _touch(record):
    if hasattr(record, 'updated_at'):
        record.updated_at = datetime.now(timezone.utc)
    return record


def _apply_updates(record, payload):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    return _touch(record)


def create_offer(db: Session, payload: OfferCreate) -> OfferLetter:
    offer = OfferLetter(**payload.model_dump())
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def list_offers(db: Session):
    return db.query(OfferLetter).order_by(OfferLetter.created_at.desc()).all()


def update_offer(db: Session, offer_id: str, payload: OfferUpdate) -> OfferLetter:
    offer = db.query(OfferLetter).filter(OfferLetter.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail='Offer not found')
    offer = _apply_updates(offer, payload)
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def _check_onboarding(db, record):
    if record.status not in {'Initiated','In Progress','Completed','On Hold'}:
        raise HTTPException(422,'Invalid onboarding status')
    employee=db.get(Employee,record.employee_id)
    if not employee or not employee.is_active:
        raise HTTPException(404,'Active employee not found')
    try:
        checklist=json.loads(record.checklist)
    except (ValueError,TypeError):
        raise HTTPException(422,'Checklist must be a JSON array')
    if not isinstance(checklist,list) or any(not isinstance(item,(str,dict)) for item in checklist):
        raise HTTPException(422,'Checklist must contain task labels or objects with label and done fields')
    if any(isinstance(item,dict) and (not isinstance(item.get('label'),str) or not isinstance(item.get('done'),bool)) for item in checklist):
        raise HTTPException(422,'Checklist tasks require a label and a done boolean')
    if record.status=='Completed' and any(isinstance(item,dict) and not item['done'] for item in checklist):
        raise HTTPException(409,'Complete all onboarding tasks before marking this plan completed')


def _check_exit(db,record):
    if record.status not in {'Requested','In Progress','Approved','Closed'}:
        raise HTTPException(422,'Invalid exit status')
    employee=db.scalar(select(Employee).where(Employee.id==record.employee_id).with_for_update(of=Employee))
    if not employee: raise HTTPException(404,'Employee not found')
    if record.status!='Closed': return
    actor=db.info.get('actor')
    if actor and actor.employee_id==employee.id:
        raise HTTPException(403,'Another HR administrator must complete your exit')
    if not record.last_working_day or record.last_working_day>business_today(db,employee.tenant_id):
        raise HTTPException(409,'Closing an exit requires a last working day on or before today')
    assets=db.scalar(select(AssetInventory.id).where(AssetInventory.employee_id==employee.id).with_for_update(of=AssetInventory))
    if assets: raise HTTPException(409,'Return or explicitly unassign all employee assets before closing this exit')
    notify_employee(db,employee.id,'offboarding_completed','Your exit has been completed and account access will be disabled.')
    employee.is_active=False
    users=db.scalars(select(User).where(User.tenant_id==employee.tenant_id,or_(User.id==employee.id,User.email==employee.email)).with_for_update(of=User))
    for user in users:
        user.is_active=False
        revoke_all(user,db)
    db.add(AuditLog(tenant_id=employee.tenant_id,actor_id=actor.id if actor else None,action='access_removed',object_type='employee',object_id=employee.id,data='Exit closed; assets cleared; sessions revoked'))


def create_onboarding(db: Session, payload: OnboardingCreate) -> OnboardingPlan:
    onboarding = OnboardingPlan(**payload.model_dump())
    _check_onboarding(db,onboarding)
    db.add(onboarding)
    notify_employee(db,onboarding.employee_id,'onboarding_updated','Your onboarding plan is '+onboarding.status+'.')
    db.commit()
    db.refresh(onboarding)
    return onboarding


def list_onboarding(db: Session):
    return db.query(OnboardingPlan).order_by(OnboardingPlan.created_at.desc()).all()


def update_onboarding(db: Session, onboarding_id: str, payload: OnboardingUpdate) -> OnboardingPlan:
    onboarding = db.query(OnboardingPlan).filter(OnboardingPlan.id == onboarding_id).first()
    if not onboarding:
        raise HTTPException(status_code=404, detail='Onboarding record not found')
    if onboarding.status=='Completed' and payload.status and payload.status!='Completed':
        raise HTTPException(409,'Completed onboarding cannot be reopened here')
    onboarding = _apply_updates(onboarding, payload)
    _check_onboarding(db,onboarding)
    db.add(onboarding)
    notify_employee(db,onboarding.employee_id,'onboarding_updated','Your onboarding plan is '+onboarding.status+'.')
    db.commit()
    db.refresh(onboarding)
    return onboarding


def create_exit_case(db: Session, payload: ExitCreate) -> ExitCase:
    exit_case = ExitCase(**payload.model_dump())
    _check_exit(db,exit_case)
    db.add(exit_case)
    if exit_case.status!='Closed': notify_employee(db,exit_case.employee_id,'exit_updated','Your exit case is '+exit_case.status+'.')
    db.commit()
    db.refresh(exit_case)
    return exit_case


def list_exit_cases(db: Session):
    return db.query(ExitCase).order_by(ExitCase.created_at.desc()).all()


def update_exit_case(db: Session, exit_id: str, payload: ExitUpdate) -> ExitCase:
    exit_case = db.query(ExitCase).filter(ExitCase.id == exit_id).with_for_update(of=ExitCase).populate_existing().first()
    if not exit_case:
        raise HTTPException(status_code=404, detail='Exit record not found')
    if exit_case.status=='Closed':
        if payload.status and payload.status!='Closed': raise HTTPException(409,'A closed exit cannot be reopened here')
        return exit_case
    exit_case = _apply_updates(exit_case, payload)
    _check_exit(db,exit_case)
    db.add(exit_case)
    if exit_case.status!='Closed': notify_employee(db,exit_case.employee_id,'exit_updated','Your exit case is '+exit_case.status+'.')
    db.commit()
    db.refresh(exit_case)
    return exit_case


def _check_asset(db,asset):
    if asset.status not in {'Available','Assigned','Repair','Retired'}:
        raise HTTPException(422,'Invalid asset status')
    if asset.employee_id:
        employee=db.scalar(select(Employee).where(Employee.id==asset.employee_id).with_for_update(of=Employee))
        if not employee or not employee.is_active: raise HTTPException(404,'Active employee not found')
        asset.status='Assigned' if asset.status=='Available' else asset.status
        asset.assigned_on=asset.assigned_on or datetime.now(timezone.utc)
    elif asset.status=='Assigned':
        raise HTTPException(422,'Choose an employee before assigning an asset')


def create_asset(db: Session, payload: AssetCreate) -> AssetInventory:
    asset = AssetInventory(**payload.model_dump())
    _check_asset(db,asset)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def list_assets(db: Session):
    return db.query(AssetInventory).order_by(AssetInventory.created_at.desc()).all()


def update_asset(db: Session, asset_id: str, payload: AssetUpdate) -> AssetInventory:
    asset = db.query(AssetInventory).filter(AssetInventory.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail='Asset not found')
    old_employee=asset.employee_id
    if payload.status=='Available':
        asset.employee_id=None;asset.assigned_on=None
    asset = _apply_updates(asset, payload)
    if payload.status=='Available': asset.employee_id=None;asset.assigned_on=None
    if old_employee and not asset.employee_id:
        actor=db.info.get('actor')
        db.add(AuditLog(tenant_id=asset.tenant_id,actor_id=actor.id if actor else None,action='asset_returned',object_type='asset',object_id=asset.id,data=json.dumps({'employee_id':old_employee,'asset_tag':asset.asset_tag})))
        notify_employee(db,old_employee,'asset_returned','Your asset return was recorded: '+asset.name)
    if payload.employee_id is not None and asset.employee_id:
        asset.assigned_on = datetime.now(timezone.utc)
    _check_asset(db,asset)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def lifecycle_counts(db: Session):
    return {
        'offers': db.query(OfferLetter).count(),
        'onboarding': db.query(OnboardingPlan).count(),
        'exits': db.query(ExitCase).count(),
        'assets': db.query(AssetInventory).count(),
    }