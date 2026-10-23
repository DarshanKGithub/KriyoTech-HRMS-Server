from sqlalchemy import Numeric
from datetime import datetime, timezone, date, timedelta
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Date, Numeric, select, ForeignKey, Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship

from app.core.security import hash_password
from app.db.database import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    # relationship to Tenant added later (Tenant class defined below)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


SEED_USERS = [
    ('Aditi Sharma', 'admin@hrms.com', 'Admin'),
    ('Riya Nair', 'hr@hrms.com', 'HR'),
    ('Arjun Mehta', 'manager@hrms.com', 'Manager'),
    ('Neha Kapoor', 'employee@hrms.com', 'Employee'),
    ('Vikram Rao', 'ceo@hrms.com', 'CEO'),
]


def seed_demo_users(db: Session) -> None:
    existing_emails = set(db.query(User.email).all())
    existing_emails = {email for (email,) in existing_emails}
    created = False

    # Ensure a demo tenant exists and assign seeded users to it
    try:
        demo_tenant = db.scalar(select(Tenant).where(Tenant.name == 'Demo Tenant'))
    except Exception:
        demo_tenant = None

    if demo_tenant is None:
        demo_tenant = Tenant(name='Demo Tenant', domain='demo.hrms')
        db.add(demo_tenant)
        try:
            db.commit()
            db.refresh(demo_tenant)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    for full_name, email, role in SEED_USERS:
        normalized_email = email.lower()
        if normalized_email in existing_emails:
            continue

        # Generate a shared id so seeded User and Employee map to same id for demo convenience
        new_id = str(uuid4())

        db.add(
            User(
                id=new_id,
                full_name=full_name,
                email=normalized_email,
                role=role,
                tenant_id=demo_tenant.id if demo_tenant else None,
                password_hash=hash_password('Hrms@12345'),
            )
        )

        # Also create a corresponding Employee record so front-end "user.id" maps to an employee
        try:
            db.add(
                Employee(
                    id=new_id,
                    full_name=full_name,
                    email=normalized_email,
                )
            )
        except Exception:
            # If Employee class not yet defined or other issue, skip creating employee here
            pass

        created = True

    if created:
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass


# --- Tenancy & Subscription models ---


class Tenant(Base):
    __tablename__ = 'tenants'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default='Asia/Kolkata')
    working_days_json: Mapped[str] = mapped_column(Text, nullable=False, default='[0,1,2,3,4]')
    subscriptions: Mapped[list['Subscription']] = relationship('Subscription', back_populates='tenant', cascade='all, delete-orphan')


class Plan(Base):
    __tablename__ = 'plans'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    billing_period: Mapped[str] = mapped_column(String(20), nullable=False, default='monthly')
    description: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    subscriptions: Mapped[list['Subscription']] = relationship('Subscription', back_populates='plan', cascade='all, delete-orphan')
    features: Mapped[list['PlanFeature']] = relationship('PlanFeature', back_populates='plan', cascade='all, delete-orphan')


class PlanFeature(Base):
    __tablename__ = 'plan_features'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey('plans.id'), nullable=False, index=True)
    feature_key: Mapped[str] = mapped_column(String(120), nullable=False)
    is_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    plan: Mapped['Plan'] = relationship('Plan', back_populates='features', lazy='joined')


class FeaturePackage(Base):
    __tablename__ = 'feature_packages'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    features: Mapped[list['FeaturePackageFeature']] = relationship('FeaturePackageFeature', back_populates='package', cascade='all, delete-orphan')


class FeaturePackageFeature(Base):
    __tablename__ = 'feature_package_features'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    package_id: Mapped[str] = mapped_column(String(36), ForeignKey('feature_packages.id'), nullable=False, index=True)
    feature_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    package: Mapped['FeaturePackage'] = relationship('FeaturePackage', back_populates='features', lazy='joined')


class Subscription(Base):
    __tablename__ = 'subscriptions'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey('plans.id'), nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    price_paid_cents: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    starts_at: Mapped[date] = mapped_column(nullable=False)
    ends_at: Mapped[date] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='active')  # active, cancelled, unpaid
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    tenant = relationship('Tenant', back_populates='subscriptions', lazy='joined')
    plan = relationship('Plan', back_populates='subscriptions', lazy='joined')


