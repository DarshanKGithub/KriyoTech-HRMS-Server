from datetime import date, datetime

from app.http import Router, Depends, HTTPException, status, Query
from app.http import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.schemas.dashboard import DashboardSummaryResponse
from app.schemas.dashboard_extended import (
    MySpaceDashboard, OrganizationDashboard, CalendarResponse,
    DelegationDashboard, ActivityFeedResponse
)
from app.services.auth_service import decode_token_payload
from app.services.dashboard_service import get_dashboard_summary
from app.services.dashboard_extended_service import (
    get_my_space_dashboard, get_organization_dashboard, 
    get_calendar_events, get_delegation_dashboard,
    get_activity_feed
)
from app.core.rbac import has_permission, get_current_user

security = HTTPBearer(auto_error=False)

router = Router()


@router.get('/workspace', response_model=dict)
def workspace(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.workspace_service import workspace_dashboard
    return workspace_dashboard(user, db)


@router.get('/summary', response_model=DashboardSummaryResponse)
def summary(
    start_date: date | None = None,
    end_date: date | None = None,
    department_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> DashboardSummaryResponse:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='start_date must be before end_date')

    # Auth check only; dashboard currently allows all authenticated roles.
    decode_token_payload(credentials.credentials)

    return get_dashboard_summary(
        db=db,
        start_date=start_date,
        end_date=end_date,
        department_id=department_id,
    )


# ============================================================================
# MY SPACE ENDPOINTS
# ============================================================================

@router.get('/my-space', response_model=MySpaceDashboard)
def get_my_space(
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MySpaceDashboard:
    """Get personalized My Space dashboard."""
    return get_my_space_dashboard(db=db, employee_id=_current_user.id)


# ============================================================================
# ORGANIZATION ENDPOINTS
# ============================================================================

@router.get('/organization', response_model=OrganizationDashboard)
def get_organization(
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationDashboard:
    """Get organization-wide dashboard (all authenticated users can view)."""
    return get_organization_dashboard(db=db)


# ============================================================================
# CALENDAR ENDPOINTS
# ============================================================================

@router.get('/calendar/events', response_model=CalendarResponse)
def get_calendar(
    start_date: date = Query(..., description='Start date in YYYY-MM-DD format'),
    end_date: date = Query(..., description='End date in YYYY-MM-DD format'),
    view_type: str = Query('personal', description='View type: "personal" or "team"'),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CalendarResponse:
    """Get calendar events for a date range."""
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='start_date must be before end_date'
        )
    
    return get_calendar_events(
        db=db,
        employee_id=_current_user.id,
        role=_current_user.role,
        start_date=start_date,
        end_date=end_date,
        view_type=view_type,
    )


# ============================================================================
# DELEGATION/TASKS ENDPOINTS
# ============================================================================

@router.get('/delegation', response_model=DelegationDashboard)
def get_delegation(
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DelegationDashboard:
    """Get delegation and task management dashboard."""
    return get_delegation_dashboard(db=db, employee_id=_current_user.id)


# ============================================================================
# ACTIVITY FEED ENDPOINTS
# ============================================================================

@router.get('/activity-feed', response_model=ActivityFeedResponse)
def get_feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActivityFeedResponse:
    """Get activity feed with pagination."""
    return get_activity_feed(
        db=db,
        employee_id=_current_user.id,
        page=page,
        page_size=page_size,
    )
