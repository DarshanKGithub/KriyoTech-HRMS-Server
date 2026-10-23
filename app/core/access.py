"""One API boundary for authentication, module authorization and entitlements."""
from datetime import date
from sqlalchemy import select
from app.http import HTTPException
from app.core.rbac import get_current_user, has_permission
from app.db.database import get_db

FEATURES = {
    'attendance': ('attendance_tracking', 'attendance_module'),
    'advanced-attendance': ('attendance_tracking', 'attendance_module'),
    'leave': ('leave_management', 'leave_module', 'attendance_module'),
    'payroll': ('payroll', 'payroll_module'), 'financials': ('payroll', 'payroll_module'),
    'documents': ('document_management', 'document_module'),
    'performance': ('performance_management', 'performance_module'),
    'helpdesk': ('helpdesk', 'helpdesk_module'),
}
PERMISSIONS = {
    'recruitment': ('manage_recruitment',), 'lifecycle': ('manage_onboarding', 'manage_exit_management', 'manage_recruitment'),
    'workflow': ('manage_workflows',), 'financials': ('view_payroll', 'view_payslip_own', 'approve_expenses'),
    'performance': ('view_performance', 'view_performance_own', 'view_performance_team'),
}
PUBLIC = {'/auth/login', '/auth/register', '/auth/forgot-password', '/auth/reset-password', '/auth/accept-invitation', '/billing/webhook', '/api/webhooks/stripe', '/api/webhooks/razorpay'}

def enforce(request, resolver, handler):
    path = request.path.rstrip('/')
    # Unrelated custom routers (including adapter tests) own their access policy.
    if not handler.__module__.startswith('app.api.routes.'):
        return
    db = resolver.call(get_db, dependency=True)
    db.info.pop('actor', None)
    if path in PUBLIC:
        return
    user = resolver.call(get_current_user, dependency=True)
    db = resolver.call(get_db, dependency=True)
    if user.role == 'Super Admin':
        if not path.startswith(('/admin', '/auth', '/tenants', '/billing', '/notifications', '/dashboard')):
            raise HTTPException(403, 'Open a company account to access HR operations')
        return
    module = 'performance' if handler.__module__.endswith('.performance') else path.split('/')[1]
    required = PERMISSIONS.get(module)
    if required and not any(has_permission(user.role, permission) for permission in required):
        raise HTTPException(403, 'Your role cannot access this module')
    if module in FEATURES:
        from app.db.models import TenantFeature, Subscription
        enabled = db.scalar(select(TenantFeature.id).where(TenantFeature.tenant_id == user.tenant_id, TenantFeature.feature_key.in_(FEATURES[module]), TenantFeature.enabled.is_(True)))
        active = db.scalar(select(Subscription.id).where(Subscription.tenant_id == user.tenant_id, Subscription.status == 'active', Subscription.starts_at <= date.today(), (Subscription.ends_at.is_(None) | (Subscription.ends_at >= date.today()))))
        if not enabled or not active:
            raise HTTPException(403, 'An active subscription and enabled module are required')