class TenantFeature(Base):
    __tablename__ = 'tenant_features'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=False, index=True)
    feature_key: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))



# --- Phase 2 models: Departments, Designations, Employees ---


class Department(Base):
    __tablename__ = 'departments'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Designation(Base):
    __tablename__ = 'designations'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Employee(Base):
    __tablename__ = 'employees'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=True)
    gender: Mapped[str] = mapped_column(String(20), nullable=True)  # Male, Female, Other, Prefer not to say
    personal_email: Mapped[str] = mapped_column(String(255), nullable=True)
    address: Mapped[str] = mapped_column(String(500), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=True)
    state: Mapped[str] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[str] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(100), nullable=True)
    emergency_contact_name: Mapped[str] = mapped_column(String(120), nullable=True)
    emergency_contact_phone: Mapped[str] = mapped_column(String(20), nullable=True)
    emergency_contact_relationship: Mapped[str] = mapped_column(String(50), nullable=True)
    bank_account_number: Mapped[str] = mapped_column(String(50), nullable=True)
    bank_ifsc_code: Mapped[str] = mapped_column(String(20), nullable=True)
    pan_number: Mapped[str] = mapped_column(String(20), nullable=True)
    aadhar_number: Mapped[str] = mapped_column(String(20), nullable=True)
    department_id: Mapped[str] = mapped_column(String(36), ForeignKey('departments.id'), nullable=True)
    designation_id: Mapped[str] = mapped_column(String(36), ForeignKey('designations.id'), nullable=True)
    manager_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=True)
    joining_date: Mapped[date] = mapped_column(Date, nullable=True)
    date_of_confirmation: Mapped[date] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    department: Mapped['Department'] = relationship('Department', lazy='selectin')
    designation: Mapped['Designation'] = relationship('Designation', lazy='selectin')
    manager: Mapped['Employee'] = relationship('Employee', remote_side=[id], lazy='selectin')


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_id: Mapped[str] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    object_type: Mapped[str] = mapped_column(String(60), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=True)
    data: Mapped[str] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def seed_demo_org(db: Session) -> None:
    """Seed a couple of departments/designations for Phase 2 initial data."""
    try:
        existing_depts = {name for (name,) in db.query(Department.name).all()}
    except Exception:
        existing_depts = set()

    defaults = ["Engineering", "People Operations", "Finance"]
    created = False
    for name in defaults:
        if name in existing_depts:
            continue
        db.add(Department(name=name))
        created = True

    try:
        existing_designs = {name for (name,) in db.query(Designation.name).all()}
    except Exception:
        existing_designs = set()

    designs = ["Engineer", "HR Manager", "Payroll Specialist"]
    for name in designs:
        if name in existing_designs:
            continue
        db.add(Designation(name=name))
        created = True

    if created:
        db.commit()


def seed_demo_plans(db: Session) -> None:
    try:
        existing_names = {name for (name,) in db.query(Plan.name).all()}
    except Exception:
        existing_names = set()

    defaults = [
        ('Trial', 0, 'trial', '14-day free trial subscription'),
        ('Monthly', 99900, 'monthly', 'Monthly subscription for 30 days'),
        ('3-Month', 279900, '3-month', '3 month subscription'),
        ('6-Month', 529900, '6-month', '6 month subscription'),
        ('9-Month', 749900, '9-month', '9 month subscription'),
        ('Yearly', 999900, 'yearly', '12 month subscription'),
    ]
    created = False
    for name, price, period, description in defaults:
        if name in existing_names:
            continue
        db.add(Plan(name=name, price_cents=price, billing_period=period, description=description))
        created = True

    if created:
        db.commit()


def seed_demo_tenant_subscription(db: Session) -> None:
    try:
        demo_tenant = db.scalar(select(Tenant).where(Tenant.name == 'Demo Tenant'))
    except Exception:
        demo_tenant = None

    if not demo_tenant:
        return

    try:
        current_sub = db.query(Subscription).filter(Subscription.tenant_id == demo_tenant.id, Subscription.status == 'active').first()
    except Exception:
        current_sub = None

    if current_sub:
        return

    plan = db.scalar(select(Plan).where(Plan.billing_period == 'monthly'))
    if not plan:
        return

    today = date.today()
    db.add(Subscription(
        tenant_id=demo_tenant.id,
        plan_id=plan.id,
        starts_at=today,
        ends_at=today + timedelta(days=30),
        status='active',
        price_paid_cents=plan.price_cents,
    ))
    db.commit()


