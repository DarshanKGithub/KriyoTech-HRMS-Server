from app.http import Router, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.rbac import require_permissions, require_super_admin
from app.db.database import get_db
from app.db.models import User
from app.schemas.auth import RoleUpdateRequest, UserPublic
from app.schemas.audit import PaginatedAuditLogs, AuditLogPublic
from app.services.audit_service import create_audit_log, list_audit_logs
from app.services.auth_service import to_public_user
from app.db.models import User as DbUser
from app.core.config import settings
import razorpay
from app.schemas.auth import UserPublic as UserPublicSchema
from app.schemas.tenancy import (
    TenantCreate,
    TenantUpdate,
    TenantPublic,
    PlanCreate,
    PlanUpdate,
    PlanPublic,
    TenantFeatureCreate,
    TenantFeaturePublic,
    TenantFeatureBatchCreate,
    FeatureOption,
    FeatureBundleCreate,
    CustomPackageCreate,
    CustomPackagePublic,
    SubscriptionCreate,
    SubscriptionPublic,
)
from app.db.models import Tenant, Plan, TenantFeature, Subscription, FeaturePackage, FeaturePackageFeature, PlanFeature
from datetime import datetime, date, timedelta

router = Router()


@router.get('/audit-logs', response_model=PaginatedAuditLogs)
def audit_logs(page: int = 1, size: int = 20, object_type: str | None = None, actor_id: str | None = None,
               _user: User = Depends(require_permissions('view_audit_logs')), db: Session = Depends(get_db)):

    if _user.role != 'Super Admin' and not _user.tenant_id:
        raise HTTPException(403, 'An organization assignment is required')
    items, total = list_audit_logs(db=db, page=page, size=size, object_type=object_type, actor_id=actor_id, tenant_id=_user.tenant_id, platform=_user.role == 'Super Admin')
    return PaginatedAuditLogs(
        items=[AuditLogPublic(
            id=a.id,
            actor_id=a.actor_id,
            action=a.action,
            object_type=a.object_type,
            object_id=a.object_id,
            data=a.data,
            created_at=a.created_at.isoformat(),
        ) for a in items],
        total=total,
        page=page,
        size=size,
    )


@router.patch('/users/{user_id}/role', response_model=UserPublic)
def update_user_role(
    user_id: str,
    payload: RoleUpdateRequest,
    actor: User = Depends(require_permissions('manage_roles')),
    db: Session = Depends(get_db),
) -> UserPublic:
    allowed_roles = {'Worker', 'Employee', 'Manager', 'HR', 'Admin', 'Super Admin', 'CEO'}
    new_role = payload.role.strip()
    if new_role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid role')

    if actor.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot change your own role')

    target = db.scalar(select(User).where(User.id == user_id))
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')

    if actor.role != 'Super Admin':
        if not actor.tenant_id or target.tenant_id != actor.tenant_id or target.role == 'Super Admin' or new_role == 'Super Admin':
            raise HTTPException(status_code=403, detail='Cannot change roles outside your organization or assign a platform role')

    old_role = target.role
    if old_role == new_role:
        return to_public_user(target, db=db)

    # Prevent deleting/demoting last Super Admin.
    if old_role == 'Super Admin' and new_role != 'Super Admin':
        super_admin_count = db.scalar(select(func.count()).select_from(User).where(User.role == 'Super Admin'))
        if int(super_admin_count or 0) <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot modify last Super Admin')

    target.role = new_role
    create_audit_log(
        db,
        actor_id=actor.id,
        action='ROLE_UPDATED',
        object_type='User',
        object_id=target.id,
        data={
            'old_role': old_role,
            'new_role': new_role,
        },
    )
    db.commit()
    db.refresh(target)
    return to_public_user(target, db=db)


