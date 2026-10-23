"""Durable encrypted mail outbox. Delivery is performed by run_mail_worker."""
import base64
import hashlib
import smtplib
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from cryptography.fernet import Fernet
from sqlalchemy import select
from app.core.config import settings
from app.db.models import MailMessage
from app.http import HTTPException


def _cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()))


def require_mail():
    if settings.mail_transport not in {'smtp','auto'} or not settings.smtp_server:
        raise HTTPException(503, 'Email delivery is not configured. Contact your administrator.')
    if settings.mail_transport=='auto' and not (settings.smtp_username and settings.smtp_password):
        raise HTTPException(503,'Email delivery credentials are not configured. Contact your administrator.')
    if not settings.smtp_use_tls and not (settings.smtp_allow_insecure_loopback and settings.smtp_server in {'localhost','127.0.0.1','::1'}):
        raise HTTPException(503, 'Secure email transport is required')


def queue_mail(db, recipient, subject, body, tenant_id=None,notification_id=None):
    require_mail()
    mail = MailMessage(notification_id=notification_id,tenant_id=tenant_id,recipient=recipient,subject=subject,encrypted_body=_cipher().encrypt(body.encode()).decode())
    db.add(mail)
    return mail


def deliver_pending(db, batch=25):
    require_mail()
    now=datetime.now(timezone.utc)
    rows=list(db.scalars(select(MailMessage).where(MailMessage.status.in_(['queued','retry']),MailMessage.available_at<=now).order_by(MailMessage.created_at).limit(batch).with_for_update(of=MailMessage,skip_locked=True)))
    sent=0
    for item in rows:
        message=EmailMessage()
        message['From']=settings.smtp_from
        message['To']=item.recipient
        message['Subject']=item.subject
        message['Message-ID']=f'<{item.id}@kriyohr.local>'
        message.set_content(_cipher().decrypt(item.encrypted_body.encode()).decode())
        item.attempts+=1
        try:
            with smtplib.SMTP(settings.smtp_server,settings.smtp_port,timeout=15) as smtp:
                smtp.ehlo()
                if settings.smtp_use_tls:
                    import ssl
                    smtp.starttls(context=ssl.create_default_context());smtp.ehlo()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username,settings.smtp_password or '')
                smtp.send_message(message)
            item.status='sent';item.sent_at=now
            # Remove sensitive reset links after successful delivery.
            item.encrypted_body=_cipher().encrypt(b'Delivered').decode()
            if item.notification_id:
                from app.db.models import Notification
                from sqlalchemy import update
                db.execute(update(Notification).where(Notification.id==item.notification_id,Notification.tenant_id==item.tenant_id).values(status='Sent',sent_at=now))
            sent+=1
        except (OSError,smtplib.SMTPException):
            item.status='failed' if item.attempts>=5 else 'retry'
            if item.status=='failed' and item.notification_id:
                from app.db.models import Notification
                from sqlalchemy import update
                db.execute(update(Notification).where(Notification.id==item.notification_id,Notification.tenant_id==item.tenant_id).values(status='Failed',error_message='Email delivery failed after retries'))
            item.available_at=now+timedelta(seconds=min(3600,30*2**item.attempts))
    db.commit()
    return {'processed':len(rows),'sent':sent,'failed':sum(row.status=='failed' for row in rows)}
