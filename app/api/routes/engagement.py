from app.services.auth_service import resolve_employee_id
from app.http import Router, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.core.rbac import get_current_user, has_permission, require_permissions
from app.db.database import get_db
from app.db.models import User
from app.schemas.engagement import (
    HelpdeskTicketCreate,
    HelpdeskTicketPublic,
    PaginatedHelpdeskTickets,
    AnnouncementCreate,
    AnnouncementPublic,
    PaginatedAnnouncements
)
from app.schemas.grievance import (
    EmployeeGrievanceCreate,
    EmployeeGrievancePublic,
    PaginatedEmployeeGrievances,
    EmployeeGrievanceStatusUpdate,
    GrievanceInvestigationUpdate
)
from app.services.engagement_service import (
    create_ticket,
    get_tickets,
    update_ticket_status,
    create_announcement,
    get_announcements
)
from app.services.grievance_service import (
    create_grievance,
    get_grievances,
    get_all_grievances,
    get_grievance,
    update_grievance_status,
    investigate_grievance
)

router = Router()

# --- Gate Pass Routes ---
from app.schemas.engagement import GatePassCreate, GatePassPublic, PaginatedGatePasses, GatePassStatusUpdate
from app.services.engagement_service import create_gatepass, list_gatepasses, update_gatepass_status


