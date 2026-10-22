from tests.company_fixtures import company_fixture
import pytest
from app.testing import APIClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import User
from app.core.security import hash_password, create_access_token
from app.http import override_dependencies


@pytest.fixture()
def db_session():
    engine = create_engine(
        'sqlite://',
        future=True,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()

    admin = User(full_name='Admin User', email='admin@test.com', role='Admin', password_hash=hash_password('password'))
    session.add(admin)
    company_fixture(session)
    session.commit()

    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        return db_session


    with override_dependencies({get_db: override_get_db}):
        test_client = APIClient()
        yield test_client



def auth_headers():
    token = create_access_token({'sub': 'admin@test.com'})
    return {'Authorization': f'Bearer {token}'}


def test_recruitment_ats_flow(client):
    job_response = client.post(
        '/recruitment/jobs',
        headers=auth_headers(),
        json={
            'title': 'Platform Engineer',
            'description': 'Build reliable internal platforms',
            'location': 'Remote',
            'employment_type': 'Full-time',
            'status': 'Open',
        },
    )
    assert job_response.status_code == 200
    job = job_response.json()

    candidate_response = client.post(
        '/recruitment/candidates',
        headers=auth_headers(),
        json={
            'first_name': 'Asha',
            'last_name': 'Patel',
            'email': 'asha@test.com',
            'resume_text': 'Python FastAPI React Docker AWS',
            'source': 'Website',
        },
    )
    assert candidate_response.status_code == 200
    candidate = candidate_response.json()
    assert 'python' in (candidate.get('parsed_skills') or '').lower()

    parse_response = client.post(
        '/recruitment/candidates/parse-resume',
        headers=auth_headers(),
        json={'resume_text': 'JavaScript, React and TypeScript developer'},
    )
    assert parse_response.status_code == 200
    assert 'react' in parse_response.json()['parsed_skills']

    application_response = client.post(
        '/recruitment/applications',
        headers=auth_headers(),
        json={
            'job_id': job['id'],
            'candidate_id': candidate['id'],
            'status': 'Applied',
        },
    )
    assert application_response.status_code == 200
    application = application_response.json()

    update_application_response = client.put(
        f"/recruitment/applications/{application['id']}/status",
        headers=auth_headers(),
        json={'status': 'Interviewing'},
    )
    assert update_application_response.status_code == 200
    assert update_application_response.json()['status'] == 'Interviewing'

    interviewer = client.get('/auth/me', headers=auth_headers())
    assert interviewer.status_code == 200
    interviewer_id = interviewer.json()['id']

    interview_response = client.post(
        '/recruitment/interviews',
        headers=auth_headers(),
        json={
            'application_id': application['id'],
            'interviewer_id': interviewer_id,
            'scheduled_at': '2026-05-09T10:30:00Z',
            'meeting_link': 'https://meet.example.com/interview',
        },
    )
    assert interview_response.status_code == 200
    interview = interview_response.json()

    update_interview_response = client.put(
        f"/recruitment/interviews/{interview['id']}/status",
        headers=auth_headers(),
        json={'status': 'Completed', 'feedback': 'Strong hire', 'rating': 5},
    )
    assert update_interview_response.status_code == 200
    assert update_interview_response.json()['status'] == 'Completed'

    jobs_list_response = client.get('/recruitment/jobs', headers=auth_headers())
    assert jobs_list_response.status_code == 200
    assert jobs_list_response.json()['total'] >= 1
