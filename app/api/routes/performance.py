from app.services.auth_service import resolve_employee_id
from app.http import Router, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date
from app.db.database import get_db
from app.core.rbac import get_current_user, require_permissions, has_permission
from app.db.models import User
from app.services.performance_service import (
    PerformanceService, GoalService, KPIService, TrainingService, CertificationService
)
from app.schemas.performance import (
    PerformanceAppraisalCreate, PerformanceAppraisalUpdate, PerformanceAppraisalPublic,
    GoalCreate, GoalUpdate, GoalPublic,
    KPICreate, KPIUpdate, KPIPublic,
    EmployeeTrainingCreate, EmployeeTrainingUpdate, EmployeeTrainingPublic,
    CertificationCreate, CertificationUpdate, CertificationPublic, CertificationVerifyPublic,
    TrainingCourseCreate, TrainingCourseUpdate, TrainingCoursePublic
)

router = Router(prefix='/performance', tags=['Performance & KPI'])


# ==================== PERFORMANCE APPRAISAL ENDPOINTS ====================

@router.post('/appraisals', response_model=PerformanceAppraisalPublic)
def create_appraisal(
    payload: PerformanceAppraisalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Create a new performance appraisal"""
    appraisal = PerformanceService.create_appraisal(db, payload)
    return appraisal


@router.get('/appraisals/{appraisal_id}', response_model=PerformanceAppraisalPublic)
def get_appraisal(
    appraisal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific appraisal"""
    appraisal = PerformanceService.get_appraisal(db, appraisal_id)
    if not appraisal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Appraisal not found')
    
    # Access control: user can view their own or if they're a reviewer
    if appraisal.employee_id != current_user.id and appraisal.reviewer_id != current_user.id:
        if not has_permission(current_user.role, 'manage_performance'):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Cannot view this appraisal'
            )
    return appraisal