# --- Phase 4 models: Shifts, Attendance, Attendance Rules ---
from datetime import date, time


class Shift(Base):
    __tablename__ = 'shifts'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # e.g., "Morning", "Evening", "Night"
    start_time: Mapped[time] = mapped_column(nullable=False)  # e.g., 09:00
    end_time: Mapped[time] = mapped_column(nullable=False)  # e.g., 18:00
    grace_period_minutes: Mapped[int] = mapped_column(nullable=False, default=0)  # e.g., 5 minutes grace
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EmployeeShiftAssignment(Base):
    __tablename__ = 'employee_shift_assignments'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    shift_id: Mapped[str] = mapped_column(String(36), ForeignKey('shifts.id'), nullable=False)
    start_date: Mapped[date] = mapped_column(nullable=False)  # When assignment starts
    end_date: Mapped[date] = mapped_column(nullable=True)  # When assignment ends (null = ongoing)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Attendance(Base):
    __tablename__ = 'attendance'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    attendance_date: Mapped[date] = mapped_column(nullable=False, index=True)
    check_in_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    check_in_latitude: Mapped[float] = mapped_column(Float, nullable=True)
    check_in_longitude: Mapped[float] = mapped_column(Float, nullable=True)
    check_out_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_latitude: Mapped[float] = mapped_column(Float, nullable=True)
    check_out_longitude: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # present, absent, half-day, work-from-home
    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    late_minutes: Mapped[int] = mapped_column(nullable=False, default=0)
    is_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_work_from_home: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    breaks: Mapped[list['AttendanceBreak']] = relationship('AttendanceBreak', back_populates='attendance', cascade='all, delete-orphan')

class AttendanceBreak(Base):
    __tablename__ = 'attendance_breaks'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    attendance_id: Mapped[str] = mapped_column(String(36), ForeignKey('attendance.id', ondelete='CASCADE'), nullable=False, index=True)
    break_type: Mapped[str] = mapped_column(String(50), nullable=False, default='lunch')
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    attendance: Mapped['Attendance'] = relationship('Attendance', back_populates='breaks')


class AttendanceRule(Base):
    __tablename__ = 'attendance_rules'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # e.g., "Late Entry After 9:30 AM"
    rule_type: Mapped[str] = mapped_column(String(60), nullable=False)  # late_entry, early_exit, half_day, etc.
    threshold_minutes: Mapped[int] = mapped_column(nullable=False)  # e.g., 30 minutes late = late entry
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def seed_demo_shifts(db: Session) -> None:
    """Seed default shifts for Phase 4."""
    try:
        existing_shifts = {name for (name,) in db.query(Shift.name).all()}
    except Exception:
        existing_shifts = set()

    shifts_data = [
        ("Morning", "09:00", "18:00", 5),
        ("Evening", "14:00", "23:00", 5),
        ("Night", "23:00", "08:00", 5),
    ]
    created = False
    for name, start_str, end_str, grace in shifts_data:
        if name in existing_shifts:
            continue
        from datetime import time as time_type
        start_time = time_type(*map(int, start_str.split(":")))
        end_time = time_type(*map(int, end_str.split(":")))
        db.add(Shift(name=name, start_time=start_time, end_time=end_time, grace_period_minutes=grace))
        created = True

    try:
        existing_rules = {name for (name,) in db.query(AttendanceRule.name).all()}
    except Exception:
        existing_rules = set()

    rules_data = [
        ("Late Entry After 30 Minutes", "late_entry", 30),
        ("Half Day Below 4 Hours", "half_day", 240),
        ("Early Exit More Than 30 Minutes", "early_exit", 30),
    ]
    for name, rule_type, threshold in rules_data:
        if name in existing_rules:
            continue
        db.add(AttendanceRule(name=name, rule_type=rule_type, threshold_minutes=threshold))
        created = True

    if created:
        db.commit()


