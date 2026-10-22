from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date


class TenantCreate(BaseModel):
    name: str = Field(min_length=1)
    domain: Optional[str] = None
    admin_name: str = Field(min_length=1)
    admin_email: str = Field(min_length=3)
    admin_password: str = Field(min_length=8)


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_active: Optional[bool] = None


class TenantPublic(BaseModel):
    id: str
    name: str
    domain: Optional[str] = None
    is_active: bool


class PlanCreate(BaseModel):
    name: str = Field(min_length=1)
    price_cents: int = 0
    billing_period: str = 'monthly'
    description: Optional[str] = None
    feature_keys: list[str] = []


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    price_cents: Optional[int] = None
    billing_period: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    feature_keys: Optional[list[str]] = None


class PlanPublic(BaseModel):
    id: str
    name: str
    price_cents: int
    billing_period: str
    description: Optional[str] = None
    is_active: bool


class TenantFeatureCreate(BaseModel):
    feature_key: str = Field(min_length=1)
    enabled: bool = True


class TenantFeaturePublic(BaseModel):
    id: str
    tenant_id: str
    feature_key: str
    enabled: bool
    created_at: str


class TenantFeatureBatchCreate(BaseModel):
    feature_keys: list[str] = Field(min_items=1)


class FeatureBundleCreate(BaseModel):
    feature_keys: list[str] = Field(min_items=1)


class FeatureOption(BaseModel):
    key: str
    name: str
    description: Optional[str] = None
    price_cents: int
    included: Optional[bool] = None


class CustomPackageCreate(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    price_cents: int
    feature_keys: list[str] = Field(min_items=1)


class CustomPackagePublic(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    price_cents: int
    feature_keys: list[str]
    created_at: str


class SubscriptionCreate(BaseModel):
    plan_id: str
    starts_at: Optional[date] = None
    duration_months: Optional[int] = None
    billing_period: Optional[str] = None
    status: Optional[str] = 'active'


class SubscriptionPublic(BaseModel):
    id: str
    tenant_id: str
    plan_id: str
    plan_name: str
    billing_period: str
    starts_at: date
    ends_at: Optional[date] = None
    status: str
    price_paid_cents: Optional[int] = None
    razorpay_order_id: Optional[str] = None
    razorpay_key: Optional[str] = None
