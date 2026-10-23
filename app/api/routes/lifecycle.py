from app.http import Router, Depends
from sqlalchemy.orm import Session

from app.core.rbac import require_permissions, get_current_user
from app.db.database import get_db
from app.db.models import User,Employee
from app.schemas.lifecycle import (
    AssetCreate,
    AssetPublic,
    AssetUpdate,
    ExitCreate,
    ExitPublic,
    ExitUpdate,
    LifecycleCounts,
    OnboardingCreate,
    OnboardingPublic,
    OnboardingUpdate,
    OfferCreate,
    OfferPublic,
    OfferUpdate,
)
from app.services.lifecycle_service import (
    create_asset,
    create_exit_case,
    create_onboarding,
    create_offer,
    lifecycle_counts,
    list_assets,
    list_exit_cases,
    list_onboarding,
    list_offers,
    update_asset,
    update_exit_case,
    update_onboarding,
    update_offer,
)

router = Router()

def _public(item,schema,db):
    result=schema.model_validate(item,from_attributes=True)
    employee=db.get(Employee,item.employee_id) if item.employee_id else None
    result.employee_name=employee.full_name if employee else None
    return result



@router.get('/summary', response_model=LifecycleCounts)
def get_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return LifecycleCounts(**lifecycle_counts(db))


@router.get('/offers', response_model=list[OfferPublic])
def get_offers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_public(item, OfferPublic, db) for item in list_offers(db)]


@router.post('/offers', response_model=OfferPublic)
def post_offer(payload: OfferCreate, user: User = Depends(require_permissions('manage_recruitment')), db: Session = Depends(get_db)):
    return _public(create_offer(db, payload), OfferPublic, db)


@router.put('/offers/{offer_id}', response_model=OfferPublic)
def put_offer(offer_id: str, payload: OfferUpdate, user: User = Depends(require_permissions('manage_recruitment')), db: Session = Depends(get_db)):
    return _public(update_offer(db, offer_id, payload), OfferPublic, db)


@router.get('/onboarding', response_model=list[OnboardingPublic])
def get_onboarding(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_public(item, OnboardingPublic, db) for item in list_onboarding(db)]


@router.post('/onboarding', response_model=OnboardingPublic)
def post_onboarding(payload: OnboardingCreate, user: User = Depends(require_permissions('create_employee')), db: Session = Depends(get_db)):
    return _public(create_onboarding(db, payload), OnboardingPublic, db)


@router.put('/onboarding/{onboarding_id}', response_model=OnboardingPublic)
def put_onboarding(onboarding_id: str, payload: OnboardingUpdate, user: User = Depends(require_permissions('create_employee')), db: Session = Depends(get_db)):
    return _public(update_onboarding(db, onboarding_id, payload), OnboardingPublic, db)


@router.get('/exits', response_model=list[ExitPublic])
def get_exits(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_public(item, ExitPublic, db) for item in list_exit_cases(db)]


@router.post('/exits', response_model=ExitPublic)
def post_exit(payload: ExitCreate, user: User = Depends(require_permissions('delete_employee')), db: Session = Depends(get_db)):
    return _public(create_exit_case(db, payload), ExitPublic, db)


@router.put('/exits/{exit_id}', response_model=ExitPublic)
def put_exit(exit_id: str, payload: ExitUpdate, user: User = Depends(require_permissions('delete_employee')), db: Session = Depends(get_db)):
    return _public(update_exit_case(db, exit_id, payload), ExitPublic, db)


@router.get('/assets', response_model=list[AssetPublic])
def get_assets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_public(item, AssetPublic, db) for item in list_assets(db)]


@router.post('/assets', response_model=AssetPublic)
def post_asset(payload: AssetCreate, user: User = Depends(require_permissions('manage_org')), db: Session = Depends(get_db)):
    return _public(create_asset(db, payload), AssetPublic, db)


@router.put('/assets/{asset_id}', response_model=AssetPublic)
def put_asset(asset_id: str, payload: AssetUpdate, user: User = Depends(require_permissions('manage_org')), db: Session = Depends(get_db)):
    return _public(update_asset(db, asset_id, payload), AssetPublic, db)