def seed_demo_leave_data(db: Session) -> None:
    """Seed default leave types and a couple of holidays for Phase 5 demo."""
    try:
        existing_types = {name for (name,) in db.query(LeaveType.name).all()}
    except Exception:
        existing_types = set()

    leave_types = [
        ("Casual Leave", "Short-term casual leave", 7),
        ("Sick Leave", "Sick or medical leave", 10),
        ("Paid Leave", "Paid annual leave", 14),
        ("Loss Of Pay", "Loss of pay leave", 0),
        ("Comp - Off", "Compensatory off", 3),
        ("Sabbatical Leave", "Long-term unpaid leave", 30),
        ("Election Leave", "Leave for voting", 1),
        ("Unplanned Leave", "Emergency leave", 5),
        ("Contingency Leave", "Contingency leave", 2),
        ("Work From Home", "Remote work days", 5),
        ("Floater Leave", "Flexible leave days", 3),
        ("Paternity Leave", "Paternity leave", 5),
    ]
    created = False
    for name, desc, days in leave_types:
        if name in existing_types:
            continue
        try:
            # Use a SAVEPOINT per row so one bad insert doesn't poison startup seeding.
            with db.begin_nested():
                db.add(LeaveType(name=name, description=desc, default_days_per_year=days))
                db.flush()
            created = True
            existing_types.add(name)
        except Exception:
            continue

    try:
        existing_holidays = {d for (d,) in db.query(Holiday.holiday_date).all()}
    except Exception:
        existing_holidays = set()

    holidays = [
        ("New Year's Day", date(2026, 1, 1)),
        ("Company Foundation Day", date(2026, 8, 15)),
    ]
    for name, hd in holidays:
        if hd in existing_holidays:
            continue
        try:
            with db.begin_nested():
                db.add(Holiday(name=name, holiday_date=hd, is_public=True))
                db.flush()
            created = True
            existing_holidays.add(hd)
        except Exception:
            continue

    # Seed leave balances for all employees
    try:
        employees = db.query(Employee).all()
        leave_types_obj = db.query(LeaveType).all()
        current_year = date.today().year
        
        for emp in employees:
            for lt in leave_types_obj:
                existing_balance = db.query(LeaveBalance).filter(
                    LeaveBalance.employee_id == emp.id,
                    LeaveBalance.leave_type_id == lt.id,
                    LeaveBalance.year == current_year
                ).first()
                
                if not existing_balance:
                    balance = LeaveBalance(
                        employee_id=emp.id,
                        leave_type_id=lt.id,
                        year=current_year,
                        granted_days=lt.default_days_per_year,
                        balance_days=lt.default_days_per_year
                    )
                    try:
                        with db.begin_nested():
                            db.add(balance)
                            db.flush()
                        created = True
                    except Exception:
                        continue
    except Exception as e:
        pass

    if created:
        try:
            db.commit()
        except Exception:
            db.rollback()


# --- Phase 5 models: Leave Management ---
from sqlalchemy import Integer


class LeaveType(Base):
    __tablename__ = 'leave_types'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    default_days_per_year: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class LeaveBalance(Base):
    __tablename__ = 'leave_balances'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    leave_type_id: Mapped[str] = mapped_column(String(36), ForeignKey('leave_types.id'), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    granted_days: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    balance_days: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    leave_type: Mapped['LeaveType'] = relationship('LeaveType', lazy='selectin')


class LeaveRequest(Base):
    __tablename__ = 'leave_requests'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    leave_type_id: Mapped[str] = mapped_column(String(36), ForeignKey('leave_types.id'), nullable=False)
    start_date: Mapped[date] = mapped_column(nullable=False)
    end_date: Mapped[date] = mapped_column(nullable=False)
    session_from: Mapped[str] = mapped_column(String(50), nullable=True, default='Session 1')
    session_to: Mapped[str] = mapped_column(String(50), nullable=True, default='Session 2')
    days_requested: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    deducted_days: Mapped[float | None] = mapped_column(Numeric(6,2), nullable=True, default=0)
    reason: Mapped[str] = mapped_column(String(1000), nullable=True)
    contact_details: Mapped[str] = mapped_column(String(500), nullable=True)
    cc_to: Mapped[str] = mapped_column(String(1000), nullable=True)  # JSON array of emails
    attachment_paths: Mapped[str] = mapped_column(String(2000), nullable=True)  # JSON array of file paths
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='pending')  # pending, approved, rejected, cancelled
    approver_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    leave_type: Mapped['LeaveType'] = relationship('LeaveType', lazy='selectin')
    employee: Mapped['Employee'] = relationship('Employee', lazy='selectin', foreign_keys=[employee_id])


