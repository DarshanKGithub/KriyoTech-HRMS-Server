from __future__ import annotations

from datetime import datetime, timezone

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


def create_onboarding(db: Session, payload: OnboardingCreate) -> OnboardingPlan:
    onboarding = OnboardingPlan(**payload.model_dump())
    db.add(onboarding)
    db.commit()
    db.refresh(onboarding)
    return onboarding


def list_onboarding(db: Session):
    return db.query(OnboardingPlan).order_by(OnboardingPlan.created_at.desc()).all()


def update_onboarding(db: Session, onboarding_id: str, payload: OnboardingUpdate) -> OnboardingPlan:
    onboarding = db.query(OnboardingPlan).filter(OnboardingPlan.id == onboarding_id).first()
    if not onboarding:
        raise HTTPException(status_code=404, detail='Onboarding record not found')
    onboarding = _apply_updates(onboarding, payload)
    db.add(onboarding)
    db.commit()
    db.refresh(onboarding)
    return onboarding


def create_exit_case(db: Session, payload: ExitCreate) -> ExitCase:
    exit_case = ExitCase(**payload.model_dump())
    db.add(exit_case)
    db.commit()
    db.refresh(exit_case)
    return exit_case


def list_exit_cases(db: Session):
    return db.query(ExitCase).order_by(ExitCase.created_at.desc()).all()


def update_exit_case(db: Session, exit_id: str, payload: ExitUpdate) -> ExitCase:
    exit_case = db.query(ExitCase).filter(ExitCase.id == exit_id).first()
    if not exit_case:
        raise HTTPException(status_code=404, detail='Exit record not found')
    exit_case = _apply_updates(exit_case, payload)
    db.add(exit_case)
    db.commit()
    db.refresh(exit_case)
    return exit_case


def create_asset(db: Session, payload: AssetCreate) -> AssetInventory:
    asset = AssetInventory(**payload.model_dump())
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
    asset = _apply_updates(asset, payload)
    if payload.employee_id is not None and asset.employee_id:
        asset.assigned_on = datetime.now(timezone.utc)
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