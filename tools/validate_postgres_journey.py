"""Run the real API journey in an isolated, temporary PostgreSQL schema."""
import os
import subprocess
import sys
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from app.core.config import settings

url = make_url(settings.sqlalchemy_database_url)
schema = 'hrms_validation_' + uuid4().hex
engine = create_engine(url)
with engine.begin() as conn:
    conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
try:
    test_url = url.update_query_dict({'options': f'-csearch_path={schema}'})
    env = dict(os.environ, HRMS_TEST_DATABASE_URL=test_url.render_as_string(hide_password=False))
    result = subprocess.run([sys.executable, '-B', '-m', 'pytest', 'tests/test_core_hr_journey.py', '-q', '--tb=short', '-p', 'no:warnings', '--basetemp=.pytest_cache/postgres-core'], env=env)
    raise SystemExit(result.returncode)
finally:
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    engine.dispose()
    print('Temporary validation schema removed')