# --- Simple To Do model for user tasks / personal checklist
class TodoItem(Base):
    __tablename__ = 'todo_items'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='open')  # open, in_progress, done
    due_date: Mapped[date] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Holiday(Base):
    __tablename__ = 'holidays'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    holiday_date: Mapped[date] = mapped_column(nullable=False, index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# --- Gate Pass Module ---
class GatePass(Base):
    __tablename__ = 'gate_passes'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False)  # Personal Work, Medical, Emergency, Official Work
    reason: Mapped[str] = mapped_column(String(1000), nullable=True)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_return_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='pending')  # pending, approved, rejected
    approver_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    admin_comments: Mapped[str] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# --- Phase 6 models: Payroll Management ---
from sqlalchemy import Numeric


class Salary(Base):
    __tablename__ = 'salaries'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    base_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    grade: Mapped[str] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='INR')
    effective_from: Mapped[date] = mapped_column(nullable=False)
    effective_to: Mapped[date] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SalaryComponent(Base):
    __tablename__ = 'salary_components'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    component_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EmployeeSalaryComponent(Base):
    __tablename__ = 'employee_salary_components'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    salary_component_id: Mapped[str] = mapped_column(String(36), ForeignKey('salary_components.id'), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Payslip(Base):
    __tablename__ = 'payslips'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    base_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    gross_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total_deductions: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_tax: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    net_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    days_worked: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    days_absent: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='draft')
    processed_by: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class PayslipComponent(Base):
    __tablename__ = 'payslip_components'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    payslip_id: Mapped[str] = mapped_column(String(36), ForeignKey('payslips.id'), nullable=False, index=True)
    salary_component_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('salary_components.id'), nullable=True)
    component_name: Mapped[str] = mapped_column(String(120), nullable=False)
    component_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SalaryHistory(Base):
    """Tracks all salary changes for audit trail and compliance."""
    __tablename__ = 'salary_history'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    salary_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('salaries.id'), nullable=True)
    base_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default='INR')
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason_for_change: Mapped[str | None] = mapped_column(String(255), nullable=True)  # e.g., 'promotion', 'salary_revision', 'demotion'
    modified_by: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    employee: Mapped[Employee] = relationship('Employee', foreign_keys=[employee_id])
    modified_by_user: Mapped[User] = relationship('User', foreign_keys=[modified_by])

    def __repr__(self) -> str:
        return f'<SalaryHistory(employee_id={self.employee_id}, base_salary={self.base_salary}, effective_from={self.effective_from})>'


def seed_demo_salary_data(db: Session) -> None:
    """Seed default salary components for payroll demo."""
    try:
        existing_components = {name for (name,) in db.query(SalaryComponent.name).all()}
    except Exception:
        existing_components = set()

    components_data = [
        ("Basic Salary", "earning", "Monthly base salary"),
        ("House Rent Allowance", "earning", "HRA component"),
        ("Dearness Allowance", "earning", "DA component"),
        ("Provident Fund", "deduction", "PF contribution"),
        ("Income Tax", "tax", "IT deduction"),
    ]
    created = False
    for name, comp_type, desc in components_data:
        if name in existing_components:
            continue
        try:
            db.add(SalaryComponent(name=name, component_type=comp_type, description=desc))
            created = True
        except Exception:
            continue

    if created:
        db.commit()


# --- Phase 7 models: Advanced Attendance & Time Tracking ---

