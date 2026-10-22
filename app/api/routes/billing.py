"""Authenticated order creation and strictly verified, replay-safe webhooks."""
import hashlib
import hmac
import json
from datetime import date, timedelta
from uuid import uuid4
from sqlalchemy import select
from app.core.config import settings
from app.core.rbac import require_permissions
from app.db.models import Subscription, Tenant, Plan
from app.db.database import get_db
from app.http import Router, Depends, HTTPException, Request

router = Router()

@router.post('/create-order')
def create_order(payload: dict, user=Depends(require_permissions('manage_settings')), db=Depends(get_db)):
    tenant_id, plan_id = payload.get('tenant_id'), payload.get('plan_id')
    if user.role != 'Super Admin' and tenant_id != user.tenant_id:
        raise HTTPException(403, 'Cannot purchase for another company')
    tenant, plan = db.get(Tenant, tenant_id), db.get(Plan, plan_id)
    if not tenant or not tenant.is_active or not plan or not plan.is_active:
        raise HTTPException(404, 'Active organization and plan are required')
    if not settings.razorpay_key_id or not settings.razorpay_key_secret or not settings.razorpay_webhook_secret:
        raise HTTPException(503, 'Verified payment processing is not configured')
    if plan.price_cents <= 0:
        raise HTTPException(400, 'Use platform plan assignment for free plans')
    import razorpay
    sub = Subscription(id=str(uuid4()), tenant_id=tenant.id, plan_id=plan.id, starts_at=date.today(), status='pending_payment', price_paid_cents=plan.price_cents)
    order = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret)).order.create({'amount': plan.price_cents, 'currency': 'INR', 'receipt': sub.id, 'notes': {'subscription_id': sub.id, 'tenant_id': tenant.id, 'plan_id': plan.id}})
    sub.external_order_id = order['id']
    db.add(sub); db.commit()
    return {'order': order, 'razorpay_key_id': settings.razorpay_key_id, 'subscription_id': sub.id}


def verified_webhook(request, db):
    secret = settings.razorpay_webhook_secret
    if not secret:
        raise HTTPException(503, 'Payment webhook verification is not configured')
    signature = request.headers.get('X-Razorpay-Signature', '')
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(400, 'Invalid webhook signature')
    try:
        event = json.loads(request.body)
    except ValueError as exc:
        raise HTTPException(400, 'Invalid event payload') from exc
    kind = event.get('event')
    if kind not in {'order.paid', 'payment.captured'}:
        return {'ok': True}
    entity = event.get('payload', {}).get('order' if kind == 'order.paid' else 'payment', {}).get('entity', {})
    order_id = entity.get('id') if kind == 'order.paid' else entity.get('order_id')
    sub = db.scalar(select(Subscription).where(Subscription.external_order_id == order_id).with_for_update(of=Subscription)) if order_id else None
    if not sub:
        raise HTTPException(404, 'Unknown payment order')
    if entity.get('currency') != 'INR' or entity.get('amount') != sub.price_paid_cents:
        raise HTTPException(400, 'Payment amount or currency does not match the order')
    if sub.status == 'active':
        return {'ok': True}
    if sub.status not in {'pending', 'pending_payment'}:
        raise HTTPException(409, 'Subscription is not awaiting payment')
    plan = db.get(Plan, sub.plan_id)
    sub.status = 'active'
    sub.starts_at = date.today()
    sub.ends_at = sub.starts_at + timedelta(days=365 if plan.billing_period == 'yearly' else 30)
    from app.api.routes.admin import _sync_subscription_features
    _sync_subscription_features(sub.tenant_id, plan, db)
    db.commit()
    return {'ok': True}

@router.post('/webhook')
def webhook(request: Request, db=Depends(get_db)):
    return verified_webhook(request, db)
