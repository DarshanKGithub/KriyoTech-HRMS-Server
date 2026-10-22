from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.http import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Candidate, Interview, JobApplication, JobPosting
from app.schemas.recruitment import (
    CandidateCreate,
    InterviewCreate,
    InterviewStatusUpdate,
    JobApplicationCreate,
    JobApplicationStatusUpdate,
    JobPostingCreate,
    JobPostingUpdate,
    ResumeParseRequest,
)

SKILL_KEYWORDS: tuple[str, ...] = (
    'python',
    'java',
    'javascript',
    'typescript',
    'react',
    'next.js',
    'fastapi',
    'django',
    'sql',
    'postgres',
    'mysql',
    'mongodb',
    'aws',
    'azure',
    'docker',
    'kubernetes',
    'git',
    'html',
    'css',
    'rest api',
    'leadership',
    'communication',
)


def _touch(record):
    if hasattr(record, 'updated_at'):
        record.updated_at = datetime.now(timezone.utc)
    return record


def _to_public(obj):
    return obj


def create_job_posting(payload: JobPostingCreate, db: Session) -> JobPosting:
    job = JobPosting(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_job_postings(db: Session, status: str | None = None, page: int = 1, size: int = 20):
    query = db.query(JobPosting)
    if status:
        query = query.filter(JobPosting.status == status)
    total = query.count()
    items = query.order_by(JobPosting.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return items, total


def update_job_posting(job_id: str, payload: JobPostingUpdate, db: Session) -> JobPosting:
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail='Job posting not found')

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_candidate(payload: CandidateCreate, db: Session) -> Candidate:
    data = payload.model_dump(exclude={'resume_text'})
    resume_text = (payload.resume_text or '').strip()
    if resume_text and not data.get('parsed_skills'):
        parsed = parse_resume_text(resume_text)
        data['parsed_skills'] = ', '.join(parsed.parsed_skills)
    candidate = Candidate(**data)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def list_candidates(db: Session):
    return db.query(Candidate).order_by(Candidate.created_at.desc()).all()


def create_job_application(payload: JobApplicationCreate, db: Session) -> JobApplication:
    job = db.query(JobPosting).filter(JobPosting.id == payload.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail='Job posting not found')

    candidate = db.query(Candidate).filter(Candidate.id == payload.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail='Candidate not found')

    application = JobApplication(**payload.model_dump())
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def list_applications(db: Session, job_id: str | None = None):
    query = db.query(JobApplication)
    if job_id:
        query = query.filter(JobApplication.job_id == job_id)
    return query.order_by(JobApplication.applied_at.desc()).all()


def update_application_status(application_id: str, payload: JobApplicationStatusUpdate, db: Session) -> JobApplication:
    application = db.query(JobApplication).filter(JobApplication.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail='Application not found')
    application.status = payload.status
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def schedule_interview(payload: InterviewCreate, db: Session) -> Interview:
    application = db.query(JobApplication).filter(JobApplication.id == payload.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail='Application not found')

    interview = Interview(**payload.model_dump(), status='Scheduled')
    db.add(interview)
    db.commit()
    db.refresh(interview)
    return interview


def list_interviews(db: Session):
    return db.query(Interview).order_by(Interview.created_at.desc()).all()


def update_interview_status(interview_id: str, payload: InterviewStatusUpdate, db: Session) -> Interview:
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail='Interview not found')
    interview.status = payload.status
    if payload.feedback is not None:
        interview.feedback = payload.feedback
    if payload.rating is not None:
        interview.rating = payload.rating
    db.add(interview)
    db.commit()
    db.refresh(interview)
    return interview


def parse_resume_text(resume_text: str):
    normalized = resume_text.lower()
    found: list[str] = []
    for keyword in SKILL_KEYWORDS:
        if keyword in normalized and keyword not in found:
            found.append(keyword)

    summary = 'Found skills: ' + ', '.join(found) if found else 'No predefined skills matched the resume text.'
    return type('ResumeParseResult', (), {'parsed_skills': found, 'summary': summary})()


def create_candidate_from_resume(payload: ResumeParseRequest, db: Session):
    parsed = parse_resume_text(payload.resume_text)
    return parsed
