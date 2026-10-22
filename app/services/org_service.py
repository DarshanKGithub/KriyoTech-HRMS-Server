from typing import List
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Department, Designation
from app.schemas.organization import DepartmentCreate, DesignationCreate
from app.http import HTTPException, status


def list_departments(db: Session, tenant_id=None, scoped=False) -> List[Department]:
    query = select(Department)
    if scoped:
        query = query.where(Department.tenant_id == tenant_id)
    return db.scalars(query.order_by(Department.name)).all()


def create_department(payload: DepartmentCreate, db: Session, tenant_id=None) -> Department:
    existing = db.scalar(select(Department).where(Department.name == payload.name))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Department already exists')
    dept = Department(name=payload.name, tenant_id=tenant_id)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


def list_designations(db: Session, tenant_id=None, scoped=False) -> List[Designation]:
    query = select(Designation)
    if scoped:
        query = query.where(Designation.tenant_id == tenant_id)
    return db.scalars(query.order_by(Designation.name)).all()


def create_designation(payload: DesignationCreate, db: Session, tenant_id=None) -> Designation:
    existing = db.scalar(select(Designation).where(Designation.name == payload.name))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Designation already exists')
    des = Designation(name=payload.name, tenant_id=tenant_id)
    db.add(des)
    db.commit()
    db.refresh(des)
    return des


def get_org_hierarchy(db: Session, tenant_id=None, scoped=False) -> List[dict]:
    from app.db.models import Employee
    query = db.query(Employee, Department, Designation)\
        .outerjoin(Department, Employee.department_id == Department.id)\
        .outerjoin(Designation, Employee.designation_id == Designation.id)\
        .filter(Employee.is_active == True)
    if scoped:
        query = query.filter(Employee.tenant_id == tenant_id)
    employees = query.all()

    nodes = {}
    for emp, dept, desig in employees:
        nodes[emp.id] = {
            "id": emp.id,
            "full_name": emp.full_name,
            "designation": desig.name if desig else None,
            "department": dept.name if dept else None,
            "manager_id": emp.manager_id,
            "children": []
        }

    hierarchy = []
    for emp_id, node in nodes.items():
        mgr_id = node['manager_id']
        if mgr_id and mgr_id in nodes:
            nodes[mgr_id]['children'].append(node)
        else:
            hierarchy.append(node)
            
    return hierarchy
