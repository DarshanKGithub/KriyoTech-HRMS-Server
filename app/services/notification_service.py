"""
Services for Notification Automation
Handles sending, queuing, and managing notifications
"""

from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from datetime import datetime, timezone
from uuid import uuid4
import json
import re

from app.db.models import (
    NotificationTemplate, Notification, NotificationPreference, User
)
from app.schemas.notifications import (
    NotificationTemplateCreate, NotificationTemplateUpdate,
    NotificationCreate, NotificationUpdate,
    NotificationPreferenceUpdate
)


class NotificationTemplateService:
    """Service for managing notification templates"""
    
    @staticmethod
    def create_template(db: Session, payload: NotificationTemplateCreate) -> NotificationTemplate:
        """Create a new notification template"""
        template = NotificationTemplate(
            id=str(uuid4()),
            name=payload.name,
            description=payload.description,
            event_type=payload.event_type,
            channel=payload.channel,
            subject=payload.subject,
            body=payload.body,
            is_active=payload.is_active
        )
        db.add(template)
        db.commit()
        return template
    
    @staticmethod
    def get_template(db: Session, template_id: str) -> NotificationTemplate:
        """Get a template by ID"""
        return db.query(NotificationTemplate).filter(
            NotificationTemplate.id == template_id
        ).first()
    
    @staticmethod
    def get_template_by_event(db: Session, event_type: str, channel: str) -> NotificationTemplate:
        """Get a template by event type and channel"""
        return db.query(NotificationTemplate).filter(
            and_(
                NotificationTemplate.event_type == event_type,
                NotificationTemplate.channel == channel,
                NotificationTemplate.is_active == True
            )
        ).first()
    
    @staticmethod
    def get_all_templates(db: Session, limit: int = 100, offset: int = 0) -> list[NotificationTemplate]:
        """Get all templates with pagination"""
        return db.query(NotificationTemplate).order_by(
            desc(NotificationTemplate.created_at)
        ).limit(limit).offset(offset).all()
    
    @staticmethod
    def update_template(db: Session, template_id: str, payload: NotificationTemplateUpdate) -> NotificationTemplate:
        """Update a template"""
        template = db.query(NotificationTemplate).filter(
            NotificationTemplate.id == template_id
        ).first()
        
        if not template:
            return None
        
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(template, field, value)
        
        template.updated_at = datetime.now(timezone.utc)
        db.commit()
        return template
    
    @staticmethod
    def delete_template(db: Session, template_id: str) -> bool:
        """Delete a template"""
        template = db.query(NotificationTemplate).filter(
            NotificationTemplate.id == template_id
        ).first()
        
        if not template:
            return False
        
        db.delete(template)
        db.commit()
        return True


