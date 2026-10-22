from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Tuple, List, Optional
from app.http import HTTPException, status
from datetime import datetime, timezone

from app.db.models import HelpdeskTicket, Announcement, GatePass, Employee
from app.schemas.engagement import HelpdeskTicketCreate, AnnouncementCreate, GatePassCreate
from app.services.notification_service import NotificationService

def create_ticket(payload: HelpdeskTicketCreate, db: Session) -> HelpdeskTicket:
    ticket = HelpdeskTicket(**payload.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket

def get_tickets(
    db: Session,
    employee_id: Optional[str] = None,
    category: Optional[str] = None,
    page: int = 1,
    size: int = 20
) -> Tuple[List[HelpdeskTicket], int]:
    query = db.query(HelpdeskTicket)
    if employee_id:
        query = query.filter(HelpdeskTicket.employee_id == employee_id)
    if category:
        query = query.filter(HelpdeskTicket.category == category)
    
    total = query.count()
    items = query.order_by(desc(HelpdeskTicket.created_at)).offset((page - 1) * size).limit(size).all()
    return items, total

def update_ticket_status(ticket_id: str, new_status: str, assigned_to: str, db: Session) -> HelpdeskTicket:
    ticket = db.query(HelpdeskTicket).filter(HelpdeskTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    
    ticket.status = new_status
    if assigned_to:
        ticket.assigned_to = assigned_to
        
    db.commit()
    db.refresh(ticket)
    return ticket

def create_announcement(payload: AnnouncementCreate, db: Session) -> Announcement:
    ann = Announcement(**payload.model_dump())
    db.add(ann)
    db.commit()
    db.refresh(ann)
    
    # Broadcast announcement
    employees = db.query(Employee).filter(Employee.is_active == True).all()
    emp_ids = [e.id for e in employees]
    if emp_ids:
        NotificationService.send_bulk_notifications(
            db=db,
            recipient_ids=emp_ids,
            event_type="announcement",
            channel="in_app",
            subject=f"New Announcement: {ann.title}",
            message=ann.content
        )
    
    return ann

def get_announcements(
    db: Session,
    page: int = 1,
    size: int = 20
) -> Tuple[List[Announcement], int]:
    query = db.query(Announcement).filter(Announcement.is_active == True)
    total = query.count()
    items = query.order_by(desc(Announcement.priority), desc(Announcement.created_at)).offset((page - 1) * size).limit(size).all()
    return items, total


def create_gatepass(payload: GatePassCreate, db: Session) -> GatePass:
    gp = GatePass(**payload.model_dump())
    db.add(gp)
    db.commit()
    db.refresh(gp)
    return gp


def list_gatepasses(
    db: Session,
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> Tuple[List[GatePass], int]:
    query = db.query(GatePass)
    if employee_id:
        query = query.filter(GatePass.employee_id == employee_id)
    if status:
        query = query.filter(GatePass.status == status)

    total = query.count()
    items = query.order_by(desc(GatePass.created_at)).offset((page - 1) * size).limit(size).all()
    return items, total


def update_gatepass_status(gatepass_id: str, new_status: str, approver_id: str | None, comments: str | None, db: Session) -> GatePass:
    gp = db.query(GatePass).filter(GatePass.id == gatepass_id).first()
    if not gp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Gate pass request not found')
    gp.status = new_status
    gp.approver_id = approver_id
    gp.admin_comments = comments
    gp.updated_at = datetime.now(timezone.utc)
    db.add(gp)
    db.commit()
    db.refresh(gp)
    return gp
