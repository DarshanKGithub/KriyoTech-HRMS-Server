"""Request-scoped ownership enforcement for all ORM reads and writes.

Unowned legacy rows are deliberately invisible until ownership is resolved.
Background jobs/admin migrations use unbound sessions and explicit scope.
"""
from dataclasses import dataclass
from sqlalchemy import event, select, or_, inspect
from sqlalchemy.orm import Session, with_loader_criteria
from app.http import HTTPException

@dataclass(frozen=True)
class Actor:
    id: str
    tenant_id: str
    role: str
    employee_id: str | None
    employee_ids: tuple
    user_ids: tuple


def bind_actor(db, user):
    from app.db.models import Employee, User, Tenant
    if user.role == 'Super Admin':
        db.info.pop('actor', None)
        return
    if not user.tenant_id:
        raise HTTPException(403, 'An organization assignment is required')
    tenant = db.execute(select(Tenant.__table__.c.is_active).where(Tenant.id == user.tenant_id)).scalar()
    if not tenant:
        raise HTTPException(403, 'Your organization is inactive')
    employees = Employee.__table__
    identity = db.execute(select(employees.c.is_active).where(employees.c.tenant_id == user.tenant_id, or_(employees.c.id == user.id, employees.c.email == user.email))).first()
    if identity is not None and not identity[0]:
        raise HTTPException(403, 'Your employee account is inactive')
    own = db.execute(select(employees.c.id).where(employees.c.tenant_id == user.tenant_id, or_(employees.c.id == user.id, employees.c.email == user.email))).scalar()
    ids = tuple(db.execute(select(employees.c.id).where(employees.c.tenant_id == user.tenant_id, or_(employees.c.id == own, employees.c.manager_id == own))).scalars()) if own else ()
    users = User.__table__
    user_ids = tuple(db.execute(select(users.c.id).where(users.c.tenant_id == user.tenant_id, or_(users.c.id.in_(ids), users.c.email.in_(select(employees.c.email).where(employees.c.id.in_(ids)))))).scalars())
    db.info['actor'] = Actor(user.id, user.tenant_id, user.role, own, ids if user.role == 'Manager' else (own,) if own else (), user_ids if user.role == 'Manager' else (user.id,))


def _criterion(model, actor):
    from app.db.models import Employee, User, Notification, NotificationPreference, AuditLog
    clause = model.tenant_id == actor.tenant_id
    limited = actor.role not in {'HR', 'Admin', 'CEO'}
    if model is Notification:
        return clause & (model.recipient_id == actor.id)
    if model is NotificationPreference:
        return clause & (model.user_id == actor.id)
    if limited:
        if model is Employee:
            clause &= model.id.in_(actor.employee_ids)
        elif model is User:
            clause &= model.id.in_(actor.user_ids)
        elif hasattr(model, 'employee_id'):
            clause &= model.employee_id.in_(actor.employee_ids)
        elif model is AuditLog:
            clause &= model.actor_id.in_(actor.user_ids)
    return clause


@event.listens_for(Session, 'do_orm_execute')
def scoped_reads(state):
    actor = state.session.info.get('actor')
    if not actor or state.execution_options.get('skip_ownership'):
        return
    from app.db.models import TENANT_MODELS
    statement = state.statement
    if state.is_select or state.is_update or state.is_delete:
        for model in TENANT_MODELS:
            statement = statement.options(with_loader_criteria(model, _criterion(model, actor), include_aliases=True))
        state.statement = statement


@event.listens_for(Session, 'before_flush')
def scoped_writes(db, context, instances):
    actor = db.info.get('actor')
    if not actor:
        return
    from app.db.models import Base, GLOBAL_TABLES, Employee, User
    models = {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers}
    rows = list(db.new) + list(db.dirty) + list(db.deleted)
    pending = {(inspect(row).mapper.local_table.name, getattr(row, 'id', None)): row for row in db.new}
    for row in rows:
        table = inspect(row).mapper.local_table
        if table.name == 'tenants' and row.id == actor.tenant_id and row not in db.deleted and row not in db.new:
            changed = {attr.key for attr in inspect(row).attrs if attr.history.has_changes()}
            if changed <= {'name', 'timezone', 'working_days_json'}:
                continue
        if table.name in GLOBAL_TABLES:
            raise HTTPException(403, 'Only platform administrators can change the product catalog')
        if row in db.new and getattr(row, 'tenant_id', None) is None:
            row.tenant_id = actor.tenant_id
        if getattr(row, 'tenant_id', None) != actor.tenant_id:
            raise HTTPException(403, 'Cannot access records outside your organization')
        if actor.role not in {'HR', 'Admin', 'CEO'}:
            employee_id = row.id if isinstance(row, Employee) else getattr(row, 'employee_id', None)
            if employee_id and employee_id not in actor.employee_ids:
                raise HTTPException(403, 'This employee is outside your reporting scope')
            if isinstance(row, User) and row.id != actor.id:
                raise HTTPException(403, 'You cannot change another user account')
    for row in rows:
        if row in db.deleted:
            continue
        for column in inspect(row).mapper.local_table.columns:
            value = getattr(row, column.name, None)
            if value is None or column.name == 'tenant_id':
                continue
            for fk in column.foreign_keys:
                parent = models.get(fk.column.table.name)
                if not parent or not hasattr(parent, 'tenant_id'):
                    continue
                target = pending.get((fk.column.table.name, value)) or db.get(parent, value)
                if not target or target.tenant_id != actor.tenant_id:
                    raise HTTPException(403, f'Invalid organization reference: {column.name}')
