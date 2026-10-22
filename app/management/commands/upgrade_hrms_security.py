from django.core.management.base import BaseCommand, CommandError
from sqlalchemy import inspect
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from app.db.database import engine
from app.db.security_migration import upgrade_security, REVISION

class Command(BaseCommand):
    help = 'Apply the reviewed HR ownership upgrade and record the schema baseline atomically.'
    def handle(self, *args, **options):
        with engine.begin() as conn:
            report = upgrade_security(conn)
            script = ScriptDirectory.from_config(Config('alembic.ini'))
            MigrationContext.configure(conn).stamp(script, REVISION)
        self.stdout.write(self.style.SUCCESS('HR schema upgraded: ' + REVISION))
        if report:
            self.stdout.write('Unowned legacy rows hidden pending ownership review: ' + str(report))
