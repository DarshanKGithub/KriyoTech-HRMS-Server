"""Idempotent migration; never guesses ownership of tenantless root records."""
from sqlalchemy import inspect, text, Index
from app.db.models import Base, TENANT_MODELS

REVISION = '20261022_secure_hr'

def upgrade_security(conn):
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())
    if not tables:
        Base.metadata.create_all(conn)
        return
    for model in TENANT_MODELS:
        table = model.__table__
        if table.name not in tables:
            table.create(conn)
            continue
        columns = {item['name'] for item in inspect(conn).get_columns(table.name)}
        if 'tenant_id' not in columns:
            conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN tenant_id VARCHAR(36) REFERENCES tenants(id)')
        name = f'ix_{table.name}_tenant_id'
        index = next((item for item in table.indexes if item.name == name), None)
        (index if index is not None else Index(name, table.c.tenant_id)).create(conn, checkfirst=True)
    columns = {c['name'] for c in inspect(conn).get_columns('tenants')}
    if 'timezone' not in columns:
        conn.exec_driver_sql("ALTER TABLE tenants ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata'")
    if 'working_days_json' not in columns:
        conn.exec_driver_sql("ALTER TABLE tenants ADD COLUMN working_days_json TEXT NOT NULL DEFAULT '[0,1,2,3,4]'")
    leave_columns = {c['name'] for c in inspect(conn).get_columns('leave_types')}
    if 'is_paid' not in leave_columns:
        conn.exec_driver_sql('ALTER TABLE leave_types ADD COLUMN is_paid BOOLEAN NOT NULL DEFAULT true')
    keys = ['employee_id', 'user_id', 'recipient_id', 'author_id', 'actor_id', 'attendance_id', 'payslip_id', 'application_id', 'job_id', 'candidate_id', 'roster_id', 'survey_id', 'question_id', 'template_id', 'workflow_id', 'goal_id', 'course_id', 'appraisal_id']
    owned = {m.__tablename__ for m in TENANT_MODELS}
    for _ in range(8):
        for model in TENANT_MODELS:
            table = model.__table__
            for name in keys:
                if name not in table.c:
                    continue
                column = table.c[name]
                for fk in column.foreign_keys:
                    parent = fk.column.table.name
                    if parent in owned:
                        conn.exec_driver_sql(f'UPDATE "{table.name}" SET tenant_id=(SELECT p.tenant_id FROM "{parent}" p WHERE p.id="{table.name}"."{name}") WHERE tenant_id IS NULL AND EXISTS (SELECT 1 FROM "{parent}" p WHERE p.id="{table.name}"."{name}" AND p.tenant_id IS NOT NULL)')
    if conn.dialect.name == 'postgresql':
        for table, columns in {'payslips':['days_worked','days_absent'], 'leave_requests':['days_requested'], 'leave_balances':['granted_days','balance_days'], 'leave_types':['default_days_per_year']}.items():
            for column in columns:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE NUMERIC(6,2)')
        conn.exec_driver_sql('ALTER TABLE payslip_components ALTER COLUMN salary_component_id DROP NOT NULL')
        for constraint in inspect(conn).get_unique_constraints('salaries'):
            if constraint['column_names'] == ['employee_id']:
                conn.exec_driver_sql(f'ALTER TABLE salaries DROP CONSTRAINT "{constraint["name"]}"')
        for index in inspect(conn).get_indexes('salaries'):
            if index.get('unique') and index['column_names'] == ['employee_id'] and not index.get('duplicates_constraint'):
                conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{index["name"]}"')
        duplicate = conn.execute(text('SELECT employee_id FROM payslips GROUP BY employee_id, month, year HAVING COUNT(*) > 1 LIMIT 1')).first()
        if duplicate:
            raise RuntimeError('Duplicate payslip periods must be reviewed before this migration')
        conn.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_payslip_employee_period ON payslips (employee_id, month, year)')
        conn.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_salary_active_employee ON salaries (employee_id) WHERE is_active=true')
    quarantined = {}
    for model in TENANT_MODELS:
        if model.__tablename__ == 'users':
            continue
        count = conn.execute(text(f'SELECT COUNT(*) FROM "{model.__tablename__}" WHERE tenant_id IS NULL')).scalar()
        if count:
            quarantined[model.__tablename__] = count
    return quarantined
