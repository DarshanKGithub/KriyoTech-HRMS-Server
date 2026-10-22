"""Services for Payroll Management (Phase 6)."""
from datetime import datetime, date
from calendar import monthrange
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.http import HTTPException, status

from app.db.models import (
    Salary, SalaryComponent, EmployeeSalaryComponent, Payslip,
    PayslipComponent, Employee, AuditLog, Attendance, SalaryHistory, User
)


def calculate_days_worked_from_attendance(employee_id: str, month: int, year: int, db: Session, tenant_id: str | None = None) -> tuple[int, int]:
    """Calculate days worked and days absent from attendance records for a given month/year.
    Returns (days_worked, days_absent)."""
    # Get all days in the month
    _, days_in_month = monthrange(year, month)
    
    # Query attendance records for the employee in the month
    query = db.query(Attendance).filter(
        Attendance.employee_id == employee_id,
        func.extract('year', Attendance.attendance_date) == year,
        func.extract('month', Attendance.attendance_date) == month,
    )
    if tenant_id:
        query = query.join(Employee, Attendance.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    attendances = query.all()
    
    # Count working days (assuming working days are Mon-Fri, excluding holidays)
    working_days = 0
    days_worked = 0
    days_absent = 0
    
    for day in range(1, days_in_month + 1):
        current_date = date(year, month, day)
        # Skip weekends (5=Saturday, 6=Sunday)
        if current_date.weekday() in [5, 6]:
            continue
        working_days += 1
        
        # Find attendance record for this day
        att = next((a for a in attendances if a.attendance_date == current_date), None)
        if att:
            if att.status in ['present', 'work-from-home']:
                if att.is_half_day:
                    days_worked += 0.5
                else:
                    days_worked += 1
            elif att.status == 'half-day':
                days_worked += 0.5
        else:
            # No attendance record = absent
            days_absent += 1
    
    return float(days_worked), float(days_absent)


def get_or_create_salary(employee_id: str, db: Session, tenant_id: str | None = None) -> Salary:
    """Get employee's current active salary record."""
    query = db.query(Salary).filter(
        Salary.employee_id == employee_id,
        Salary.is_active.is_(True)
    )
    if tenant_id:
        query = query.join(Employee, Salary.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    sal = query.first()
    if not sal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No active salary found for employee')
    return sal


def calculate_gross_salary(employee_id: str, db: Session, tenant_id: str | None = None) -> tuple[float, list]:
    """Calculate gross salary (base + all earnings) for an employee.
    Returns (gross_amount, list of earning components)."""
    salary = get_or_create_salary(employee_id, db, tenant_id)
    base = float(salary.base_salary)
    
    # Get all earnings components for employee
    query = db.query(EmployeeSalaryComponent).join(
        SalaryComponent, EmployeeSalaryComponent.salary_component_id == SalaryComponent.id
    ).filter(
        EmployeeSalaryComponent.employee_id == employee_id,
        SalaryComponent.component_type == 'earning'
    )
    if tenant_id:
        query = query.join(Employee, EmployeeSalaryComponent.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    earnings = query.all()
    
    earning_components = [{'name': 'Basic Salary', 'amount': base}]
    total_earnings = base
    
    for ecomp in earnings:
        comp = db.query(SalaryComponent).filter(SalaryComponent.id == ecomp.salary_component_id).first()
        if comp:
            earning_components.append({'name': comp.name, 'amount': float(ecomp.amount)})
            total_earnings += float(ecomp.amount)
    
    return total_earnings, earning_components


def calculate_deductions_and_tax(employee_id: str, gross_salary: float, db: Session, tenant_id: str | None = None) -> tuple[float, float, list, list]:
    """Calculate total deductions and tax.
    Returns (total_deductions, total_tax, deduction_components, tax_components)."""
    
    # Get deduction components
    d_query = db.query(EmployeeSalaryComponent).join(
        SalaryComponent, EmployeeSalaryComponent.salary_component_id == SalaryComponent.id
    ).filter(
        EmployeeSalaryComponent.employee_id == employee_id,
        SalaryComponent.component_type == 'deduction'
    )
    if tenant_id:
        d_query = d_query.join(Employee, EmployeeSalaryComponent.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    deductions = d_query.all()
    
    deduction_components = []
    total_deductions = 0.0
    for dcomp in deductions:
        comp = db.query(SalaryComponent).filter(SalaryComponent.id == dcomp.salary_component_id).first()
        if comp:
            deduction_components.append({'name': comp.name, 'amount': float(dcomp.amount)})
            total_deductions += float(dcomp.amount)
    
    # Get tax components
    t_query = db.query(EmployeeSalaryComponent).join(
        SalaryComponent, EmployeeSalaryComponent.salary_component_id == SalaryComponent.id
    ).filter(
        EmployeeSalaryComponent.employee_id == employee_id,
        SalaryComponent.component_type == 'tax'
    )
    if tenant_id:
        t_query = t_query.join(Employee, EmployeeSalaryComponent.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    taxes = t_query.all()
    
    tax_components = []
    total_tax = 0.0
    for tcomp in taxes:
        comp = db.query(SalaryComponent).filter(SalaryComponent.id == tcomp.salary_component_id).first()
        if comp:
            tax_components.append({'name': comp.name, 'amount': float(tcomp.amount)})
            total_tax += float(tcomp.amount)
    
    return total_deductions, total_tax, deduction_components, tax_components


def create_payslip(employee_id: str, month: int, year: int, days_worked=None, days_absent=None, db: Session = None, tenant_id: str | None = None) -> Payslip:
    from app.services.payroll_engine import monthly_payroll
    from sqlalchemy.exc import IntegrityError
    if db.scalar(select(Payslip.id).where(Payslip.employee_id==employee_id, Payslip.month==month, Payslip.year==year)):
        raise HTTPException(409, 'Payslip already exists for this month')
    calculation = monthly_payroll(employee_id, month, year, db, tenant_id)
    components = calculation.pop('components')
    payslip = Payslip(employee_id=employee_id, month=month, year=year, status='draft', **calculation)
    try:
        db.add(payslip); db.flush()
        for component in components:
            db.add(PayslipComponent(payslip_id=payslip.id, salary_component_id=None, **component))
        db.add(AuditLog(actor_id=db.info['actor'].id if db.info.get('actor') else None, action='create', object_type='payslip', object_id=payslip.id, data=str({'month':month,'year':year})))
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, 'Payslip period already exists or salary data conflicts') from error
    return payslip


def get_payslip(payslip_id: str, db: Session, tenant_id: str | None = None, lock: bool = False) -> Payslip:
    """Fetch a payslip by ID."""
    query = db.query(Payslip)
    if tenant_id:
        query = query.join(Employee, Payslip.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update(of=Payslip)
    ps = query.filter(Payslip.id == payslip_id).populate_existing().first()
    if not ps:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Payslip not found')
    return ps


def list_payslips(db: Session, tenant_id: str | None = None, employee_id: str | None = None, month: int | None = None, 
                  year: int | None = None, page: int = 1, size: int = 20):
    """List payslips with optional filters."""
    query = db.query(Payslip)
    
    if tenant_id:
        query = query.join(Employee, Payslip.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    
    if employee_id:
        query = query.filter(Payslip.employee_id == employee_id)
    if month:
        query = query.filter(Payslip.month == month)
    if year:
        query = query.filter(Payslip.year == year)
    
    total = query.with_entities(func.count(Payslip.id)).scalar() or 0
    items = query.order_by(Payslip.created_at.desc()).offset((page - 1) * size).limit(size).all()
    
    return items, int(total)


def approve_payslip(payslip_id: str, approver_id: str, db: Session, tenant_id: str | None = None) -> Payslip:
    """Approve a payslip (transition from draft to approved)."""
    ps = get_payslip(payslip_id, db, tenant_id, lock=True)
    
    if ps.status != 'draft':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Payslip is not in draft status')
    
    ps.status = 'approved'
    ps.processed_by = approver_id
    ps.processed_at = datetime.now()
    ps.updated_at = datetime.now()
    
    db.add(ps)
    db.commit()
    db.refresh(ps)
    
    # Audit
    try:
        db.add(AuditLog(
            actor_id=approver_id,
            action='approve',
            object_type='payslip',
            object_id=ps.id,
            data=str({'status': 'approved'})
        ))
        db.commit()
    except Exception:
        db.rollback()
    
    return ps


def mark_payslip_paid(payslip_id: str, processor_id: str, db: Session, tenant_id: str | None = None) -> Payslip:
    """Mark payslip as paid (transition from approved to paid)."""
    ps = get_payslip(payslip_id, db, tenant_id, lock=True)
    
    if ps.status != 'approved':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Payslip must be approved before marking as paid')
    
    ps.status = 'paid'
    ps.updated_at = datetime.now()
    
    db.add(ps)
    db.commit()
    db.refresh(ps)
    
    # Audit
    try:
        db.add(AuditLog(
            actor_id=processor_id,
            action='mark_paid',
            object_type='payslip',
            object_id=ps.id,
            data=str({'status': 'paid'})
        ))
        db.commit()
    except Exception:
        db.rollback()
    
    return ps


def get_payslip_details(payslip_id: str, db: Session, tenant_id: str | None = None) -> dict:
    """Get full payslip details including components for PDF/email."""
    ps = get_payslip(payslip_id, db, tenant_id)
    
    # Get employee info
    emp = db.query(Employee).filter(Employee.id == ps.employee_id).first()
    
    # Get components
    components = db.query(PayslipComponent).filter(PayslipComponent.payslip_id == ps.id).all()
    components_list = [
        {
            'component_name': c.component_name,
            'component_type': c.component_type,
            'amount': float(c.amount)
        }
        for c in components
    ]
    
    return {
        'id': ps.id,
        'employee_id': ps.employee_id,
        'employee_name': emp.full_name if emp else 'Unknown',
        'employee_email': emp.email if emp else None,
        'month': ps.month,
        'year': ps.year,
        'base_salary': float(ps.base_salary),
        'gross_salary': float(ps.gross_salary),
        'total_deductions': float(ps.total_deductions),
        'total_tax': float(ps.total_tax),
        'net_salary': float(ps.net_salary),
        'days_worked': ps.days_worked,
        'days_absent': ps.days_absent,
        'status': ps.status,
        'components': components_list,
        'processed_at': ps.processed_at,
        'created_at': ps.created_at,
    }


def send_payslip_email(payslip_id: str, db: Session, tenant_id: str | None = None) -> bool:
    """Generate and send payslip PDF via email."""
    from app.core.payroll_utils import send_email, generate_payslip_pdf_bytes, generate_payslip_html
    
    payslip_data = get_payslip_details(payslip_id, db, tenant_id)
    
    if not payslip_data['employee_email']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Employee email not found')
    
    month_names = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    month_name = month_names[payslip_data['month'] - 1]
    
    subject = f"Payslip - {month_name} {payslip_data['year']}"
    
    # Generate HTML body for email
    html_body = generate_payslip_html(payslip_data)
    
    # Try to generate PDF
    pdf_bytes = generate_payslip_pdf_bytes(payslip_data)
    
    # Save PDF temporarily if generated
    pdf_path = None
    if pdf_bytes and not isinstance(pdf_bytes, str):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as f:
            f.write(pdf_bytes)
            pdf_path = f.name
    
    # Send email
    success = send_email(
        to_email=payslip_data['employee_email'],
        subject=subject,
        body=html_body,
        attachment_path=pdf_path,
        attachment_name=f"Payslip_{month_name}_{payslip_data['year']}.pdf"
    )
    
    # Clean up temp file
    if pdf_path:
        import os
        try:
            os.remove(pdf_path)
        except:
            pass
    
    return success


def run_batch_payroll(month: int, year: int, db: Session, tenant_id: str | None = None) -> dict:
    """Generate payslips for all active employees for a given month/year.
    Returns summary of processing results."""
    
    # Get all active employees
    query = db.query(Employee).filter(Employee.is_active.is_(True))
    if tenant_id:
        query = query.filter(Employee.tenant_id == tenant_id)
    employees = query.all()
    
    if not employees:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No active employees found')
    
    results = {
        'total_employees': len(employees),
        'successful': 0,
        'failed': 0,
        'already_exists': 0,
        'errors': []
    }
    
    for emp in employees:
        try:
            # Check if payslip already exists
            existing = db.query(Payslip).filter(
                Payslip.employee_id == emp.id,
                Payslip.month == month,
                Payslip.year == year
            ).first()
            
            if existing:
                results['already_exists'] += 1
                continue
            
            # Create payslip for this employee
            ps = create_payslip(
                employee_id=emp.id,
                month=month,
                year=year,
                db=db,
                tenant_id=tenant_id
            )
            results['successful'] += 1
            
        except Exception as e:
            db.rollback()
            results['failed'] += 1
            results['errors'].append({
                'employee_id': emp.id,
                'employee_name': emp.full_name,
                'error': str(e)
            })
    
    # Log the batch run
    try:
        db.add(AuditLog(
            actor_id=None,
            action='batch_payroll_run',
            object_type='payroll_batch',
            object_id=f'{month}_{year}',
            data=str({
                'month': month,
                'year': year,
                'successful': results['successful'],
                'failed': results['failed'],
                'already_exists': results['already_exists']
            })
        ))
        db.commit()
    except Exception:
        db.rollback()
    
    return results


def create_salary_history_entry(employee_id: str, base_salary: float, grade: str | None, 
                                effective_from: date, reason: str | None, modified_by_id: str, 
                                salary_id: str | None = None, db: Session = None) -> SalaryHistory:
    """Create a salary history entry for audit trail."""
    history = SalaryHistory(
        employee_id=employee_id,
        salary_id=salary_id,
        base_salary=base_salary,
        grade=grade,
        currency='INR',
        effective_from=effective_from,
        reason_for_change=reason,
        modified_by=modified_by_id,
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history


def get_salary_history(employee_id: str, db: Session, page: int = 1, size: int = 10, tenant_id: str | None = None) -> dict:
    """Get salary history for an employee with pagination."""
    query = db.query(SalaryHistory).filter(SalaryHistory.employee_id == employee_id)
    if tenant_id:
        query = query.join(Employee, SalaryHistory.employee_id == Employee.id).filter(Employee.tenant_id == tenant_id)
    query = query.order_by(SalaryHistory.effective_from.desc())
    
    total = query.count()
    skip = (page - 1) * size
    items = query.offset(skip).limit(size).all()
    
    return {
        'items': [
            {
                'id': h.id,
                'base_salary': float(h.base_salary),
                'grade': h.grade,
                'currency': h.currency,
                'effective_from': h.effective_from,
                'effective_to': h.effective_to,
                'reason_for_change': h.reason_for_change,
                'modified_by': h.modified_by_user.email if h.modified_by_user else None,
                'created_at': h.created_at,
            }
            for h in items
        ],
        'total': total,
        'page': page,
        'size': size,
    }


def update_salary(employee_id: str, new_base_salary: float, grade: str | None, effective_from: date, reason: str | None, modified_by_id: str, db: Session, tenant_id: str | None = None) -> Salary:
    from datetime import timedelta
    from app.services.payroll_engine import money
    employee = db.scalar(select(Employee).where(Employee.id==employee_id))
    if not employee or tenant_id and employee.tenant_id!=tenant_id:
        raise HTTPException(404, 'Employee not found')
    current = db.scalar(select(Salary).where(Salary.employee_id==employee_id,Salary.is_active.is_(True)).with_for_update())
    if current and effective_from < current.effective_from:
        raise HTTPException(400, 'A salary revision cannot precede the active salary')
    try:
        if current and current.effective_from==effective_from:
            current.base_salary=money(new_base_salary); current.grade=grade
            new=current
        else:
            if current:
                current.is_active=False; current.effective_to=effective_from-timedelta(days=1)
                db.flush()
            new=Salary(employee_id=employee_id,base_salary=money(new_base_salary),grade=grade,currency='INR',effective_from=effective_from,is_active=True)
            db.add(new); db.flush()
        db.add(SalaryHistory(employee_id=employee_id,salary_id=new.id,base_salary=money(new_base_salary),grade=grade,currency='INR',effective_from=effective_from,reason_for_change=reason,modified_by=modified_by_id))
        db.add(AuditLog(actor_id=modified_by_id,action='update_salary',object_type='salary',object_id=new.id,data=str({'effective_from':str(effective_from)})))
        db.commit()
        return new
    except Exception:
        db.rollback()
        raise