# --- Tenancy admin endpoints ---
@router.post('/tenants', response_model=TenantPublic)
def create_tenant(payload: TenantCreate, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    from app.services.company_service import provision_company
    tenant, _ = provision_company(payload.name, payload.domain, payload.admin_name, payload.admin_email, payload.admin_password, db)
    return TenantPublic(id=tenant.id, name=tenant.name, domain=tenant.domain, is_active=tenant.is_active)


@router.get('/tenants', response_model=list[TenantPublic])
def list_tenants(actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(Tenant).all()
    return [TenantPublic(id=r.id, name=r.name, domain=r.domain, is_active=r.is_active) for r in rows]


@router.get('/tenants/{tenant_id}', response_model=TenantPublic)
def get_tenant(tenant_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    t = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')
    return TenantPublic(id=t.id, name=t.name, domain=t.domain, is_active=t.is_active)


@router.patch('/tenants/{tenant_id}', response_model=TenantPublic)
def update_tenant(tenant_id: str, payload: TenantUpdate, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    t = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')
    if payload.name is not None:
        t.name = payload.name.strip()
    if payload.domain is not None:
        t.domain = payload.domain
    if payload.is_active is not None:
        t.is_active = payload.is_active
    db.commit()
    db.refresh(t)
    return TenantPublic(id=t.id, name=t.name, domain=t.domain, is_active=t.is_active)


@router.delete('/tenants/{tenant_id}')
def delete_tenant(tenant_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    t = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')
        
    from app.db.models import (
        User as DbUser, Employee, Department, Designation, Shift, AttendanceRule, LeaveType, 
        Holiday, SalaryComponent, TenantFeature, Subscription, EmployeeShiftAssignment,
        Attendance, LeaveBalance, LeaveRequest, TodoItem, GatePass, Salary, 
        EmployeeSalaryComponent, Payslip, PayslipComponent, SalaryHistory, 
        Timesheet, OvertimeRequest, AttendanceRegularization, CompOffRequest,
        BiometricLog, PerformanceAppraisal, Goal, KPI, EmployeeTraining, Certification,
        HelpdeskTicket, EmployeeGrievance, EmployeeDocument, OfferLetter, OnboardingPlan,
        ExitCase, SalaryStructure, Reimbursement, EmployeeLoan, Feedback, SurveyAnswer,
        JobPosting, JobApplication,
        Notification, NotificationPreference, Announcement, Survey, SurveyQuestion, SurveyResponse,
        AssetInventory, Interview
    )

    try:
        # Delete employee-dependent records
        employee_ids = db.scalars(select(Employee.id).where(Employee.tenant_id == tenant_id)).all()
        if employee_ids:
            # First level dependencies
            db.query(Attendance).filter(Attendance.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(LeaveBalance).filter(LeaveBalance.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(LeaveRequest).filter(LeaveRequest.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(TodoItem).filter(TodoItem.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(GatePass).filter(GatePass.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(Timesheet).filter(Timesheet.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(OvertimeRequest).filter(OvertimeRequest.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(AttendanceRegularization).filter(AttendanceRegularization.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(CompOffRequest).filter(CompOffRequest.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(BiometricLog).filter(BiometricLog.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(PerformanceAppraisal).filter(PerformanceAppraisal.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(Goal).filter(Goal.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(KPI).filter(KPI.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(EmployeeTraining).filter(EmployeeTraining.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(Certification).filter(Certification.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(HelpdeskTicket).filter(HelpdeskTicket.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(EmployeeGrievance).filter(EmployeeGrievance.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(EmployeeDocument).filter(EmployeeDocument.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(OfferLetter).filter(OfferLetter.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(OnboardingPlan).filter(OnboardingPlan.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(ExitCase).filter(ExitCase.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(SalaryStructure).filter(SalaryStructure.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(Reimbursement).filter(Reimbursement.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(EmployeeLoan).filter(EmployeeLoan.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(Feedback).filter(Feedback.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(EmployeeShiftAssignment).filter(EmployeeShiftAssignment.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(EmployeeSalaryComponent).filter(EmployeeSalaryComponent.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            
            # Detach assets
            db.query(AssetInventory).filter(AssetInventory.employee_id.in_(employee_ids)).update({"employee_id": None}, synchronize_session=False)
            
            # Survey Responses for Employees
            survey_response_ids = db.scalars(select(SurveyResponse.id).where(SurveyResponse.employee_id.in_(employee_ids))).all()
            if survey_response_ids:
                db.query(SurveyAnswer).filter(SurveyAnswer.response_id.in_(survey_response_ids)).delete(synchronize_session=False)
            db.query(SurveyResponse).filter(SurveyResponse.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            
            
            # Nested dependencies for Payslip
            payslip_ids = db.scalars(select(Payslip.id).where(Payslip.employee_id.in_(employee_ids))).all()
            if payslip_ids:
                db.query(PayslipComponent).filter(PayslipComponent.payslip_id.in_(payslip_ids)).delete(synchronize_session=False)
            db.query(Payslip).filter(Payslip.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            
            # Nested dependencies for Salary
            salary_ids = db.scalars(select(Salary.id).where(Salary.employee_id.in_(employee_ids))).all()
            if salary_ids:
                db.query(SalaryHistory).filter(SalaryHistory.salary_id.in_(salary_ids)).delete(synchronize_session=False)
            db.query(SalaryHistory).filter(SalaryHistory.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            db.query(Salary).filter(Salary.employee_id.in_(employee_ids)).delete(synchronize_session=False)
            
            # Break manager self-referential FK before deleting employees
            db.query(Employee).filter(Employee.tenant_id == tenant_id).update({"manager_id": None}, synchronize_session=False)

        # Delete tenant-dependent records
        department_ids = db.scalars(select(Department.id).where(Department.tenant_id == tenant_id)).all()
        if department_ids:
            job_posting_ids = db.scalars(select(JobPosting.id).where(JobPosting.department_id.in_(department_ids))).all()
            if job_posting_ids:
                job_app_ids = db.scalars(select(JobApplication.id).where(JobApplication.job_id.in_(job_posting_ids))).all()
                if job_app_ids:
                    db.query(Interview).filter(Interview.application_id.in_(job_app_ids)).delete(synchronize_session=False)
                db.query(JobApplication).filter(JobApplication.job_id.in_(job_posting_ids)).delete(synchronize_session=False)
            db.query(JobPosting).filter(JobPosting.department_id.in_(department_ids)).delete(synchronize_session=False)

        user_ids = db.scalars(select(DbUser.id).where(DbUser.tenant_id == tenant_id)).all()
        if user_ids:
            survey_ids = db.scalars(select(Survey.id).where(Survey.created_by.in_(user_ids))).all()
            if survey_ids:
                user_survey_response_ids = db.scalars(select(SurveyResponse.id).where(SurveyResponse.survey_id.in_(survey_ids))).all()
                if user_survey_response_ids:
                    db.query(SurveyAnswer).filter(SurveyAnswer.response_id.in_(user_survey_response_ids)).delete(synchronize_session=False)
                db.query(SurveyResponse).filter(SurveyResponse.survey_id.in_(survey_ids)).delete(synchronize_session=False)
                db.query(SurveyQuestion).filter(SurveyQuestion.survey_id.in_(survey_ids)).delete(synchronize_session=False)
            db.query(Survey).filter(Survey.created_by.in_(user_ids)).delete(synchronize_session=False)
            db.query(Announcement).filter(Announcement.author_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(Notification).filter(Notification.recipient_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(NotificationPreference).filter(NotificationPreference.user_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(Interview).filter(Interview.interviewer_id.in_(user_ids)).delete(synchronize_session=False)

        db.query(Employee).filter(Employee.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(DbUser).filter(DbUser.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(TenantFeature).filter(TenantFeature.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(Department).filter(Department.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(Designation).filter(Designation.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(Shift).filter(Shift.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(AttendanceRule).filter(AttendanceRule.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(LeaveType).filter(LeaveType.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(Holiday).filter(Holiday.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(SalaryComponent).filter(SalaryComponent.tenant_id == tenant_id).delete(synchronize_session=False)
        db.query(Subscription).filter(Subscription.tenant_id == tenant_id).delete(synchronize_session=False)
        
        # Finally delete tenant
        db.delete(t)
        db.commit()
        return {'message': 'Tenant deleted'}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# --- User tenancy management ---
@router.get('/users', response_model=list[UserPublicSchema])
def admin_list_users(actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(DbUser).all()
    return [to_public_user(u, db=db) for u in rows]


@router.patch('/users/{user_id}/tenant', response_model=UserPublicSchema)
def assign_user_to_tenant(user_id: str, tenant_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    target = db.scalar(select(DbUser).where(DbUser.id == user_id))
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')

    # Ensure tenant exists
    t = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')

    if target.role == 'Super Admin':
        raise HTTPException(403, 'Platform administrators cannot belong to a company')
    if target.tenant_id and target.tenant_id != tenant_id:
        raise HTTPException(409, 'An existing company assignment cannot be transferred here')
    from app.db.models import Employee
    from sqlalchemy import or_
    employees = list(db.scalars(select(Employee).where(or_(Employee.id == target.id, Employee.email == target.email))))
    if any(employee.tenant_id and employee.tenant_id != tenant_id for employee in employees):
        raise HTTPException(409, 'The employee already belongs to another company')
    target.tenant_id = tenant_id
    for employee in employees:
        employee.tenant_id = tenant_id
    db.commit()
    db.refresh(target)
    return to_public_user(target, db=db)


# Plans
@router.post('/plans', response_model=PlanPublic)
def create_plan(payload: PlanCreate, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    p = Plan(name=payload.name.strip(), price_cents=payload.price_cents, billing_period=payload.billing_period, description=payload.description)
    db.add(p)
    db.flush()
    for feature_key in payload.feature_keys:
        normalized_key = feature_key.strip()
        if not normalized_key:
            continue
        db.add(PlanFeature(plan_id=p.id, feature_key=normalized_key, is_included=True))
    db.commit()
    db.refresh(p)
    return PlanPublic(id=p.id, name=p.name, price_cents=p.price_cents, billing_period=p.billing_period, description=p.description, is_active=p.is_active)


@router.get('/plans', response_model=list[PlanPublic])
def list_plans(actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(Plan).all()
    return [PlanPublic(id=r.id, name=r.name, price_cents=r.price_cents, billing_period=r.billing_period, description=r.description, is_active=r.is_active) for r in rows]


@router.get('/packages', response_model=list[CustomPackagePublic])
def list_custom_packages(actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(FeaturePackage).all()
    return [CustomPackagePublic(
        id=r.id,
        name=r.name,
        description=r.description,
        price_cents=r.price_cents,
        feature_keys=[feature.feature_key for feature in r.features],
        created_at=r.created_at.isoformat(),
    ) for r in rows]


@router.post('/packages', response_model=CustomPackagePublic)
def create_custom_package(
    payload: CustomPackageCreate,
    actor: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> CustomPackagePublic:
    pkg = FeaturePackage(name=payload.name.strip(), description=payload.description or None, price_cents=payload.price_cents)
    db.add(pkg)
    db.flush()
    for feature_key in payload.feature_keys:
        normalized_key = feature_key.strip()
        if not normalized_key:
            continue
        db.add(FeaturePackageFeature(package_id=pkg.id, feature_key=normalized_key))
    db.commit()
    db.refresh(pkg)
    return CustomPackagePublic(
        id=pkg.id,
        name=pkg.name,
        description=pkg.description,
        price_cents=pkg.price_cents,
        feature_keys=[feature.feature_key for feature in pkg.features],
        created_at=pkg.created_at.isoformat(),
    )


@router.get('/packages/{package_id}', response_model=CustomPackagePublic)
def get_custom_package(package_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    pkg = db.scalar(select(FeaturePackage).where(FeaturePackage.id == package_id))
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Package not found')
    return CustomPackagePublic(
        id=pkg.id,
        name=pkg.name,
        description=pkg.description,
        price_cents=pkg.price_cents,
        feature_keys=[feature.feature_key for feature in pkg.features],
        created_at=pkg.created_at.isoformat(),
    )


@router.patch('/packages/{package_id}', response_model=CustomPackagePublic)
def update_custom_package(
    package_id: str,
    payload: CustomPackageCreate,
    actor: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> CustomPackagePublic:
    pkg = db.scalar(select(FeaturePackage).where(FeaturePackage.id == package_id))
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Package not found')
    pkg.name = payload.name.strip()
    pkg.description = payload.description or None
    pkg.price_cents = payload.price_cents
    db.query(FeaturePackageFeature).filter(FeaturePackageFeature.package_id == package_id).delete(synchronize_session=False)
    for feature_key in payload.feature_keys:
        normalized_key = feature_key.strip()
        if not normalized_key:
            continue
        db.add(FeaturePackageFeature(package_id=package_id, feature_key=normalized_key))
    db.commit()
    db.refresh(pkg)
    return CustomPackagePublic(
        id=pkg.id,
        name=pkg.name,
        description=pkg.description,
        price_cents=pkg.price_cents,
        feature_keys=[feature.feature_key for feature in pkg.features],
        created_at=pkg.created_at.isoformat(),
    )


@router.delete('/packages/{package_id}')
def delete_custom_package(package_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    pkg = db.scalar(select(FeaturePackage).where(FeaturePackage.id == package_id))
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Package not found')
    db.delete(pkg)
    db.commit()
    return {'message': 'Package deleted'}


@router.get('/plans/{plan_id}/features', response_model=list[FeatureOption])
def list_plan_features(plan_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    plan = db.scalar(select(Plan).where(Plan.id == plan_id))
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Plan not found')
    included = {pf.feature_key for pf in db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).all()}
    options = [
        FeatureOption(key='attendance_module', name='Attendance Module', description='Timesheets, regularization, and attendance reports', price_cents=29900, included='attendance_module' in included),
        FeatureOption(key='payroll_module', name='Payroll Module', description='Payroll processing, salary slips, and financial reports', price_cents=49900, included='payroll_module' in included),
        FeatureOption(key='employee_module', name='Employee Management', description='Employee directory, org chart, and lifecycle actions', price_cents=19900, included='employee_module' in included),
        FeatureOption(key='document_module', name='Document Center', description='Document uploads, approvals, and secure storage', price_cents=14900, included='document_module' in included),
        FeatureOption(key='helpdesk_module', name='Helpdesk Module', description='Support tickets, grievances, and gate pass management', price_cents=15900, included='helpdesk_module' in included),
    ]
    return options


@router.post('/plans/{plan_id}/features/batch', response_model=list[FeatureOption])
def update_plan_features(
    plan_id: str,
    payload: FeatureBundleCreate,
    actor: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> list[FeatureOption]:
    plan = db.scalar(select(Plan).where(Plan.id == plan_id))
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Plan not found')
    db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).delete(synchronize_session=False)
    for feature_key in payload.feature_keys:
        normalized_key = feature_key.strip()
        if not normalized_key:
            continue
        db.add(PlanFeature(plan_id=plan_id, feature_key=normalized_key, is_included=True))
    db.commit()
    return list_plan_features(plan_id=plan_id, actor=actor, db=db)


@router.get('/plans/{plan_id}', response_model=PlanPublic)
def get_plan(plan_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    p = db.scalar(select(Plan).where(Plan.id == plan_id))
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Plan not found')
    return PlanPublic(id=p.id, name=p.name, price_cents=p.price_cents, billing_period=p.billing_period, description=p.description, is_active=p.is_active)


@router.patch('/plans/{plan_id}', response_model=PlanPublic)
def update_plan(plan_id: str, payload: PlanUpdate, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    p = db.scalar(select(Plan).where(Plan.id == plan_id))
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Plan not found')
    if payload.name is not None:
        p.name = payload.name.strip()
    if payload.price_cents is not None:
        p.price_cents = payload.price_cents
    if payload.billing_period is not None:
        p.billing_period = payload.billing_period
    if payload.description is not None:
        p.description = payload.description
    if payload.is_active is not None:
        p.is_active = payload.is_active
    if payload.feature_keys is not None:
        db.query(PlanFeature).filter(PlanFeature.plan_id == plan_id).delete(synchronize_session=False)
        for feature_key in payload.feature_keys:
            normalized_key = feature_key.strip()
            if not normalized_key:
                continue
            db.add(PlanFeature(plan_id=plan_id, feature_key=normalized_key, is_included=True))
    db.commit()
    db.refresh(p)
    return PlanPublic(id=p.id, name=p.name, price_cents=p.price_cents, billing_period=p.billing_period, description=p.description, is_active=p.is_active)


@router.delete('/plans/{plan_id}')
def delete_plan(plan_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    p = db.scalar(select(Plan).where(Plan.id == plan_id))
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Plan not found')
    db.delete(p)
    db.commit()
    return {'message': 'Plan deleted'}


def _get_subscription_feature_keys(plan: Plan) -> list[str]:
    period = (plan.billing_period or 'monthly').lower()
    mapping = {
        'trial': ['subscription_active', 'subscription_trial'],
        'monthly': ['subscription_active', 'subscription_monthly'],
        '3-month': ['subscription_active', 'subscription_3month'],
        '6-month': ['subscription_active', 'subscription_6month'],
        '9-month': ['subscription_active', 'subscription_9month'],
        'yearly': ['subscription_active', 'subscription_yearly'],
    }
    return mapping.get(period, ['subscription_active', f'subscription_{period}'])


def _sync_subscription_features(tenant_id: str, plan: Plan, db: Session) -> None:
    active_keys = set(_get_subscription_feature_keys(plan))
    active_keys.update(db.scalars(select(PlanFeature.feature_key).where(PlanFeature.plan_id == plan.id, PlanFeature.is_included.is_(True))))
    existing = db.query(TenantFeature).filter(TenantFeature.tenant_id == tenant_id).all()
    seen: set[str] = set()
    for feature in existing:
        if feature.feature_key in active_keys:
            feature.enabled = True
            seen.add(feature.feature_key)
        elif feature.feature_key.startswith('subscription_'):
            feature.enabled = False

    for key in active_keys:
        if key not in seen:
            db.add(TenantFeature(tenant_id=tenant_id, feature_key=key, enabled=True))


def _subscription_to_public(subscription: Subscription, db: Session) -> SubscriptionPublic:
    plan = db.scalar(select(Plan).where(Plan.id == subscription.plan_id))
    return SubscriptionPublic(
        id=subscription.id,
        tenant_id=subscription.tenant_id,
        plan_id=subscription.plan_id,
        plan_name=plan.name if plan else 'Unknown',
        billing_period=plan.billing_period if plan else 'unknown',
        starts_at=subscription.starts_at,
        ends_at=subscription.ends_at,
        status=subscription.status,
        price_paid_cents=subscription.price_paid_cents,
    )


@router.post('/tenants/{tenant_id}/subscriptions', response_model=SubscriptionPublic)
def create_tenant_subscription(
    tenant_id: str,
    payload: SubscriptionCreate,
    actor: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> SubscriptionPublic:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')

    plan = db.scalar(select(Plan).where(Plan.id == payload.plan_id))
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Plan not found')

    start_date = payload.starts_at or date.today()
    period = (payload.billing_period or plan.billing_period or 'monthly').lower()
    duration_mapping = {
        'trial': 14,
        'monthly': 30,
        '3-month': 90,
        '6-month': 180,
        '9-month': 270,
        'yearly': 365,
    }
    duration_days = duration_mapping.get(period, 30)
    if payload.duration_months is not None:
        ends_at = start_date + timedelta(days=payload.duration_months * 30)
    else:
        ends_at = start_date + timedelta(days=duration_days)

    status = payload.status or 'active'
    razorpay_order_id = None
    razorpay_key = None
    
    if plan.price_cents > 0 and settings.razorpay_key_id and settings.razorpay_key_secret:
        status = 'pending_payment'

    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        starts_at=start_date,
        ends_at=ends_at,
        status=status,
        price_paid_cents=plan.price_cents,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    if status == 'pending_payment' and settings.razorpay_key_id and settings.razorpay_key_secret:
        try:
            client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
            order = client.order.create({
                "amount": plan.price_cents,
                "currency": "INR",
                "receipt": str(subscription.id)[:40],
                "notes": {
                    "subscription_id": str(subscription.id),
                    "tenant_id": str(tenant.id),
                    "plan_id": str(plan.id),
                }
            })
            razorpay_order_id = order['id']
            razorpay_key = settings.razorpay_key_id
            subscription.external_order_id = razorpay_order_id
            db.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Instantly activate and sync features
        _sync_subscription_features(tenant.id, plan, db)
        db.commit()

    resp = _subscription_to_public(subscription, db)
    resp.razorpay_order_id = razorpay_order_id
    resp.razorpay_key = razorpay_key
    return resp


@router.get('/subscriptions', response_model=list[SubscriptionPublic])
def list_subscriptions(actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(Subscription).all()
    return [_subscription_to_public(row, db) for row in rows]


from pydantic import BaseModel

class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str

@router.post('/subscriptions/verify-payment')
def verify_payment(payload: VerifyPaymentRequest, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=400, detail="Razorpay not configured")
    
    try:
        client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
        client.utility.verify_payment_signature({
            'razorpay_payment_id': payload.razorpay_payment_id,
            'razorpay_order_id': payload.razorpay_order_id,
            'razorpay_signature': payload.razorpay_signature
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    subscription = db.scalar(select(Subscription).where(Subscription.external_order_id == payload.razorpay_order_id).with_for_update(of=Subscription))
    if not subscription:
        raise HTTPException(404, 'Unknown payment order')
    try:
        payment = client.payment.fetch(payload.razorpay_payment_id)
    except Exception as exc:
        raise HTTPException(502, 'Unable to verify the payment with the provider') from exc
    if (payment.get('order_id') != subscription.external_order_id
            or payment.get('status') != 'captured'
            or payment.get('amount') != subscription.price_paid_cents
            or payment.get('currency') != 'INR'):
        raise HTTPException(400, 'A captured payment matching this order is required')
    if subscription.status == 'active':
        return {'status': 'success', 'message': 'Subscription is already active'}
    if subscription.status != 'pending_payment':
        raise HTTPException(409, 'Subscription is not awaiting payment')
    plan = db.get(Plan, subscription.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(409, 'The purchased plan is unavailable')
    subscription.status = 'active'
    subscription.starts_at = date.today()
    subscription.ends_at = subscription.starts_at + timedelta(days={'trial':14,'monthly':30,'3-month':90,'6-month':180,'9-month':270,'yearly':365}.get(plan.billing_period,30))
    _sync_subscription_features(subscription.tenant_id, plan, db)
    db.commit()
    return {'status': 'success', 'message': 'Payment verified and subscription activated'}


@router.get('/tenants/{tenant_id}/subscriptions', response_model=list[SubscriptionPublic])
def list_tenant_subscriptions(
    tenant_id: str,
    actor: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> list[SubscriptionPublic]:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')
    rows = db.query(Subscription).filter(Subscription.tenant_id == tenant_id).all()
    return [_subscription_to_public(row, db) for row in rows]


@router.delete('/subscriptions/{subscription_id}')
def cancel_subscription(subscription_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    sub = db.scalar(select(Subscription).where(Subscription.id == subscription_id))
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Subscription not found')
    
    sub.status = 'cancelled'
    
    # Also disable related tenant features if we cancel the subscription
    db.query(TenantFeature).filter(TenantFeature.tenant_id == sub.tenant_id, TenantFeature.feature_key.like('subscription_%')).update({"enabled": False}, synchronize_session=False)
    
    db.commit()
    return {'message': 'Subscription cancelled'}


# Tenant features
@router.post('/tenants/{tenant_id}/features', response_model=TenantFeaturePublic)
def add_tenant_feature(tenant_id: str, payload: TenantFeatureCreate, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    t = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')
    tf = TenantFeature(tenant_id=tenant_id, feature_key=payload.feature_key.strip(), enabled=bool(payload.enabled))
    db.add(tf)
    db.commit()
    db.refresh(tf)
    return TenantFeaturePublic(id=tf.id, tenant_id=tf.tenant_id, feature_key=tf.feature_key, enabled=tf.enabled, created_at=tf.created_at.isoformat())


@router.get('/tenants/{tenant_id}/features', response_model=list[TenantFeaturePublic])
def list_tenant_features(tenant_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(TenantFeature).filter(TenantFeature.tenant_id == tenant_id).all()
    return [TenantFeaturePublic(id=r.id, tenant_id=r.tenant_id, feature_key=r.feature_key, enabled=r.enabled, created_at=r.created_at.isoformat()) for r in rows]


@router.patch('/tenants/{tenant_id}/features/{feature_id}', response_model=TenantFeaturePublic)
def update_tenant_feature(tenant_id: str, feature_id: str, payload: TenantFeatureCreate, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    tf = db.scalar(select(TenantFeature).where(TenantFeature.id == feature_id, TenantFeature.tenant_id == tenant_id))
    if not tf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Feature not found')
    tf.feature_key = payload.feature_key.strip()
    tf.enabled = bool(payload.enabled)
    db.commit()
    db.refresh(tf)
    return TenantFeaturePublic(id=tf.id, tenant_id=tf.tenant_id, feature_key=tf.feature_key, enabled=tf.enabled, created_at=tf.created_at.isoformat())


@router.get('/features', response_model=list[FeatureOption])
def list_feature_options(actor: User = Depends(require_super_admin)):
    options = [
        FeatureOption(key='attendance_module', name='Attendance Module', description='Timesheets, regularization, and attendance reports', price_cents=29900),
        FeatureOption(key='payroll_module', name='Payroll Module', description='Payroll processing, salary slips, and financial reports', price_cents=49900),
        FeatureOption(key='employee_module', name='Employee Management', description='Employee directory, org chart, and lifecycle actions', price_cents=19900),
        FeatureOption(key='document_module', name='Document Center', description='Document uploads, approvals, and secure storage', price_cents=14900),
        FeatureOption(key='helpdesk_module', name='Helpdesk Module', description='Support tickets, grievances, and gate pass management', price_cents=15900),
    ]
    return options


@router.post('/tenants/{tenant_id}/features/batch', response_model=list[TenantFeaturePublic])
def add_tenant_features_batch(
    tenant_id: str,
    payload: TenantFeatureBatchCreate,
    actor: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> list[TenantFeaturePublic]:
    t = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tenant not found')

    created_features: list[TenantFeature] = []
    for feature_key in payload.feature_keys:
        normalized_key = feature_key.strip()
        if not normalized_key:
            continue

        existing = db.scalar(select(TenantFeature).where(TenantFeature.tenant_id == tenant_id, TenantFeature.feature_key == normalized_key))
        if existing:
            existing.enabled = True
            created_features.append(existing)
        else:
            new_feature = TenantFeature(tenant_id=tenant_id, feature_key=normalized_key, enabled=True)
            db.add(new_feature)
            created_features.append(new_feature)

    db.commit()
    return [TenantFeaturePublic(id=f.id, tenant_id=f.tenant_id, feature_key=f.feature_key, enabled=f.enabled, created_at=f.created_at.isoformat()) for f in created_features]


@router.delete('/tenants/{tenant_id}/features/{feature_id}')
def delete_tenant_feature(tenant_id: str, feature_id: str, actor: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    tf = db.scalar(select(TenantFeature).where(TenantFeature.id == feature_id, TenantFeature.tenant_id == tenant_id))
    if not tf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Feature not found')
    db.delete(tf)
    db.commit()
    return {'message': 'Tenant feature removed'}
