"""Role-scoped dashboard data. Missing data is never synthesized as a metric."""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rbac import has_permission
from app.http import HTTPException
from app.db.models import (
    User, Employee, Tenant, Subscription, Plan, Department, Attendance,
    LeaveRequest, LeaveBalance, LeaveType, TodoItem, Holiday, Payslip,
)
from app.services.auth_service import resolve_employee_id


def workspace_dashboard(user: User, db: Session) -> dict:
    from app.core.business_time import business_today, tenant_zone
    today = business_today(db, user.tenant_id)
    timezone_name = str(tenant_zone(db, user.tenant_id))
    result = {
        'scope': 'personal', 'as_of': today.isoformat(), 'timezone': timezone_name,
        'metrics': [], 'departments': [], 'pending_leaves': [], 'tasks': [],
        'holidays': [], 'attendance': None, 'leave_balances': [], 'latest_payslip': None,
        'employee_linked': False,
    }

    def metric(key, label, statement, description):
        result['metrics'].append({'key': key, 'label': label, 'value': int(db.scalar(statement) or 0), 'description': description})

    if user.role == 'Super Admin':
        result['scope'] = 'platform'
        metric('clients', 'Client organizations', select(func.count(Tenant.id)), 'All client organizations')
        metric('active_clients', 'Active clients', select(func.count(Tenant.id)).where(Tenant.is_active.is_(True)), 'Organizations enabled on the platform')
        metric('subscriptions', 'Active subscriptions', select(func.count(Subscription.id)).where(Subscription.status == 'active'), 'Subscriptions marked active by the server')
        metric('plans', 'Subscription plans', select(func.count(Plan.id)), 'Configured billing plans')
        return result

    if not user.tenant_id:
        raise HTTPException(403, 'Your account is not assigned to an organization. Contact your administrator.')
    employee_id = resolve_employee_id(user, db)
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee and employee.tenant_id != user.tenant_id:
        employee = None
        employee_id = None
    result['employee_linked'] = employee is not None

    organization_role = user.role in ('Admin', 'HR', 'CEO')
    manager = user.role == 'Manager'
    if organization_role or manager:
        result['scope'] = 'organization' if organization_role else 'team'
        employee_query = select(Employee.id).where(Employee.tenant_id == user.tenant_id)
        if manager:
            if not employee_id:
                raise HTTPException(403, 'A linked employee record is required to identify your direct reports.')
            employee_query = employee_query.where(Employee.manager_id == employee_id)
        metric('employees', 'Employees' if organization_role else 'Direct reports', select(func.count()).select_from(employee_query.subquery()), 'Organization headcount' if organization_role else 'Employees reporting directly to you')
        metric('present', 'Checked in today', select(func.count(Attendance.id)).where(Attendance.employee_id.in_(employee_query), Attendance.attendance_date == today, Attendance.check_in_time.is_not(None)), f'Recorded check-ins on {today.isoformat()}')
        metric('on_leave', 'On approved leave', select(func.count(func.distinct(LeaveRequest.employee_id))).where(LeaveRequest.employee_id.in_(employee_query), LeaveRequest.status == 'approved', LeaveRequest.start_date <= today, LeaveRequest.end_date >= today), 'Approved leave covering today')
        metric('pending_leaves', 'Leave approvals', select(func.count(LeaveRequest.id)).where(LeaveRequest.employee_id.in_(employee_query), LeaveRequest.status.in_(['pending', 'pending_manager', 'pending_hr'])), 'Requests awaiting a decision')
        rows = db.execute(select(Department.name, func.count(Employee.id)).join(Employee, Employee.department_id == Department.id).where(Employee.id.in_(employee_query)).group_by(Department.id, Department.name)).all()
        result['departments'] = [{'name': name, 'count': count} for name, count in rows]
        if has_permission(user.role, 'approve_leave'):
            leaves = db.execute(select(LeaveRequest, Employee.full_name, LeaveType.name).join(Employee, LeaveRequest.employee_id == Employee.id).join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id).where(LeaveRequest.employee_id.in_(employee_query), LeaveRequest.status.in_(['pending', 'pending_manager', 'pending_hr'])).order_by(LeaveRequest.start_date).limit(6)).all()
            result['pending_leaves'] = [{'id': leave.id, 'employee_name': name, 'leave_type': kind, 'start_date': leave.start_date.isoformat(), 'end_date': leave.end_date.isoformat(), 'status': leave.status} for leave, name, kind in leaves]

    result['holidays'] = [{'id': item.id, 'name': item.name, 'date': item.holiday_date.isoformat()} for item in db.scalars(select(Holiday).where(Holiday.tenant_id == user.tenant_id, Holiday.holiday_date >= today).order_by(Holiday.holiday_date).limit(4))]
    if not employee_id:
        return result
    attendance = db.scalar(select(Attendance).where(Attendance.employee_id == employee_id, Attendance.attendance_date == today))
    if attendance:
        result['attendance'] = {'id': attendance.id, 'status': attendance.status, 'check_in_time': attendance.check_in_time.isoformat() if attendance.check_in_time else None, 'check_out_time': attendance.check_out_time.isoformat() if attendance.check_out_time else None}
    balances = db.execute(select(LeaveBalance, LeaveType.name).join(LeaveType, LeaveBalance.leave_type_id == LeaveType.id).where(LeaveBalance.employee_id == employee_id, LeaveBalance.year == today.year, LeaveType.tenant_id == user.tenant_id)).all()
    result['leave_balances'] = [{'name': name, 'days': float(balance.balance_days)} for balance, name in balances]
    tasks = db.scalars(select(TodoItem).where(TodoItem.employee_id == employee_id, TodoItem.status != 'done').order_by(TodoItem.due_date.asc().nullslast()).limit(5)).all()
    result['tasks'] = [{'id': task.id, 'title': task.title, 'status': task.status, 'due_date': task.due_date.isoformat() if task.due_date else None} for task in tasks]
    if not organization_role and not manager:
        result['metrics'] = [
            {'key': 'hours', 'label': 'Today’s attendance', 'value': 'Checked out' if attendance and attendance.check_out_time else 'Checked in' if attendance and attendance.check_in_time else 'Not checked in', 'description': f'{today.isoformat()} · {timezone_name}'},
            {'key': 'balance', 'label': 'Available leave days', 'value': sum(item['days'] for item in result['leave_balances']) if balances else None, 'description': 'Current year balances recorded by HR'},
            {'key': 'requests', 'label': 'Pending leave requests', 'value': int(db.scalar(select(func.count(LeaveRequest.id)).where(LeaveRequest.employee_id == employee_id, LeaveRequest.status.in_(['pending', 'pending_manager', 'pending_hr']))) or 0), 'description': 'Your requests awaiting a decision'},
            {'key': 'tasks', 'label': 'Open tasks', 'value': int(db.scalar(select(func.count(TodoItem.id)).where(TodoItem.employee_id == employee_id, TodoItem.status != 'done')) or 0), 'description': 'Your assigned checklist items'},
        ]
    if has_permission(user.role, 'view_payslip_own') or has_permission(user.role, 'view_payroll'):
        payslip = db.scalar(select(Payslip).where(Payslip.employee_id == employee_id, Payslip.status.in_(['approved', 'paid'])).order_by(Payslip.year.desc(), Payslip.month.desc()).limit(1))
        if payslip:
            result['latest_payslip'] = {'id': payslip.id, 'month': payslip.month, 'year': payslip.year, 'net_salary': float(payslip.net_salary), 'status': payslip.status}
    return result