class Timesheet(Base):
    __tablename__ = 'timesheets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    date: Mapped["date"] = mapped_column(Date, nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=True)
    task_description: Mapped[str] = mapped_column(String(1000), nullable=False)
    hours_worked: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Draft') # Draft, Submitted, Approved, Rejected
    approver_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class OvertimeRequest(Base):
    __tablename__ = 'overtime_requests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    attendance_id: Mapped[str] = mapped_column(String(36), ForeignKey('attendance.id'), nullable=True)
    date: Mapped["date"] = mapped_column(Date, nullable=False)
    hours: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Pending') # Pending, Approved, Rejected
    approver_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AttendanceRegularization(Base):
    __tablename__ = 'attendance_regularizations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    attendance_id: Mapped[str] = mapped_column(String(36), ForeignKey('attendance.id'), nullable=True)
    date: Mapped["date"] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    requested_check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_check_out: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Pending') # Pending, Approved, Rejected
    approver_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class CompOffRequest(Base):
    __tablename__ = 'comp_off_requests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    worked_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=True)
    leave_balance_id: Mapped[str] = mapped_column(String(36), ForeignKey('leave_balances.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Pending') # Pending, Approved, Rejected
    approver_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class BiometricDevice(Base):
    __tablename__ = 'biometric_devices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    device_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Active')
    last_sync_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class BiometricLog(Base):
    __tablename__ = 'biometric_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey('biometric_devices.id'), nullable=False)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    log_type: Mapped[str] = mapped_column(String(20), nullable=False) # In, Out
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Unprocessed') # Unprocessed, Processed, Error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Roster(Base):
    __tablename__ = 'rosters'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class RosterEntry(Base):
    __tablename__ = 'roster_entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    roster_id: Mapped[str] = mapped_column(String(36), ForeignKey('rosters.id'), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    date: Mapped["date"] = mapped_column(Date, nullable=False)
    shift_id: Mapped[str] = mapped_column(String(36), ForeignKey('shifts.id'), nullable=True)
    is_off_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# --- Phase 8 models: Performance, Training & Engagement ---

class PerformanceAppraisal(Base):
    __tablename__ = 'performance_appraisals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=True)
    review_period: Mapped[str] = mapped_column(String(100), nullable=False) # e.g. "Q1 2026"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Draft') # Draft, Submitted, Completed
    review_date: Mapped[date] = mapped_column(Date, nullable=True)
    rating: Mapped[float] = mapped_column(Numeric(3, 1), nullable=True)
    goals_achieved: Mapped[str] = mapped_column(String(2000), nullable=True)
    areas_for_improvement: Mapped[str] = mapped_column(String(2000), nullable=True)
    comments: Mapped[str] = mapped_column(String(2000), nullable=True)
    next_review_date: Mapped[date] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Goal(Base):
    __tablename__ = 'goals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    appraisal_id: Mapped[str] = mapped_column(String(36), ForeignKey('performance_appraisals.id'), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Active') # Active, Paused, Completed, Cancelled
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=True)
    achieved_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=True)
    achievement_percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class KPI(Base):
    __tablename__ = 'kpis'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    goal_id: Mapped[str] = mapped_column(String(36), ForeignKey('goals.id'), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Active') # Active, Paused, Completed
    target_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    achieved_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=True, default=0.0)
    weightage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class TrainingCourse(Base):
    __tablename__ = 'training_courses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    instructor: Mapped[str] = mapped_column(String(120), nullable=True)
    duration_hours: Mapped[float] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EmployeeTraining(Base):
    __tablename__ = 'employee_trainings'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey('training_courses.id'), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Enrolled') # Enrolled, In Progress, Completed
    completion_date: Mapped[date] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Certification(Base):
    __tablename__ = 'certifications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    verification_id: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuing_authority: Mapped[str] = mapped_column(String(120), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Announcement(Base):
    __tablename__ = 'announcements'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=False)
    priority: Mapped[str] = mapped_column(String(30), nullable=False, default='Normal') # Low, Normal, High
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class HelpdeskTicket(Base):
    __tablename__ = 'helpdesk_tickets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default='General') # IT, HR, Payroll, Admin
    priority: Mapped[str] = mapped_column(String(30), nullable=False, default='Medium') # Low, Medium, High, Critical
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Open') # Open, In Progress, Resolved, Closed
    assigned_to: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class EmployeeGrievance(Base):
    __tablename__ = 'employee_grievances'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    against_employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Submitted') # Submitted, Investigating, Resolved
    investigator_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=True)
    investigation_notes: Mapped[str] = mapped_column(String(2000), nullable=True)
    meeting_scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class EmployeeDocument(Base):
    __tablename__ = 'employee_documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False) # e.g., 'ID Proof', 'Offer Letter', 'Resume', 'Other'
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

