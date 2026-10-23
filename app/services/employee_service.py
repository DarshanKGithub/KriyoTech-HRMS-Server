from datetime import date
from typing import List, Tuple
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.http import HTTPException, status
from uuid import uuid4
from sqlalchemy import text

from app.core.security import hash_password
from app.db.models import Employee, User, LeaveType, LeaveBalance, Department, Designation
from app.schemas.employee import EmployeeCreate, EmployeeCreateWithAccount, EmployeeUpdate, ALLOWED_PROVISION_ROLES


def list_employees(db: Session, tenant_id: str | None = None) -> List[Employee]:
    stmt = select(Employee).order_by(Employee.full_name)
    if tenant_id:
        stmt = stmt.where(Employee.tenant_id == tenant_id)
    return db.scalars(stmt).all()


def search_employees(db: Session, page: int = 1, size: int = 20, q: str | None = None,
                     department_id: str | None = None, designation_id: str | None = None, tenant_id: str | None = None, is_super_admin: bool = False,
                     sort_by: str = 'full_name', sort_dir: str = 'asc', is_active: bool | None = None, manager_id: str | None = None) -> Tuple[List[Employee], int]:
    """Return (items, total) for employees matching optional filters with pagination."""
    stmt = select(Employee)
    filters = []
    
    if is_super_admin:
        stmt = stmt.join(User, User.id == Employee.id)
        filters.append(User.role.in_(['CEO', 'Admin']))
    elif tenant_id:
        filters.append(Employee.tenant_id == tenant_id)
        
    if q:
        like = f"%{q.lower()}%"
        filters.append(func.lower(Employee.full_name).like(like) | func.lower(Employee.email).like(like))
    if department_id:
        filters.append(Employee.department_id == department_id)
    if designation_id:
        filters.append(Employee.designation_id == designation_id)
    if is_active is not None:
        filters.append(Employee.is_active == is_active)
    if manager_id:
        filters.append(Employee.manager_id == manager_id)

    if filters:
        for f in filters:
            stmt = stmt.where(f)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))

    sort_column = {'full_name': Employee.full_name, 'email': Employee.email, 'is_active': Employee.is_active}.get(sort_by, Employee.full_name)
    order = sort_column.desc() if sort_dir == 'desc' else sort_column.asc()
    items = db.scalars(stmt.order_by(order, Employee.id).offset((page - 1) * size).limit(size)).all()
    return items, int(total or 0)


def get_employee(employee_id: str, db: Session, tenant_id: str | None = None) -> Employee:
    stmt = select(Employee).where(Employee.id == employee_id)
    if tenant_id:
        stmt = stmt.where(Employee.tenant_id == tenant_id)
    emp = db.scalar(stmt)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee not found')
    return emp


def _validate_manager_for_new_employee(db: Session, manager_id: str | None, new_id: str, tenant_id: str | None = None) -> None:
    if not manager_id:
        return
    mgr = db.scalar(select(Employee).where(Employee.id == manager_id))
    if not mgr:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Manager not found')
    if tenant_id and mgr.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail='Manager must belong to the same organization')

    current = manager_id
    seen: set[str] = set()
    while current:
        if current in seen:
            break
        seen.add(current)
        if current == new_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Manager assignment would create a cycle')
        current = db.scalar(select(Employee.manager_id).where(Employee.id == current))


def _employee_from_payload(payload: EmployeeCreate, employee_id: str, tenant_id: str | None = None) -> Employee:
    return Employee(
        id=employee_id,
        tenant_id=tenant_id,
        full_name=payload.full_name.strip(),
        email=payload.email.lower().strip(),
        phone=payload.phone,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        personal_email=payload.personal_email,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        zip_code=payload.zip_code,
        country=payload.country,
        emergency_contact_name=payload.emergency_contact_name,
        emergency_contact_phone=payload.emergency_contact_phone,
        emergency_contact_relationship=payload.emergency_contact_relationship,
        bank_account_number=payload.bank_account_number,
        bank_ifsc_code=payload.bank_ifsc_code,
        pan_number=payload.pan_number,
        aadhar_number=payload.aadhar_number,
        department_id=payload.department_id,
        designation_id=payload.designation_id,
        manager_id=payload.manager_id,
        joining_date=payload.joining_date,
        date_of_confirmation=payload.date_of_confirmation,
    )


