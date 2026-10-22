from django.core.management.base import BaseCommand

from app.db.database import SessionLocal, engine
from app.db import models


class Command(BaseCommand):
    help = 'Initialize a new HRMS database; optionally seed demonstration data.'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true', help='Create demonstration users and HR data')

    def handle(self, *args, **options):
        models.Base.metadata.create_all(bind=engine)
        if options['demo']:
            with SessionLocal() as db:
                for name in (
                    'seed_demo_users', 'seed_demo_org', 'seed_demo_plans',
                    'seed_demo_tenant_subscription', 'seed_demo_shifts',
                    'seed_demo_leave_data', 'seed_demo_salary_data',
                ):
                    getattr(models, name)(db)
        self.stdout.write(self.style.SUCCESS('HRMS database initialized'))
