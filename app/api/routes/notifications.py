"""
API Routes for Notification Automation
"""

from app.http import Router, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.rbac import get_current_user, require_permissions
from app.db.models import User

from app.services.notification_service import (
    NotificationTemplateService, NotificationService, NotificationPreferenceService
)
from app.schemas.notifications import (
    NotificationTemplateCreate, NotificationTemplateUpdate, NotificationTemplatePublic,
    NotificationCreate, NotificationUpdate, NotificationPublic,
    NotificationPreferenceUpdate, NotificationPreferencePublic,
    BulkNotificationCreate, NotificationStats, NotificationFilter
)
router = Router(tags=['Notifications'])


# --- Template Management ---

@router.post('/templates', response_model=NotificationTemplatePublic, status_code=201)
def create_template(
    payload: NotificationTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_notifications'))
):
    """Create a new notification template"""
    template = NotificationTemplateService.create_template(db, payload)
    return template


@router.get('/templates/{template_id}', response_model=NotificationTemplatePublic)
def get_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a notification template"""
    template = NotificationTemplateService.get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Template not found')
    return template


@router.get('/templates', response_model=list[NotificationTemplatePublic])
def get_templates(
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all notification templates"""
    templates = NotificationTemplateService.get_all_templates(db, limit, offset)
    return templates


@router.put('/templates/{template_id}', response_model=NotificationTemplatePublic)
def update_template(
    template_id: str,
    payload: NotificationTemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_notifications'))
):
    """Update a notification template"""
    template = NotificationTemplateService.update_template(db, template_id, payload)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Template not found')
    return template


@router.delete('/templates/{template_id}', status_code=204)
def delete_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_notifications'))
):
    """Delete a notification template"""
    if not NotificationTemplateService.delete_template(db, template_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Template not found')


# --- Notification Management ---

@router.post('', response_model=NotificationPublic, status_code=201)
def send_notification(
    payload: NotificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('send_notifications'))
):
    """Send a notification"""
    notification = NotificationService.send_notification(db, payload)
    return notification


@router.post('/bulk', response_model=list[NotificationPublic], status_code=201)
def send_bulk_notifications(
    payload: BulkNotificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('send_notifications'))
):
    """Send notifications to multiple recipients"""
    notifications = NotificationService.send_bulk_notifications(
        db,
        payload.recipient_ids,
        payload.event_type,
        payload.channel,
        payload.subject,
        payload.message,
        payload.data
    )
    return notifications


@router.get('/{notification_id}', response_model=NotificationPublic)
def get_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific notification"""
    notification = NotificationService.get_notification(db, notification_id)
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Notification not found')
    
    # Access control: user can view their own notifications or admin can view any
    if notification.recipient_id != current_user.id and not (current_user.role == 'Admin' or current_user.role == 'HR'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view this notification')
    
    return notification


@router.get('/user/me/notifications', response_model=list[NotificationPublic])
def get_my_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's notifications"""
    notifications = NotificationService.get_user_notifications(
        db, current_user.id, limit, offset, unread_only
    )
    return notifications


@router.get('/user/{user_id}/notifications', response_model=list[NotificationPublic])
def get_user_notifications(
    user_id: str,
    unread_only: bool = Query(False),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a user's notifications"""
    # Access control: user can view their own or admin/hr can view any
    if user_id != current_user.id and not (current_user.role == 'Admin' or current_user.role == 'HR'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view these notifications')
    
    notifications = NotificationService.get_user_notifications(
        db, user_id, limit, offset, unread_only
    )
    return notifications


@router.get('/user/me/unread-count', response_model=dict)
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get unread notification count for current user"""
    count = NotificationService.get_unread_count(db, current_user.id)
    return {'unread_count': count}


@router.patch('/{notification_id}', response_model=NotificationPublic)
def update_notification(
    notification_id: str,
    payload: NotificationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a notification"""
    notification = NotificationService.get_notification(db, notification_id)
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Notification not found')
    
    # Access control: user can update their own
    if notification.recipient_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot update this notification')
    
    # Mark as read
    if payload.status == 'Read':
        return NotificationService.mark_as_read(db, notification_id)
    
    return notification


@router.post('/mark-read', response_model=dict)
def mark_notifications_read(
    notification_ids: list[str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark multiple notifications as read"""
    from app.db.models import Notification
    from sqlalchemy import select
    unique_ids = set(notification_ids)
    owned_ids = set(db.scalars(select(Notification.id).where(Notification.id.in_(unique_ids), Notification.recipient_id == current_user.id)))
    if owned_ids != unique_ids:
        raise HTTPException(403, 'Only your own notifications can be marked as read')
    count = NotificationService.mark_multiple_as_read(db, list(owned_ids))
    return {'marked_count': count}


@router.delete('/{notification_id}', status_code=204)
def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a notification"""
    notification = NotificationService.get_notification(db, notification_id)
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Notification not found')
    
    # Access control: user can delete their own
    if notification.recipient_id != current_user.id and not (current_user.role == 'Admin'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot delete this notification')
    
    NotificationService.delete_notification(db, notification_id)


# --- Notification Stats ---

@router.get('/user/me/stats', response_model=NotificationStats)
def get_my_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's notification statistics"""
    stats = NotificationService.get_notification_stats(db, current_user.id)
    return stats


# --- Notification Preferences ---

@router.get('/preferences/me', response_model=NotificationPreferencePublic)
def get_my_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's notification preferences"""
    pref = NotificationPreferenceService.get_preference(db, current_user.id)
    return pref


@router.patch('/preferences/me', response_model=NotificationPreferencePublic)
def update_my_preferences(
    payload: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current user's notification preferences"""
    pref = NotificationPreferenceService.update_preference(db, current_user.id, payload)
    return pref


@router.get('/preferences/{user_id}', response_model=NotificationPreferencePublic)
def get_user_preferences(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a user's notification preferences"""
    # Access control: user can view their own or admin/hr can view any
    if user_id != current_user.id and not (current_user.role == 'Admin' or current_user.role == 'HR'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot view these preferences')
    
    pref = NotificationPreferenceService.get_preference(db, user_id)
    return pref


@router.patch('/preferences/{user_id}', response_model=NotificationPreferencePublic)
def update_user_preferences(
    user_id: str,
    payload: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_notifications'))
):
    """Update a user's notification preferences (Admin only)"""
    pref = NotificationPreferenceService.update_preference(db, user_id, payload)
    return pref
