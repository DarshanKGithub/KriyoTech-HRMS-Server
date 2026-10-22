from app.http import Router, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.rbac import get_current_user, require_permissions
from app.db.database import get_db
from app.db.models import User
from app.schemas.recruitment import (
    JobPostingCreate, JobPostingPublic, PaginatedJobPostings,
    CandidateCreate, CandidatePublic,
    JobApplicationCreate, JobApplicationPublic,
    InterviewCreate, InterviewPublic,
    JobPostingUpdate, JobApplicationStatusUpdate, InterviewStatusUpdate,
    ResumeParseRequest, ResumeParseResponse,
)
from app.services.recruitment_service import (
    create_job_posting as create_job_posting_service,
    list_job_postings as list_job_postings_service,
    update_job_posting as update_job_posting_service,
    create_candidate as create_candidate_service,
    list_candidates as list_candidates_service,
    create_job_application as create_job_application_service,
    list_applications as list_applications_service,
    update_application_status as update_application_status_service,
    schedule_interview as schedule_interview_service,
    list_interviews as list_interviews_service,
    update_interview_status as update_interview_status_service,
    parse_resume_text,
)

router = Router()

# --- Job Postings ---

@router.post('/jobs', response_model=JobPostingPublic)
def create_job_posting(
    payload: JobPostingCreate,
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    job = create_job_posting_service(payload, db)
    return JobPostingPublic.model_validate(job, from_attributes=True)

@router.get('/jobs', response_model=PaginatedJobPostings)
def list_jobs(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user), # Any logged-in user can see jobs
    db: Session = Depends(get_db)
):
    items, total = list_job_postings_service(db=db, status=status, page=page, size=size)
    return PaginatedJobPostings(
        items=[JobPostingPublic.model_validate(i, from_attributes=True) for i in items],
        total=total,
        page=page,
        size=size
    )


@router.put('/jobs/{job_id}', response_model=JobPostingPublic)
def edit_job_posting(
    job_id: str,
    payload: JobPostingUpdate,
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    job = update_job_posting_service(job_id, payload, db)
    return JobPostingPublic.model_validate(job, from_attributes=True)

# --- Candidates ---

@router.post('/candidates', response_model=CandidatePublic)
def add_candidate(
    payload: CandidateCreate,
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    candidate = create_candidate_service(payload, db)
    return CandidatePublic.model_validate(candidate, from_attributes=True)

@router.get('/candidates', response_model=list[CandidatePublic])
def list_candidates(
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    items = list_candidates_service(db)
    return [CandidatePublic.model_validate(i, from_attributes=True) for i in items]


@router.post('/candidates/parse-resume', response_model=ResumeParseResponse)
def parse_resume(
    payload: ResumeParseRequest,
    user: User = Depends(require_permissions('manage_recruitment')),
):
    parsed = parse_resume_text(payload.resume_text)
    return ResumeParseResponse(parsed_skills=parsed.parsed_skills, summary=parsed.summary)

# --- Applications ---

@router.post('/applications', response_model=JobApplicationPublic)
def apply_job(
    payload: JobApplicationCreate,
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    app = create_job_application_service(payload, db)
    return JobApplicationPublic.model_validate(app, from_attributes=True)

@router.get('/applications', response_model=list[JobApplicationPublic])
def list_applications(
    job_id: Optional[str] = Query(None),
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    items = list_applications_service(db, job_id=job_id)
    return [JobApplicationPublic.model_validate(i, from_attributes=True) for i in items]


@router.put('/applications/{application_id}/status', response_model=JobApplicationPublic)
def update_application(
    application_id: str,
    payload: JobApplicationStatusUpdate,
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    app = update_application_status_service(application_id, payload, db)
    return JobApplicationPublic.model_validate(app, from_attributes=True)

# --- Interviews ---

@router.post('/interviews', response_model=InterviewPublic)
def schedule_interview(
    payload: InterviewCreate,
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    interview = schedule_interview_service(payload, db)
    return InterviewPublic.model_validate(interview, from_attributes=True)


@router.get('/interviews', response_model=list[InterviewPublic])
def get_interviews(
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    items = list_interviews_service(db)
    return [InterviewPublic.model_validate(i, from_attributes=True) for i in items]


@router.put('/interviews/{interview_id}/status', response_model=InterviewPublic)
def change_interview_status(
    interview_id: str,
    payload: InterviewStatusUpdate,
    user: User = Depends(require_permissions('manage_recruitment')),
    db: Session = Depends(get_db)
):
    interview = update_interview_status_service(interview_id, payload, db)
    return InterviewPublic.model_validate(interview, from_attributes=True)
