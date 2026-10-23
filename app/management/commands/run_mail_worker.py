import time
from django.core.management.base import BaseCommand
from app.db.database import SessionLocal
from app.services.mail_service import deliver_pending
class Command(BaseCommand):
    help='Deliver the persistent email outbox with bounded retries.'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        while True:
            with SessionLocal() as db:
                result=deliver_pending(db)
            if result['processed']: self.stdout.write(str(result))
            if options['once']: return
            time.sleep(2)
