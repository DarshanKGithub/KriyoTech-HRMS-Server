from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class OfferCreate(BaseModel):
    employee_id: str
    candidate_id: Optional[str] = None
    title: str = Field(min_length=2, max_length=200)
    salary_amount: float = Field(ge=0)
    joining_date: Optional[date] = None
    status: str = 'Draft'
    notes: Optional[str] = None


class OfferUpdate(BaseModel):
    title: Optional[str] = None
    salary_amount: Optional[float] = Field(default=None, ge=0)
    joining_date: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class OfferPublic(OfferCreate):
    employee_name: str | None = None
    id: str
    created_at: datetime
    updated_at: datetime


class OnboardingCreate(BaseModel):
    employee_id: str
    probation_end_date: Optional[date] = None
    checklist: str = Field(default='[]')
    owner_id: Optional[str] = None
    status: str = 'Initiated'


class OnboardingUpdate(BaseModel):
    probation_end_date: Optional[date] = None
    checklist: Optional[str] = None
    owner_id: Optional[str] = None
    status: Optional[str] = None


class OnboardingPublic(OnboardingCreate):
    employee_name: str | None = None
    id: str
    created_at: datetime
    updated_at: datetime


class ExitCreate(BaseModel):
    employee_id: str
    exit_type: str = Field(min_length=2, max_length=100)
    reason: Optional[str] = None
    notice_period_end: Optional[date] = None
    last_working_day: Optional[date] = None
    settlement_amount: Optional[float] = Field(default=0, ge=0)
    status: str = 'Requested'


class ExitUpdate(BaseModel):
    exit_type: Optional[str] = None
    reason: Optional[str] = None
    notice_period_end: Optional[date] = None
    last_working_day: Optional[date] = None
    settlement_amount: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None


class ExitPublic(ExitCreate):
    employee_name: str | None = None
    id: str
    created_at: datetime
    updated_at: datetime


class AssetCreate(BaseModel):
    asset_tag: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=2, max_length=200)
    category: str = Field(min_length=2, max_length=100)
    serial_number: Optional[str] = None
    employee_id: Optional[str] = None
    status: str = 'Available'
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    asset_tag: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    serial_number: Optional[str] = None
    employee_id: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AssetPublic(AssetCreate):
    employee_name: str | None = None
    id: str
    assigned_on: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class LifecycleCounts(BaseModel):
    offers: int
    onboarding: int
    exits: int
    assets: int