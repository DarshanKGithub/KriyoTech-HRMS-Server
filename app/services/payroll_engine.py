"""Decimal monthly payroll using company workweek, holidays, leave and salary dates."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from app.db.models import Employee, Salary, SalaryStructure, SalaryComponent, EmployeeSalaryComponent, Attendance, Holiday, LeaveRequest, LeaveType
from app.core.business_time import working_days, business_today
from app.http import HTTPException

def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def monthly_payroll(employee_id, month, year, db, tenant_id=None):
    if not 1 <= month <= 12 or not 2000 <= year <= 2200:
        raise HTTPException(422, 'Invalid payroll period')
    start, end = date(year,month,1), date(year,month,monthrange(year,month)[1])
    if end >= business_today(db,tenant_id):
        raise HTTPException(400, 'Payroll generation requires a completed calendar month')
    employee = db.scalar(select(Employee).where(Employee.id == employee_id))
    if not employee or tenant_id and employee.tenant_id != tenant_id:
        raise HTTPException(404, 'Employee not found')
    salaries = db.scalars(select(Salary).where(Salary.employee_id == employee_id, Salary.effective_from <= end, (Salary.effective_to.is_(None) | (Salary.effective_to >= start))).order_by(Salary.effective_from.desc())).all()
    if not salaries:
        raise HTTPException(400, 'Configure salary effective within this payroll period first')
    holidays = set(db.scalars(select(Holiday.holiday_date).where(Holiday.tenant_id == tenant_id, Holiday.holiday_date >= start, Holiday.holiday_date <= end)))
    workdays = [start+timedelta(days=i) for i in range((end-start).days+1) if (start+timedelta(days=i)).weekday() in working_days(db,tenant_id) and start+timedelta(days=i) not in holidays]
    if not workdays:
        raise HTTPException(400, 'This period has no configured working days')
    attendance = {item.attendance_date:item for item in db.scalars(select(Attendance).where(Attendance.employee_id == employee_id, Attendance.attendance_date >= start, Attendance.attendance_date <= end))}
    leaves = db.execute(select(LeaveRequest,LeaveType.is_paid).join(LeaveType,LeaveType.id==LeaveRequest.leave_type_id).where(LeaveRequest.employee_id==employee_id,LeaveRequest.status=='approved',LeaveRequest.start_date<=end,LeaveRequest.end_date>=start)).all()
    attended=Decimal(0); paid=Decimal(0); eligible=Decimal(0); basic=Decimal(0)
    for day in workdays:
        salary=next((item for item in salaries if item.effective_from<=day and (item.effective_to is None or item.effective_to>=day)),None)
        if not salary or employee.joining_date and day<employee.joining_date:
            continue
        eligible+=1
        record=attendance.get(day)
        worked=Decimal('.5') if record and (record.is_half_day or record.status=='half-day') else Decimal(1) if record and record.status in {'present','work-from-home','late'} else Decimal(0)
        leave_credit=Decimal(0)
        for leave,is_paid in leaves:
            if is_paid and leave.start_date<=day<=leave.end_date:
                credit=Decimal(1)
                if day==leave.start_date and leave.session_from=='Session 2': credit-=Decimal('.5')
                if day==leave.end_date and leave.session_to=='Session 1': credit-=Decimal('.5')
                leave_credit+=credit
        credit=min(Decimal(1),worked+leave_credit)
        attended+=worked; paid+=credit
        basic+=money(salary.base_salary)*credit/Decimal(len(workdays))
    factor=paid/Decimal(len(workdays))
    components=[{'component_name':'Basic salary','component_type':'earning','amount':money(basic)}]
    structure=db.scalar(select(SalaryStructure).where(SalaryStructure.employee_id==employee_id))
    if structure:
        for label,field in [('House rent allowance','hra'),('Dearness allowance','da'),('Special allowance','special_allowance')]:
            components.append({'component_name':label,'component_type':'earning','amount':money(money(getattr(structure,field))*factor)})
    else:
        for item,component in db.execute(select(EmployeeSalaryComponent,SalaryComponent).join(SalaryComponent,SalaryComponent.id==EmployeeSalaryComponent.salary_component_id).where(EmployeeSalaryComponent.employee_id==employee_id)):
            components.append({'component_name':component.name,'component_type':component.component_type,'amount':money(money(item.amount)*factor)})
    gross=sum((item['amount'] for item in components if item['component_type']=='earning'),Decimal(0))
    if structure:
        for label,base,percentage,kind in [('Provident fund',money(basic),structure.pf_percentage,'deduction'),('Employee insurance',gross,structure.esi_percentage,'deduction'),('Configured tax',gross,structure.tax_bracket_percentage,'tax')]:
            components.append({'component_name':label,'component_type':kind,'amount':money(base*money(percentage)/100)})
    deductions=sum((item['amount'] for item in components if item['component_type']=='deduction'),Decimal(0))
    tax=sum((item['amount'] for item in components if item['component_type']=='tax'),Decimal(0))
    if gross-deductions-tax<0:
        raise HTTPException(400, 'Deductions exceed gross earnings; review salary setup')
    return {'base_salary':money(salaries[0].base_salary),'gross_salary':money(gross),'total_deductions':money(deductions),'total_tax':money(tax),'net_salary':money(gross-deductions-tax),'days_worked':attended,'days_absent':max(Decimal(0),eligible-paid),'components':components}
