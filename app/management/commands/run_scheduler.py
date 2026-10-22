from django.conf import settings
from django.core.management.base import BaseCommand
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.scheduler import auto_checkout_wrapper


class Command(BaseCommand):
    help = 'Run one dedicated worker for shift-end attendance auto-checkout.'

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_job(
            auto_checkout_wrapper,
            CronTrigger(minute='*', timezone=settings.TIME_ZONE),
            id='nightly_auto_checkout', replace_existing=True,
        )
        self.stdout.write('Attendance scheduler running')
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown(wait=False)