# --- Phase 9 models: Recruitment and ATS ---

class JobPosting(Base):
    __tablename__ = 'job_postings'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[str] = mapped_column(String(36), ForeignKey('departments.id'), nullable=True)
    location: Mapped[str] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str] = mapped_column(String(50), nullable=True) # Full-time, Part-time, Contract
    description: Mapped[str] = mapped_column(String(4000), nullable=False)
    requirements: Mapped[str] = mapped_column(String(4000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Open') # Open, Closed, Draft
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class Candidate(Base):
    __tablename__ = 'candidates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    resume_url: Mapped[str] = mapped_column(String(1000), nullable=True)
    parsed_skills: Mapped[str] = mapped_column(String(2000), nullable=True) # JSON array
    source: Mapped[str] = mapped_column(String(100), nullable=True) # LinkedIn, Website, Referral
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class JobApplication(Base):
    __tablename__ = 'job_applications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey('job_postings.id'), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey('candidates.id'), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default='Applied') # Applied, Screening, Interviewing, Offered, Hired, Rejected
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# --- Phase 10.5 models: Offers, Onboarding, Exits, Assets ---

class OfferLetter(Base):
    __tablename__ = 'offer_letters'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey('candidates.id'), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    salary_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    joining_date: Mapped[date] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Draft')
    notes: Mapped[str] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class OnboardingPlan(Base):
    __tablename__ = 'onboarding_plans'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    probation_end_date: Mapped[date] = mapped_column(Date, nullable=True)
    checklist: Mapped[str] = mapped_column(String(2000), nullable=False, default='[]')
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Initiated')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ExitCase(Base):
    __tablename__ = 'exit_cases'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    exit_type: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=True)
    notice_period_end: Mapped[date] = mapped_column(Date, nullable=True)
    last_working_day: Mapped[date] = mapped_column(Date, nullable=True)
    settlement_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Requested')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AssetInventory(Base):
    __tablename__ = 'asset_inventory'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    asset_tag: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(120), nullable=True)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Available')
    assigned_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class Interview(Base):
    __tablename__ = 'interviews'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    application_id: Mapped[str] = mapped_column(String(36), ForeignKey('job_applications.id'), nullable=False)
    interviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meeting_link: Mapped[str] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Scheduled') # Scheduled, Completed, Cancelled
    feedback: Mapped[str] = mapped_column(String(2000), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=True) # 1-5
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

# --- Phase 10 models: Advanced Financials & Compensation ---

class SalaryStructure(Base):
    __tablename__ = 'salary_structures'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), unique=True, index=True)
    base_salary: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    hra: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    da: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    special_allowance: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    pf_percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=12.0)
    esi_percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.75)
    tax_bracket_percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class Reimbursement(Base):
    __tablename__ = 'reimbursements'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), index=True)
    expense_type: Mapped[str] = mapped_column(String(100), nullable=False) # Travel, Medical, Food, Office Supplies
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    receipt_url: Mapped[str] = mapped_column(String(500), nullable=True)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Pending') # Pending, Approved, Rejected, Paid
    applied_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class EmployeeLoan(Base):
    __tablename__ = 'employee_loans'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), index=True)
    loan_type: Mapped[str] = mapped_column(String(50), nullable=False) # Personal, Advance Salary
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    interest_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)
    emi_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    remaining_balance: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Active') # Active, Closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# --- Phase 13: Notification Automation ---

class NotificationTemplate(Base):
    __tablename__ = 'notification_templates'
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)  # leave_approved, payslip_generated, etc.
    channel: Mapped[str] = mapped_column(String(50), nullable=False)  # email, sms, in_app, push
    subject: Mapped[str] = mapped_column(String(200), nullable=True)  # For email
    body: Mapped[str] = mapped_column(String(2000), nullable=False)  # Template with {variable} placeholders
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    __tablename__ = 'notifications'
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    recipient_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey('notification_templates.id'), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)  # email, sms, in_app, push
    subject: Mapped[str] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    data: Mapped[str] = mapped_column(String(2000), nullable=True)  # JSON metadata
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Pending')  # Pending, Sent, Failed, Read
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class NotificationPreference(Base):
    __tablename__ = 'notification_preferences'
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=False, index=True, unique=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), nullable=True)  # HH:MM format
    quiet_hours_end: Mapped[str] = mapped_column(String(5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))