def _validate_org_links(payload, db, tenant_id):
    if not tenant_id:
        return
    for field, model in (('department_id', Department), ('designation_id', Designation)):
        value = getattr(payload, field, None)
        if value:
            record = db.get(model, value)
            if not record or record.tenant_id != tenant_id:
                raise HTTPException(400, f'{field} must belong to the same organization')


def _provision_leave_balances(employee_id: str, db: Session) -> None:
    current_year = date.today().year
    leave_types = db.scalars(select(LeaveType).where(LeaveType.is_active.is_(True))).all()
    for leave_type in leave_types:
        existing = db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.leave_type_id == leave_type.id,
                LeaveBalance.year == current_year,
            )
        )
        if existing:
            continue
        granted = leave_type.default_days_per_year or 0
        db.add(
            LeaveBalance(
                employee_id=employee_id,
                leave_type_id=leave_type.id,
                year=current_year,
                granted_days=granted,
                balance_days=granted,
            )
        )


def _audit_employee_action(db: Session, actor_id: str | None, action: str, emp: Employee, extra: dict | None = None) -> None:
    try:
        from app.db.models import AuditLog

        data = {'full_name': emp.full_name, 'email': emp.email}
        if extra:
            data.update(extra)
        db.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                object_type='employee',
                object_id=emp.id,
                data=str(data),
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def create_employee(payload: EmployeeCreate, db: Session, actor_id: str | None = None, tenant_id: str | None = None) -> Employee:
    """Create employee with linked login (preferred for Admin/HR provisioning)."""
    if isinstance(payload, EmployeeCreateWithAccount):
        return create_employee_with_account(payload, db, actor_id, tenant_id=tenant_id)

    # Legacy path: employee record only (no login) — kept for backward compatibility in tests
    email = payload.email.lower().strip()
    existing = db.scalar(select(Employee).where(Employee.email == email))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Employee with this email exists')
    new_id = str(uuid4())
    _validate_manager_for_new_employee(db, payload.manager_id, new_id, tenant_id)
    _validate_org_links(payload, db, tenant_id)
    emp = _employee_from_payload(payload, new_id, tenant_id)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    _provision_leave_balances(emp.id, db)
    db.commit()
    _audit_employee_action(db, actor_id, 'create', emp)
    return emp


