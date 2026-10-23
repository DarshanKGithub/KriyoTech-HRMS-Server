"""Account recovery, durable mail and leave reversal accounting."""
from alembic import op
revision='20261022_account_release'
down_revision='20261022_secure_hr'
branch_labels=None
depends_on=None

def upgrade():
    from app.db.release_migration import upgrade_release
    upgrade_release(op.get_bind())

def downgrade():
    raise RuntimeError('Restore a verified backup to roll back account security data')