from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from uuid import uuid4
from app.db.database import Base

class Survey(Base):
    __tablename__ = 'surveys'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Draft') # Draft, Active, Closed
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

class SurveyQuestion(Base):
    __tablename__ = 'survey_questions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    survey_id: Mapped[str] = mapped_column(String(36), ForeignKey('surveys.id'), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(String(500), nullable=False)
    question_type: Mapped[str] = mapped_column(String(30), nullable=False) # Rating, Text, MultipleChoice
    options: Mapped[str] = mapped_column(String(1000), nullable=True) # JSON string of options
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

class SurveyResponse(Base):
    __tablename__ = 'survey_responses'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    survey_id: Mapped[str] = mapped_column(String(36), ForeignKey('surveys.id'), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class SurveyAnswer(Base):
    __tablename__ = 'survey_answers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    response_id: Mapped[str] = mapped_column(String(36), ForeignKey('survey_responses.id'), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(36), ForeignKey('survey_questions.id'), nullable=False)
    answer_text: Mapped[str] = mapped_column(String(2000), nullable=True)
    rating_value: Mapped[int] = mapped_column(Integer, nullable=True)

class Feedback(Base):
    __tablename__ = 'feedback'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey('employees.id'), nullable=True)
    feedback_type: Mapped[str] = mapped_column(String(50), nullable=False) # Peer, Manager, Anonymous
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

# --- Phase 9 models: Dynamic Workflow Engine & Form Builder ---

class FormTemplate(Base):
    __tablename__ = 'form_templates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    schema_json: Mapped[str] = mapped_column(String(5000), nullable=False) # JSON definition of form fields
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class WorkflowTemplate(Base):
    __tablename__ = 'workflow_templates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_event: Mapped[str] = mapped_column(String(120), nullable=False) # e.g. "ON_EMPLOYEE_JOIN"
    steps_json: Mapped[str] = mapped_column(String(5000), nullable=False) # JSON array defining sequence of steps
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class WorkflowInstance(Base):
    __tablename__ = 'workflow_instances'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey('workflow_templates.id'), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False) # e.g. employee_id or document_id
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='In Progress') # In Progress, Completed, Failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))



# Every business row has explicit ownership, including roots such as jobs/forms.
# Global product catalog and tenant registry are platform-owned.
# Account security records are durable across workers and restarts.
class TaxDeclaration(Base):
    __tablename__ = 'tax_declarations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    employee_id: Mapped[str] = mapped_column(ForeignKey('employees.id'), nullable=False, index=True)
    financial_year: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    declared_amount: Mapped[float] = mapped_column(Numeric(12,2), nullable=False)
    approved_amount: Mapped[float | None] = mapped_column(Numeric(12,2), nullable=True)
    proof_document_id: Mapped[str | None] = mapped_column(ForeignKey('employee_documents.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='Draft')
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc), nullable=False)

class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AccountToken(Base):
    __tablename__ = 'account_tokens'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)

class AuthRateLimit(Base):
    __tablename__ = 'auth_rate_limits'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

class MailMessage(Base):
    __tablename__ = 'mail_messages'
    notification_id: Mapped[str | None] = mapped_column(ForeignKey('notifications.id'),nullable=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='queued', nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

from sqlalchemy import Column, UniqueConstraint
GLOBAL_TABLES = {'tenants', 'plans', 'plan_features', 'feature_packages', 'feature_package_features', 'auth_rate_limits'}
TENANT_MODELS = []
for _mapper in list(Base.registry.mappers):
    _model = _mapper.class_
    if _mapper.local_table.name not in GLOBAL_TABLES:
        if 'tenant_id' not in _mapper.local_table.c:
            setattr(_model, 'tenant_id', Column(String(36), ForeignKey('tenants.id'), nullable=True, index=True))
        TENANT_MODELS.append(_model)
Payslip.__table__.append_constraint(UniqueConstraint('employee_id', 'month', 'year', name='uq_payslip_employee_period'))
