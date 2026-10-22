from app.http import Router, Request, Depends
from app.db.database import get_db
from app.api.routes.billing import verified_webhook
router = Router()

@router.post('/razorpay')
def razorpay_webhook(request: Request, db=Depends(get_db)):
    return verified_webhook(request, db)
