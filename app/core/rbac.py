from collections.abc import Callable

from app.http import Depends, HTTPException, status
from app.http import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.services.auth_service import get_user_from_token
from app.db.models import Tenant, TenantFeature
from sqlalchemy import select

security = HTTPBearer(auto_error=False)


MODULE_PERMISSIONS: dict[str, set[str]] = {
    'employees': {
        'view_employee',
        'create_employee',
        'edit_employee',
        'delete_employee',
        'manage_employee',
        'upload_documents',
        'download_documents',
        'delete_documents',
    },
    'attendance': {
        'view_attendance',
        'view_attendance_own',
        'view_attendance_team',
        'mark_attendance',
        'approve_attendance',
        'manage_attendance',
        'manage_attendance_records',
        'request_attendance_correction',
    },
    'leave': {
        'apply_leave',
        'request_leave',
        'view_leave',
        'view_leave_own',
        'view_leave_team',
        'approve_leave',
        'reject_leave',
        'configure_leave_policies',
        'view_leave_analytics',
    },
    'payroll': {
        'view_payroll',
        'view_payslip_own',
        'download_payslip',
        'process_payroll',
        'export_payroll',
    },
    'recruitment': {
        'manage_recruitment',
        'create_job',
        'review_candidates',
        'schedule_interviews',
        'generate_offer_letters',
        'manage_onboarding',
        'manage_exit_management',
    },
    'performance': {
        'view_performance',
        'view_performance_own',
        'view_performance_team',
        'evaluate_performance',
        'manage_performance',
        'conduct_appraisals',
        'recommend_promotions',
    },
    'documents': {
        'view_documents',
        'upload_documents',
        'download_documents',
        'delete_documents',
        'manage_documents',
    },
    'settings': {
        'manage_settings',
        'manage_roles',
        'manage_workflows',
        'manage_integrations',
        'enable_modules',
        'disable_modules',
    },
    'reports': {
        'view_reports',
        'export_reports',
        'view_dashboard',
        'view_audit_logs',
    },
    'notifications': {
        'view_announcements',
        'manage_announcements',
        'manage_notifications',
        'send_notifications',
    },
    'engagement': {
        'view_holidays',
        'manage_holidays',
        'view_tasks',
        'assign_tasks',
        'view_project_allocation',
        'manage_gatepasses',
        'manage_helpdesk',
        'manage_grievances',
        'view_expense_claims_own',
        'submit_reimbursement',
        'approve_expenses',
        'raise_support_ticket',
    },
    'organization': {
        'view_org',
        'manage_org',
        'manage_shifts',
        'view_shift_schedule',
    },
    'common': {
        'view_dashboard',
        'view_profile',
        'edit_profile',
        'change_password',
    },
}


def _module_permissions(*module_names: str) -> set[str]:
    permissions: set[str] = set()
    for module_name in module_names:
        permissions.update(MODULE_PERMISSIONS.get(module_name, set()))
    return permissions


ROLE_PERMISSIONS: dict[str, set[str]] = {
    'Worker': {
        *_module_permissions('common'),
        'view_attendance_own',
        'mark_attendance',
        'request_attendance_correction',
        'apply_leave',
        'request_leave',
        'view_leave_own',
        'view_payslip_own',
        'download_payslip',
        'view_holidays',
        'view_announcements',
        'view_tasks',
        'view_shift_schedule',
        'view_expense_claims_own',
        'submit_reimbursement',
        'raise_support_ticket',
        'view_performance_own',
        'upload_documents',
    },
    'Employee': {
        *_module_permissions('common'),
        'view_attendance_own',
        'mark_attendance',
        'request_attendance_correction',
        'apply_leave',
        'request_leave',
        'view_leave_own',
        'view_payslip_own',
        'download_payslip',
        'view_holidays',
        'view_announcements',
        'view_tasks',
        'view_shift_schedule',
        'view_expense_claims_own',
        'submit_reimbursement',
        'raise_support_ticket',
        'view_performance_own',
        'upload_documents',
    },
    'Manager': {
        *_module_permissions('common', 'attendance', 'leave', 'performance', 'documents', 'engagement', 'reports'),
        'view_employee',
        'view_performance_team',
        'view_leave_team',
        'view_attendance_team',
        'assign_tasks',
        'conduct_appraisals',
        'recommend_promotions',
        'approve_expenses',
        'view_project_allocation',
    },
    'HR': {
        *_module_permissions(
            'common',
            'employees',
            'attendance',
            'leave',
            'payroll',
            'recruitment',
            'performance',
            'documents',
            'reports',
            'notifications',
            'engagement',
            'organization',
        ),
        'manage_employee',
        'manage_onboarding',
        'manage_exit_management',
        'configure_leave_policies',
        'manage_holidays',
        'view_leave_analytics',
        'view_performance_team',
        'review_candidates',
        'create_job',
        'schedule_interviews',
        'generate_offer_letters',
        'manage_documents',
        'manage_helpdesk',
        'manage_grievances',
    },
    'Admin': {
        '*',
    },
    'Super Admin': {
        '*',
    },
    'CEO': {
        *_module_permissions('employees', 'settings', 'recruitment'),
        *_module_permissions('common', 'reports', 'attendance', 'leave', 'payroll', 'performance', 'documents', 'notifications', 'engagement', 'organization'),
        'view_employee',
        'view_leave_analytics',
        'view_performance_team',
        'view_project_allocation',
    },
}


ROLE_PERMISSIONS['Manager'] -= {'manage_attendance', 'manage_attendance_records', 'configure_leave_policies', 'manage_holidays', 'manage_gatepasses', 'manage_helpdesk', 'manage_grievances', 'view_audit_logs'}


def _normalize_role(role: str | None) -> str:
    return (role or '').strip()


def get_permissions_for_role(role: str | None) -> set[str]:
    return set(ROLE_PERMISSIONS.get(_normalize_role(role), set()))


def has_permission(role: str | None, permission: str) -> bool:
    permissions = get_permissions_for_role(role)
    return '*' in permissions or permission in permissions


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')
    return get_user_from_token(credentials.credentials, db=db)


def require_permissions(*required_permissions: str) -> Callable[[User], User]:
    def _checker(user: User = Depends(get_current_user)) -> User:
        if not required_permissions:
            return user

        user_permissions = get_permissions_for_role(user.role)
        if '*' in user_permissions:
            return user

        for permission in required_permissions:
            if permission not in user_permissions:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient privileges')
        return user

    return _checker


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != 'Super Admin':
        raise HTTPException(status_code=403, detail='Platform administration requires a Super Admin account')
    return user


def require_entitlement(feature_key: str) -> Callable[[User], User]:
    """Require explicit company ownership, a current subscription and a module grant."""
    def _checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        from datetime import date
        from app.db.models import Subscription
        if not user.tenant_id:
            raise HTTPException(403, 'An organization assignment is required')
        tenant = db.get(Tenant, user.tenant_id)
        active = db.scalar(select(Subscription.id).where(Subscription.tenant_id == user.tenant_id, Subscription.status == 'active', Subscription.starts_at <= date.today(), Subscription.ends_at.is_(None) | (Subscription.ends_at >= date.today())))
        feature = db.scalar(select(TenantFeature.id).where(TenantFeature.tenant_id == user.tenant_id, TenantFeature.feature_key == feature_key, TenantFeature.enabled.is_(True)))
        if not tenant or not tenant.is_active or not active or not feature:
            raise HTTPException(403, 'An active subscription and enabled module are required')
        return user
    return _checker
