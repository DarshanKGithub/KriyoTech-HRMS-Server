from app.http import Router, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.rbac import get_current_user
from app.db.database import get_db
from app.db.models import User, Subscription, Plan, Tenant

router = Router()

@router.get('/me/subscription')
def get_my_subscription(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the active subscription details for the current user's tenant."""
    if not user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User is not associated with any tenant")

    # Fetch the tenant
    tenant = db.scalar(select(Tenant).where(Tenant.id == user.tenant_id))
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # Fetch the active subscription
    subscription = db.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == user.tenant_id, Subscription.status == 'active')
        .order_by(Subscription.created_at.desc())
    )

    if not subscription:
        return {
            "tenant_name": tenant.name,
            "domain": tenant.domain,
            "has_active_subscription": False,
            "subscription": None
        }

    # Fetch the plan associated with the subscription
    plan = db.scalar(select(Plan).where(Plan.id == subscription.plan_id))

    return {
        "tenant_name": tenant.name,
        "domain": tenant.domain,
        "has_active_subscription": True,
        "subscription": {
            "id": subscription.id,
            "status": subscription.status,
            "starts_at": subscription.starts_at,
            "ends_at": subscription.ends_at,
            "price_paid_cents": subscription.price_paid_cents,
            "plan": {
                "id": plan.id if plan else None,
                "name": plan.name if plan else "Custom",
                "billing_cycle": plan.billing_period if plan else None,
                "max_employees": None,
            }
        }
    }