def create_employee_with_account(
    payload: EmployeeCreateWithAccount,
    db: Session,
    actor_id: str | None = None,
    tenant_id: str | None = None,
) -> Employee:
    email = payload.email.lower().strip()
    role = (payload.role or 'Employee').strip()

    if role not in ALLOWED_PROVISION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Invalid role. Allowed roles: {", ".join(ALLOWED_PROVISION_ROLES)}',
        )

    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='A login account with this email already exists')
    if db.scalar(select(Employee).where(Employee.email == email)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='An employee with this email already exists')

    new_id = str(uuid4())
    _validate_manager_for_new_employee(db, payload.manager_id, new_id, tenant_id)
    _validate_org_links(payload, db, tenant_id)

    user = User(
        id=new_id,
        tenant_id=tenant_id,
        full_name=payload.full_name.strip(),
        email=email,
        role=role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    emp = _employee_from_payload(payload, new_id, tenant_id)

    try:
        db.add(user)
        db.add(emp)
        db.commit()
        db.refresh(emp)
        _provision_leave_balances(emp.id, db)
        db.commit()
        _audit_employee_action(db, actor_id, 'create', emp, extra={'role': role, 'login_created': True})
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Unable to create employee account') from exc

    return emp


def update_employee(employee_id: str, payload: EmployeeUpdate, db: Session, actor_id: str | None = None, tenant_id: str | None = None) -> Employee:
    emp = get_employee(employee_id, db, tenant_id)
    linked_user = db.scalar(select(User).where((User.id == emp.id) | (User.email == emp.email)))
    if payload.full_name is not None:
        emp.full_name = payload.full_name
        if linked_user:
            linked_user.full_name = payload.full_name.strip()
    _validate_org_links(payload, db, tenant_id)
    if 'department_id' in payload.model_fields_set:
        emp.department_id = payload.department_id
    if 'designation_id' in payload.model_fields_set:
        emp.designation_id = payload.designation_id
    if 'manager_id' in payload.model_fields_set:
        # manager must exist
        if payload.manager_id == emp.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Manager assignment would create a cycle (self-manager not allowed)',
            )

        mgr = None
        if payload.manager_id:
            mgr = db.scalar(select(Employee).where(Employee.id == payload.manager_id))
            if not mgr:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Manager not found')
            if tenant_id and mgr.tenant_id != tenant_id:
                raise HTTPException(400, 'Manager must belong to the same organization')

        # detect cycles: walk up manager chain to ensure employee_id is not encountered
        current = payload.manager_id
        seen = set()
        while current:
            if current in seen:
                break
            seen.add(current)
            if current == emp.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Manager assignment would create a cycle')
            current = db.scalar(select(Employee.manager_id).where(Employee.id == current))

        emp.manager_id = payload.manager_id
    if payload.is_active is not None:
        if linked_user and linked_user.is_active != payload.is_active:
            from app.services.account_service import revoke_all
            revoke_all(linked_user,db)
        emp.is_active = payload.is_active
        if linked_user:
            linked_user.is_active = payload.is_active

    db.commit()
    db.refresh(emp)
    # audit
    try:
        from app.db.models import AuditLog
        db.add(AuditLog(actor_id=actor_id, action='update', object_type='employee', object_id=emp.id, data=str({'full_name': emp.full_name, 'email': emp.email})))
        db.commit()
    except Exception:
        db.rollback()
    return emp


