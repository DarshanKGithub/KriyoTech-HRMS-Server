import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.db.database import SessionLocal
from app.services.attendance_service import run_auto_checkout_job

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

def auto_checkout_wrapper():
    logger.info("Starting auto-checkout nightly job...")
    with SessionLocal() as db:
        try:
            run_auto_checkout_job(db)
        except Exception as e:
            logger.exception(f"Failed to run auto checkout job: {e}")

def start_scheduler():
    # Evaluate each company shift cutoff every minute
    scheduler.add_job(
        auto_checkout_wrapper,
        trigger=CronTrigger(minute="*"),
        id='nightly_auto_checkout',
        name='Nightly Auto-Checkout',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("APScheduler started successfully.")
