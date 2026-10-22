import json
from typing import Any, Tuple
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import AuditLog, User


def list_audit_logs(db: Session, page: int = 1, size: int = 20, object_type: str | None = None,
                    actor_id: str | None = None, tenant_id: str | None = None, platform: bool = True) -> Tuple[list[AuditLog], int]:
    stmt = select(AuditLog)
    if not platform:
        stmt = stmt.join(User, User.id == AuditLog.actor_id).where(User.tenant_id == tenant_id)
    if object_type:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    return items, int(total or 0)


def create_audit_log(
    db: Session,
    *,
    actor_id: str | None,
    action: str,
    object_type: str,
    object_id: str | None,
    data: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        data=json.dumps(data or {}, default=str),
    )
    db.add(log)
    return log
