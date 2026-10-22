from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine_kwargs = {}
if settings.sqlalchemy_database_url.startswith('sqlite'):
    engine_kwargs['connect_args'] = {'check_same_thread': False}

class OwnedSession(Session):
    def get(self, entity, ident, **kwargs):
        result = super().get(entity, ident, **kwargs)
        actor = self.info.get('actor')
        if result is not None and actor and hasattr(result, 'tenant_id'):
            from app.db.models import Notification, NotificationPreference
            if isinstance(result, Notification) and result.recipient_id != actor.id:
                return None
            if isinstance(result, NotificationPreference) and result.user_id != actor.id:
                return None
            if result.tenant_id != actor.tenant_id:
                return None
            if actor.role not in {'HR', 'Admin', 'CEO'}:
                from app.db.models import Employee, User
                if isinstance(result, Employee) and result.id not in actor.employee_ids:
                    return None
                if isinstance(result, User) and result.id not in actor.user_ids:
                    return None
                if hasattr(result,'employee_id') and result.employee_id not in actor.employee_ids:
                    return None
        return result

engine = create_engine(settings.sqlalchemy_database_url, future=True, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, class_=OwnedSession, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
