from sqlalchemy import inspect
from app.db.models import Base
from app.db.security_migration import upgrade_security
REVISION='20261022_account_release'

def upgrade_release(conn):
    upgrade_security(conn)
    columns={c['name'] for c in inspect(conn).get_columns('users')}
    if 'auth_version' not in columns:
        conn.exec_driver_sql('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')
    if 'email_verified' not in columns:
        conn.exec_driver_sql('ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT false')
    columns={c['name'] for c in inspect(conn).get_columns('leave_requests')}
    if 'deducted_days' not in columns:
        conn.exec_driver_sql('ALTER TABLE leave_requests ADD COLUMN deducted_days NUMERIC(6,2) NULL')
    Base.metadata.create_all(conn)
