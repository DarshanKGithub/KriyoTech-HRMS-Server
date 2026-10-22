"""Add explicit tenant ownership and fractional HR days.
revision: 20261022_secure_hr
"""
revision = '20261022_secure_hr'
down_revision = 'c796235f9357'
branch_labels = None
depends_on = None

def upgrade():
    from alembic import op
    from app.db.security_migration import upgrade_security
    upgrade_security(op.get_bind())

def downgrade():
    raise RuntimeError('Ownership migration contains backfills; restore a reviewed backup instead')
