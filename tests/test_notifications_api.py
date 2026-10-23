import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import User
from app.schemas.notifications import (
    NotificationTemplateCreate,
    NotificationTemplateUpdate,
    NotificationCreate,
    NotificationPreferenceUpdate,
)
from app.services.notification_service import (
    NotificationTemplateService,
    NotificationService,
    NotificationPreferenceService,
)


@pytest.fixture()
def db():
    engine = create_engine(
        'sqlite://',
        future=True,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def recipient_user(db):
    user = User(
        id='user-notify-1',
        full_name='Notification User',
        email='notify@example.com',
        role='Employee',
        password_hash='hashed',
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_notification_template_crud_and_lookup(db):
    payload = NotificationTemplateCreate(
        name='Leave Approved Template',
        description='Template for approval messages',
        event_type='leave_approved',
        channel='in_app',
        subject='Leave Approved',
        body='Hi {employee_name}, your leave request was approved.',
        is_active=True,
    )

    template = NotificationTemplateService.create_template(db, payload)
    assert template.name == 'Leave Approved Template'

    fetched = NotificationTemplateService.get_template_by_event(db, 'leave_approved', 'in_app')
    assert fetched is not None
    assert fetched.id == template.id

    updated = NotificationTemplateService.update_template(
        db,
        template.id,
        NotificationTemplateUpdate(body='Updated body', is_active=False),
    )
    assert updated.body == 'Updated body'
    assert updated.is_active is False

    deleted = NotificationTemplateService.delete_template(db, template.id)
    assert deleted is True
    assert NotificationTemplateService.get_template(db, template.id) is None


def test_notification_send_preferences_read_and_stats(db, recipient_user):
    preference = NotificationPreferenceService.update_preference(
        db,
        recipient_user.id,
        NotificationPreferenceUpdate(
            email_enabled=False,
            sms_enabled=False,
            in_app_enabled=True,
            push_enabled=False,
        ),
    )
    assert preference.email_enabled is False
    assert preference.in_app_enabled is True

    skipped_payload = NotificationCreate(
        recipient_id=recipient_user.id,
        template_id=None,
        event_type='leave_approved',
        channel='email',
        subject='Leave Approved',
        message='Your leave was approved',
        data=json.dumps({'employee_name': 'Notification User'}),
    )
    skipped = NotificationService.send_notification(db, skipped_payload)
    assert skipped.status == 'Skipped'

    in_app_payload = NotificationCreate(
        recipient_id=recipient_user.id,
        template_id=None,
        event_type='leave_approved',
        channel='in_app',
        subject='Leave Approved',
        message='Your leave was approved',
        data=json.dumps({'employee_name': 'Notification User'}),
    )
    notification = NotificationService.send_notification(db, in_app_payload)
    assert notification.status == 'Sent'

    unread_count = NotificationService.get_unread_count(db, recipient_user.id)
    assert unread_count == 2

    read_notification = NotificationService.mark_as_read(db, notification.id)
    assert read_notification.status == 'Read'
    assert read_notification.read_at is not None

    remaining_unread = NotificationService.get_unread_count(db, recipient_user.id)
    assert remaining_unread == 1

    notifications = NotificationService.get_user_notifications(db, recipient_user.id, unread_only=True)
    assert len(notifications) == 1
    assert notifications[0].id == skipped.id

    deleted = NotificationService.delete_notification(db, skipped.id)
    assert deleted is True


def test_bulk_notifications_create_multiple_rows(db, recipient_user):
    second_user = User(
        id='user-notify-2',
        full_name='Second User',
        email='second@example.com',
        role='Employee',
        password_hash='hashed',
        is_active=True,
    )
    db.add(second_user)
    db.commit()

    notifications = NotificationService.send_bulk_notifications(
        db,
        [recipient_user.id, second_user.id],
        'performance_review',
        'in_app',
        'Review due',
        'Your performance review is due soon',
        json.dumps({'review_period': 'Q1 2026'}),
    )

    assert len(notifications) == 2
    assert all(item.status == 'Sent' for item in notifications)
    assert NotificationService.get_unread_count(db, recipient_user.id) == 1
    assert NotificationService.get_unread_count(db, second_user.id) == 1