def delete_employee(employee_id: str, db: Session, actor_id: str | None = None, tenant_id: str | None = None) -> Employee:
    emp = get_employee(employee_id, db, tenant_id)
    try:
        from app.db.models import (
            AuditLog, EmployeeShiftAssignment, Attendance, LeaveBalance, LeaveRequest,
            TodoItem, GatePass, Salary, EmployeeSalaryComponent, Payslip, SalaryHistory,
            Timesheet, OvertimeRequest, AttendanceRegularization, CompOffRequest, BiometricLog,
            RosterEntry, PerformanceAppraisal, Goal, KPI, EmployeeTraining, Certification,
            HelpdeskTicket, EmployeeGrievance, EmployeeDocument, OfferLetter, OnboardingPlan,
            ExitCase, AssetInventory, SalaryStructure, Reimbursement, EmployeeLoan,
            SurveyResponse, Feedback
        )

        # Delete all related records in correct order to respect foreign key constraints
        # Delete tables that reference this employee
        db.query(EmployeeShiftAssignment).filter(EmployeeShiftAssignment.employee_id == employee_id).delete()
        db.query(Attendance).filter(Attendance.employee_id == employee_id).delete()
        db.query(LeaveRequest).filter(LeaveRequest.employee_id == employee_id).delete()
        db.query(LeaveBalance).filter(LeaveBalance.employee_id == employee_id).delete()
        db.query(TodoItem).filter(TodoItem.employee_id == employee_id).delete()
        db.query(GatePass).filter(GatePass.employee_id == employee_id).delete()
        db.query(EmployeeSalaryComponent).filter(EmployeeSalaryComponent.employee_id == employee_id).delete()
        db.query(Payslip).filter(Payslip.employee_id == employee_id).delete()
        db.query(SalaryHistory).filter(SalaryHistory.employee_id == employee_id).delete()
        db.query(Salary).filter(Salary.employee_id == employee_id).delete()
        db.query(Timesheet).filter(Timesheet.employee_id == employee_id).delete()
        db.query(OvertimeRequest).filter(OvertimeRequest.employee_id == employee_id).delete()
        db.query(AttendanceRegularization).filter(AttendanceRegularization.employee_id == employee_id).delete()
        db.query(CompOffRequest).filter(CompOffRequest.employee_id == employee_id).delete()
        db.query(BiometricLog).filter(BiometricLog.employee_id == employee_id).delete()
        db.query(RosterEntry).filter(RosterEntry.employee_id == employee_id).delete()
        db.query(PerformanceAppraisal).filter(PerformanceAppraisal.employee_id == employee_id).delete()
        db.query(Goal).filter(Goal.employee_id == employee_id).delete()
        db.query(KPI).filter(KPI.employee_id == employee_id).delete()
        db.query(EmployeeTraining).filter(EmployeeTraining.employee_id == employee_id).delete()
        db.query(Certification).filter(Certification.employee_id == employee_id).delete()
        db.query(HelpdeskTicket).filter(HelpdeskTicket.employee_id == employee_id).delete()
        db.query(EmployeeDocument).filter(EmployeeDocument.employee_id == employee_id).delete()
        db.query(OfferLetter).filter(OfferLetter.employee_id == employee_id).delete()
        db.query(OnboardingPlan).filter(OnboardingPlan.employee_id == employee_id).delete()
        db.query(ExitCase).filter(ExitCase.employee_id == employee_id).delete()
        db.query(AssetInventory).filter(AssetInventory.employee_id == employee_id).delete()
        db.query(SalaryStructure).filter(SalaryStructure.employee_id == employee_id).delete()
        db.query(Reimbursement).filter(Reimbursement.employee_id == employee_id).delete()
        db.query(EmployeeLoan).filter(EmployeeLoan.employee_id == employee_id).delete()
        db.query(SurveyResponse).filter(SurveyResponse.employee_id == employee_id).delete()

        # Handle grievances where employee is involved
        db.query(EmployeeGrievance).filter(EmployeeGrievance.employee_id == employee_id).delete()
        db.query(EmployeeGrievance).filter(EmployeeGrievance.against_employee_id == employee_id).delete()

        # Handle feedback/appraisals where employee is reviewer
        db.query(Feedback).filter(Feedback.employee_id == employee_id).delete()
        db.query(Feedback).filter(Feedback.reviewer_id == employee_id).delete()
        db.query(PerformanceAppraisal).filter(PerformanceAppraisal.reviewer_id == employee_id).delete()

        # Handle grievances with investigator
        db.query(EmployeeGrievance).filter(EmployeeGrievance.investigator_id == employee_id).delete()

        # Update any employees who had this employee as their manager (set manager to NULL)
        db.query(Employee).filter(Employee.manager_id == employee_id).update({Employee.manager_id: None})

        # Record audit before delete
        db.add(AuditLog(actor_id=actor_id, action='delete', object_type='employee', object_id=emp.id, data=str({'full_name': emp.full_name, 'email': emp.email})))

        # Delete linked user account
        linked_user = db.scalar(select(User).where((User.id == emp.id) | (User.email == emp.email)))
        if linked_user:
            db.delete(linked_user)

        # Delete the employee
        db.delete(emp)
        db.commit()
    except Exception as e:
        db.rollback()
        raise
    return emp


def get_manager_chain(employee_id: str, db: Session, tenant_id: str | None = None) -> List[dict]:
    """Return manager chain for the given employee id as list of dicts (closest manager first)."""
    # get immediate manager
    stmt = select(Employee).where(Employee.id == employee_id)
    if tenant_id:
        stmt = stmt.where(Employee.tenant_id == tenant_id)
    emp = db.scalar(stmt)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Employee not found')

    start_mgr = emp.manager_id
    if not start_mgr:
        return []

    # Recursive CTE to walk manager chain upwards
    sql = text(
        "WITH RECURSIVE chain AS ("
        " SELECT id, full_name, email, manager_id FROM employees WHERE id = :start"
        " UNION ALL"
        " SELECT e.id, e.full_name, e.email, e.manager_id FROM employees e JOIN chain c ON e.id = c.manager_id"
        " ) SELECT id, full_name, email, manager_id FROM chain;"
    )

    result = db.execute(sql, {"start": start_mgr}).fetchall()
    # result is list of Row; convert to dicts
    chain = []
    for row in result:
        # skip the starter if it's empty? keep all starting from manager
        chain.append({"id": row[0], "full_name": row[1], "email": row[2], "manager_id": row[3]})
    return chain