@router.get('/appraisals/employee/{employee_id}')
def get_employee_appraisals(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all appraisals for an employee"""
    # Access control
    if employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    appraisals = PerformanceService.get_appraisals_for_employee(db, employee_id)
    return [PerformanceAppraisalPublic.model_validate(a, from_attributes=True) for a in appraisals]


@router.put('/appraisals/{appraisal_id}', response_model=PerformanceAppraisalPublic)
def update_appraisal(
    appraisal_id: str,
    payload: PerformanceAppraisalUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Update an appraisal"""
    appraisal = PerformanceService.get_appraisal(db, appraisal_id)
    if not appraisal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Appraisal not found')
    
    updated = PerformanceService.update_appraisal(db, appraisal_id, payload)
    return updated


@router.delete('/appraisals/{appraisal_id}')
def delete_appraisal(
    appraisal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Delete an appraisal"""
    success = PerformanceService.delete_appraisal(db, appraisal_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Appraisal not found')
    return {'message': 'Appraisal deleted'}


# ==================== GOAL ENDPOINTS ====================

@router.post('/goals', response_model=GoalPublic)
def create_goal(
    payload: GoalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new goal for self or as HR/manager for others."""
    if payload.employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    goal = GoalService.create_goal(db, payload)
    return GoalPublic.model_validate(goal, from_attributes=True)


@router.get('/goals/{goal_id}', response_model=GoalPublic)
def get_goal(
    goal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific goal"""
    goal = GoalService.get_goal(db, goal_id)
    if not goal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Goal not found')
    
    # Access control
    if goal.employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    return goal


@router.get('/goals/employee/{employee_id}')
def get_employee_goals(
    employee_id: str,
    status: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all goals for an employee"""
    # Access control
    if employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    goals = GoalService.get_goals_for_employee(db, employee_id, status)
    return [GoalPublic.model_validate(g, from_attributes=True) for g in goals]


@router.put('/goals/{goal_id}', response_model=GoalPublic)
def update_goal(
    goal_id: str,
    payload: GoalUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Update a goal"""
    goal = GoalService.get_goal(db, goal_id)
    if not goal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Goal not found')
    
    updated = GoalService.update_goal(db, goal_id, payload)
    return updated


@router.delete('/goals/{goal_id}')
def delete_goal(
    goal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Delete a goal"""
    success = GoalService.delete_goal(db, goal_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Goal not found')
    return {'message': 'Goal deleted'}


# ==================== KPI ENDPOINTS ====================

@router.post('/kpis', response_model=KPIPublic)
def create_kpi(
    payload: KPICreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Create a new KPI"""
    kpi = KPIService.create_kpi(db, payload)
    return kpi


@router.get('/kpis/{kpi_id}', response_model=KPIPublic)
def get_kpi(
    kpi_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific KPI"""
    kpi = KPIService.get_kpi(db, kpi_id)
    if not kpi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='KPI not found')
    
    # Access control
    if kpi.employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    return kpi


@router.get('/kpis/employee/{employee_id}')
def get_employee_kpis(
    employee_id: str,
    status: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all KPIs for an employee"""
    # Access control
    if employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    kpis = KPIService.get_kpis_for_employee(db, employee_id, status)
    return [KPIPublic.model_validate(k, from_attributes=True) for k in kpis]


@router.get('/performance-score/{employee_id}')
def get_performance_score(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get weighted performance score for an employee"""
    # Access control
    if employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    score = KPIService.get_employee_performance_score(db, employee_id)
    return score


@router.put('/kpis/{kpi_id}', response_model=KPIPublic)
def update_kpi(
    kpi_id: str,
    payload: KPIUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Update a KPI"""
    kpi = KPIService.get_kpi(db, kpi_id)
    if not kpi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='KPI not found')
    
    updated = KPIService.update_kpi(db, kpi_id, payload)
    return updated


@router.delete('/kpis/{kpi_id}')
def delete_kpi(
    kpi_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Delete a KPI"""
    success = KPIService.delete_kpi(db, kpi_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='KPI not found')
    return {'message': 'KPI deleted'}


# ==================== TRAINING ENDPOINTS ====================

@router.post('/training/courses', response_model=TrainingCoursePublic)
def create_course(
    payload: TrainingCourseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Create a new training course"""
    course = TrainingService.create_course(db, payload)
    return course


@router.get('/training/courses')
def get_all_courses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all training courses"""
    courses = TrainingService.get_all_courses(db)
    return [TrainingCoursePublic.model_validate(c, from_attributes=True) for c in courses]


@router.post('/training/enrollments', response_model=EmployeeTrainingPublic)
def enroll_employee(
    payload: EmployeeTrainingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Enroll an employee in a training course"""
    training = TrainingService.enroll_employee(db, payload)
    return training


@router.get('/training/enrollments/employee/{employee_id}')
def get_employee_trainings(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all training enrollments for an employee"""
    # Access control
    if employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    trainings = TrainingService.get_trainings_for_employee(db, employee_id)
    return [EmployeeTrainingPublic.model_validate(t, from_attributes=True) for t in trainings]


@router.put('/training/enrollments/{training_id}', response_model=EmployeeTrainingPublic)
def update_training(
    training_id: str,
    payload: EmployeeTrainingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_permissions('manage_performance'))
):
    """Update a training enrollment"""
    training = TrainingService.get_employee_training(db, training_id)
    if not training:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Training not found')
    
    updated = TrainingService.update_training(db, training_id, payload)
    return updated


# ==================== CERTIFICATION ENDPOINTS ====================

@router.post('/certifications', response_model=CertificationPublic)
def create_certification(
    payload: CertificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new certification record"""
    # Allow employee to create their own or HR to create for others
    if payload.employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    cert = CertificationService.create_certification(db, payload)
    is_expired = bool(cert.expiry_date and cert.expiry_date < date.today())
    return CertificationPublic.model_validate(
        {**cert.__dict__, 'is_expired': is_expired},
        from_attributes=True,
    )


@router.get('/certifications/verify/{verification_id}', response_model=CertificationVerifyPublic)
def verify_certification(
    verification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify a certification by its unique verification ID."""
    cert = CertificationService.get_certification_by_verification_id(db, verification_id.upper())
    if not cert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Certification not found')

    is_expired = bool(cert.expiry_date and cert.expiry_date < date.today())
    return CertificationVerifyPublic(
        verification_id=cert.verification_id,
        name=cert.name,
        issuing_authority=cert.issuing_authority,
        issue_date=cert.issue_date,
        expiry_date=cert.expiry_date,
        employee_id=cert.employee_id,
        is_expired=is_expired,
        is_valid=not is_expired,
    )


@router.get('/certifications/employee/{employee_id}')
def get_employee_certifications(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all certifications for an employee"""
    # Access control
    if employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    certs = CertificationService.get_certifications_for_employee(db, employee_id)
    today = date.today()
    return [
        CertificationPublic.model_validate(
            {**c.__dict__, 'is_expired': bool(c.expiry_date and c.expiry_date < today)},
            from_attributes=True,
        )
        for c in certs
    ]


@router.put('/certifications/{cert_id}', response_model=CertificationPublic)
def update_certification(
    cert_id: str,
    payload: CertificationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a certification record"""
    cert = CertificationService.get_certification(db, cert_id)
    if not cert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Certification not found')
    
    # Access control
    if cert.employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    updated = CertificationService.update_certification(db, cert_id, payload)
    return updated


@router.delete('/certifications/{cert_id}')
def delete_certification(
    cert_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a certification record"""
    cert = CertificationService.get_certification(db, cert_id)
    if not cert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Certification not found')
    
    # Access control
    if cert.employee_id != current_user.id and not has_permission(current_user.role, 'manage_performance'):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unauthorized')
    
    success = CertificationService.delete_certification(db, cert_id)
    return {'message': 'Certification deleted'}
