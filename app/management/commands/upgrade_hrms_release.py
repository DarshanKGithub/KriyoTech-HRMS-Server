from django.core.management.base import BaseCommand
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from app.db.database import engine
from app.db.release_migration import upgrade_release,REVISION
class Command(BaseCommand):
    help='Apply the reviewed account and workflow release upgrade atomically.'
    def handle(self,*args,**options):
        with engine.begin() as conn:
            upgrade_release(conn)
            MigrationContext.configure(conn).stamp(ScriptDirectory.from_config(Config('alembic.ini')),REVISION)
        self.stdout.write(self.style.SUCCESS('HR schema upgraded: '+REVISION))