class NotificationService:
    """Service for managing notifications"""
    
    @staticmethod
    def substitute_variables(template_body: str, variables: dict) -> str:
        """Substitute {variable} placeholders with actual values"""
        result = template_body
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result
    
    @staticmethod
    def should_send(db: Session, user_id: str, channel: str) -> bool:
        """Check if notification should be sent based on user preferences"""
        from sqlalchemy import select
        recipient=db.get(User,user_id)
        if not recipient: return False
        pref=db.execute(select(NotificationPreference.__table__).where(NotificationPreference.__table__.c.user_id==user_id,NotificationPreference.__table__.c.tenant_id==recipient.tenant_id)).mappings().first()

        if not pref:
            # Default preferences: all channels enabled
            return True
        
        # Check channel preference
        channel_map = {
            'email': pref['email_enabled'],
            'sms': pref['sms_enabled'],
            'in_app': pref['in_app_enabled'],
            'push': pref['push_enabled']
        }
        
        if channel not in channel_map:
            return False
        
        return channel_map[channel]
    
    @staticmethod
    def send_notification(db: Session, payload: NotificationCreate) -> Notification:
        """Create and send a notification"""
        from app.http import HTTPException
        recipient = db.get(User, payload.recipient_id)
        if not recipient:
            raise HTTPException(404, 'Recipient not found')
        
        # Check user preferences
        if not NotificationService.should_send(db, payload.recipient_id, payload.channel):
            status = 'Skipped'
        else:
            status = 'Sent' if payload.channel=='in_app' else 'Pending'
        
        notification = Notification(
            id=str(uuid4()),
            tenant_id=recipient.tenant_id,
            recipient_id=payload.recipient_id,
            template_id=payload.template_id,
            event_type=payload.event_type,
            channel=payload.channel,
            subject=payload.subject,
            message=payload.message,
            data=payload.data,
            status=status
        )
        
        db.add(notification)
        if status!='Skipped' and payload.channel=='email':
            from app.services.mail_service import queue_mail
            from app.http import HTTPException
            recipient=db.get(User,payload.recipient_id)
            if not recipient: raise HTTPException(404,'Recipient not found')
            db.flush()
            queue_mail(db,recipient.email,payload.subject or 'KriyoHR notification',payload.message,recipient.tenant_id,notification.id)
        elif status!='Skipped' and payload.channel not in {'in_app','email'}:
            from app.http import HTTPException
            raise HTTPException(503,'This notification delivery channel is not configured')
        if status=='Sent': notification.sent_at=datetime.now(timezone.utc)
        db.commit()
        return notification
    
    @staticmethod
    def send_bulk_notifications(db: Session, recipient_ids: list, event_type: str, 
                               channel: str, subject: str, message: str, 
                               data: str = None) -> list[Notification]:
        """Send notifications to multiple recipients"""
        notifications = []
        
        for recipient_id in recipient_ids:
            payload = NotificationCreate(
                recipient_id=recipient_id,
                event_type=event_type,
                channel=channel,
                subject=subject,
                message=message,
                data=data
            )
            notif = NotificationService.send_notification(db, payload)
            notifications.append(notif)
        
        return notifications
    
    @staticmethod
    def get_notification(db: Session, notification_id: str) -> Notification:
        """Get a notification by ID"""
        return db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
    
    @staticmethod
    def get_user_notifications(db: Session, user_id: str, limit: int = 50, 
                              offset: int = 0, unread_only: bool = False) -> list[Notification]:
        """Get notifications for a user"""
        query = db.query(Notification).filter(
            Notification.recipient_id == user_id
        )
        
        if unread_only:
            query = query.filter(
                Notification.status != 'Read'
            )
        
        return query.order_by(
            desc(Notification.created_at)
        ).limit(limit).offset(offset).all()
    
    @staticmethod
    def get_unread_count(db: Session, user_id: str) -> int:
        """Get count of unread notifications"""
        return db.query(Notification).filter(
            and_(
                Notification.recipient_id == user_id,
                Notification.status != 'Read'
            )
        ).count()
    
    @staticmethod
    def mark_as_read(db: Session, notification_id: str) -> Notification:
        """Mark notification as read"""
        notification = db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if not notification:
            return None
        
        notification.status = 'Read'
        notification.read_at = datetime.now(timezone.utc)
        notification.updated_at = datetime.now(timezone.utc)
        db.commit()
        return notification
    
    @staticmethod
    def mark_multiple_as_read(db: Session, notification_ids: list[str]) -> int:
        """Mark multiple notifications as read"""
        now = datetime.now(timezone.utc)
        count = db.query(Notification).filter(
            Notification.id.in_(notification_ids)
        ).update({
            'status': 'Read',
            'read_at': now,
            'updated_at': now
        })
        db.commit()
        return count
    
    @staticmethod
    def delete_notification(db: Session, notification_id: str) -> bool:
        """Delete a notification"""
        notification = db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if not notification:
            return False
        
        db.delete(notification)
        db.commit()
        return True
    
    @staticmethod
    def get_notification_stats(db: Session, user_id: str) -> dict:
        """Get notification statistics for a user"""
        notifs = db.query(Notification).filter(
            Notification.recipient_id == user_id
        ).all()
        
        by_channel = {}
        by_status = {}
        unread_count = 0
        
        for n in notifs:
            # Count by channel
            by_channel[n.channel] = by_channel.get(n.channel, 0) + 1
            
            # Count by status
            by_status[n.status] = by_status.get(n.status, 0) + 1
            
            # Count unread
            if n.status != 'Read':
                unread_count += 1
        
        return {
            'unread_count': unread_count,
            'total_count': len(notifs),
            'by_channel': by_channel,
            'by_status': by_status
        }


class NotificationPreferenceService:
    """Service for managing notification preferences"""
    
    @staticmethod
    def get_preference(db: Session, user_id: str) -> NotificationPreference:
        """Get user's notification preferences"""
        pref = db.query(NotificationPreference).filter(
            NotificationPreference.user_id == user_id
        ).first()
        
        if not pref:
            # Create default preferences
            pref = NotificationPreference(
                id=str(uuid4()),
                user_id=user_id,
                email_enabled=True,
                sms_enabled=False,
                in_app_enabled=True,
                push_enabled=True
            )
            db.add(pref)
            db.commit()
        
        return pref
    
    @staticmethod
    def update_preference(db: Session, user_id: str, 
                         payload: NotificationPreferenceUpdate) -> NotificationPreference:
        """Update user's notification preferences"""
        pref = NotificationPreferenceService.get_preference(db, user_id)
        
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(pref, field, value)
        
        pref.updated_at = datetime.now(timezone.utc)
        db.commit()
        return pref