@router.post('/gatepasses', response_model=GatePassPublic)
def submit_gatepass(
    payload: GatePassCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.employee_id != resolve_employee_id(user,db) and not has_permission(user.role, 'manage_gatepasses'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot create gate pass for others')

    gp = create_gatepass(payload, db)
    return GatePassPublic.model_validate(gp, from_attributes=True)


@router.get('/gatepasses', response_model=PaginatedGatePasses)
def list_gatepass_endpoint(
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if employee_id and employee_id != resolve_employee_id(user,db) and not has_permission(user.role, 'manage_gatepasses'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view other employee gate passes')

    if not employee_id and not has_permission(user.role, 'manage_gatepasses'):
        employee_id = resolve_employee_id(user,db)

    items, total = list_gatepasses(db, employee_id=employee_id, status=status, page=page, size=size)
    return PaginatedGatePasses(items=[GatePassPublic.model_validate(i, from_attributes=True) for i in items], total=total, page=page, size=size)


@router.put('/gatepasses/{gp_id}/status', response_model=GatePassPublic)
def update_gatepass_status_endpoint(
    gp_id: str,
    payload: GatePassStatusUpdate,
    user: User = Depends(require_permissions('manage_gatepasses')),
    db: Session = Depends(get_db),
):
    gp = update_gatepass_status(gp_id, payload.status, user.id, payload.comments, db)
    return GatePassPublic.model_validate(gp, from_attributes=True)


# --- Helpdesk Routes ---

@router.post('/tickets', response_model=HelpdeskTicketPublic)
def submit_ticket(
    payload: HelpdeskTicketCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if payload.employee_id != resolve_employee_id(user,db) and not has_permission(user.role, 'manage_helpdesk'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create tickets for others")
    
    return HelpdeskTicketPublic.model_validate(create_ticket(payload, db))

@router.get('/tickets', response_model=PaginatedHelpdeskTickets)
def list_tickets(
    employee_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if employee_id and employee_id != resolve_employee_id(user,db) and not has_permission(user.role, 'manage_helpdesk'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view other's tickets")

    if not employee_id and not has_permission(user.role, 'manage_helpdesk'):
        employee_id = resolve_employee_id(user,db)

    items, total = get_tickets(db, employee_id, category, page, size)
    return PaginatedHelpdeskTickets(
        items=[HelpdeskTicketPublic.model_validate(i, from_attributes=True) for i in items],
        total=total,
        page=page,
        size=size
    )

class TicketStatusUpdate(BaseModel):
    status: str

@router.put('/tickets/{ticket_id}/status', response_model=HelpdeskTicketPublic)
def change_ticket_status(
    ticket_id: str,
    payload: TicketStatusUpdate,
    user: User = Depends(require_permissions('manage_helpdesk')),
    db: Session = Depends(get_db)
):
    return HelpdeskTicketPublic.model_validate(update_ticket_status(ticket_id, payload.status, user.id, db))


# --- Announcement Routes ---

class AnnouncementRequest(BaseModel):
    title: str
    content: str
    priority: Optional[str] = 'Normal'

@router.post('/announcements', response_model=AnnouncementPublic)
def post_announcement(
    payload: AnnouncementRequest,
    user: User = Depends(require_permissions('manage_announcements')),
    db: Session = Depends(get_db)
):
    ann_create = AnnouncementCreate(
        title=payload.title,
        content=payload.content,
        priority=payload.priority,
        author_id=user.id
    )
    return AnnouncementPublic.model_validate(create_announcement(ann_create, db))

@router.get('/announcements', response_model=PaginatedAnnouncements)
def list_active_announcements(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    items, total = get_announcements(db, page, size)
    return PaginatedAnnouncements(
        items=[AnnouncementPublic.model_validate(i, from_attributes=True) for i in items],
        total=total,
        page=page,
        size=size
    )


# --- Grievance Routes ---

@router.post('/grievances', response_model=EmployeeGrievancePublic)
def file_grievance(
    payload: EmployeeGrievanceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """File a new employee grievance"""
    grievance = create_grievance(payload, resolve_employee_id(user,db), db)
    return EmployeeGrievancePublic.model_validate(grievance, from_attributes=True)


@router.get('/grievances', response_model=PaginatedEmployeeGrievances)
def list_grievances(
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List grievances (own or all if admin)"""
    if has_permission(user.role, 'manage_grievances'):
        # Admin/HR can view all grievances
        items, total = get_all_grievances(db, status_filter=status, page=page, size=size)
    else:
        # Employees can only see their own grievances
        items, total = get_grievances(
            db,
            employee_id=resolve_employee_id(user,db),
            status_filter=status,
            page=page,
            size=size
        )
    
    return PaginatedEmployeeGrievances(
        items=[EmployeeGrievancePublic.model_validate(i, from_attributes=True) for i in items],
        total=total,
        page=page,
        size=size
    )


@router.get('/grievances/{grievance_id}', response_model=EmployeeGrievancePublic)
def get_grievance_detail(
    grievance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get grievance details"""
    grievance = get_grievance(db, grievance_id)
    if not grievance:
        raise HTTPException(status_code=404, detail='Grievance not found')
    
    # Check permission
    if grievance.employee_id != resolve_employee_id(user,db) and not has_permission(user.role, 'manage_grievances'):
        raise HTTPException(status_code=403, detail='Cannot access this grievance')
    
    return EmployeeGrievancePublic.model_validate(grievance, from_attributes=True)


@router.put('/grievances/{grievance_id}/status', response_model=EmployeeGrievancePublic)
def update_grievance_status_endpoint(
    grievance_id: str,
    payload: EmployeeGrievanceStatusUpdate,
    user: User = Depends(require_permissions('manage_grievances')),
    db: Session = Depends(get_db)
):
    """Update grievance status (admin only)"""
    grievance = update_grievance_status(grievance_id, payload, db)
    if not grievance:
        raise HTTPException(status_code=404, detail='Grievance not found')
    
    return EmployeeGrievancePublic.model_validate(grievance, from_attributes=True)


@router.put('/grievances/{grievance_id}/investigate', response_model=EmployeeGrievancePublic)
def investigate_grievance_endpoint(
    grievance_id: str,
    payload: GrievanceInvestigationUpdate,
    user: User = Depends(require_permissions('manage_grievances')),
    db: Session = Depends(get_db)
):
    """Update grievance investigation (admin only)"""
    grievance = investigate_grievance(grievance_id, payload, db)
    if not grievance:
        raise HTTPException(status_code=404, detail='Grievance not found')
    
    return EmployeeGrievancePublic.model_validate(grievance, from_attributes=True)
