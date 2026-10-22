"""Launch an isolated PostgreSQL/Django server for the real browser journey."""
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from app.core.config import settings

url = make_url(settings.sqlalchemy_database_url)
schema = 'hrms_browser_' + uuid4().hex
engine = create_engine(url)
with engine.begin() as conn:
    conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
process = None
fixture = None
try:
    database = url.update_query_dict({'options': f'-csearch_path={schema}'}).render_as_string(hide_password=False)
    os.environ['HRMS_TEST_DATABASE_URL'] = database
    from tests.test_core_hr_journey import api, auth
    from app.db.models import Attendance
    from datetime import date
    fixture = api.__wrapped__()
    client, db = next(fixture)
    response = client.post('/financials/salary-structures', headers=auth('a-hr'), json={'employee_id':'a-employee','base_salary':22000,'hra':0,'da':0,'special_allowance':0,'pf_percentage':0,'esi_percentage':0,'tax_bracket_percentage':0,'effective_from':'2026-09-01'})
    assert response.status_code == 200, response.content
    db.info.pop('actor',None)
    db.add(Attendance(tenant_id='a',employee_id='a-employee',attendance_date=date(2026,9,1),status='present',is_half_day=True))
    db.commit()
    env = dict(os.environ, DATABASE_URL=database, FRONTEND_ORIGINS='http://localhost:3011')
    with open('.venv-local/browser-django.log','w') as log:
        process = subprocess.Popen([sys.executable,'-B','-u','manage.py','runserver','127.0.0.1:8001','--noreload'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(60):
            try:
                with urlopen('http://127.0.0.1:8001/health',timeout=1) as response:
                    if response.status == 200: break
            except OSError: time.sleep(.5)
        else: raise RuntimeError('Isolated Django server did not become ready')
        env['E2E_CHROMIUM_PATH'] = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
        result = subprocess.run([r'C:\Program Files\nodejs\node.exe','node_modules/@playwright/test/cli.js','test','-c','playwright.core.config.ts'],cwd=Path.cwd().parent/'AviCorex-HRMS-UI',env=env)
        raise SystemExit(result.returncode)
finally:
    if process:
        # Terminate the venv launcher and its Python child as one verified process tree.
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
        process.wait(timeout=10)
    if fixture: fixture.close()
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    engine.dispose()
    print('Isolated browser server and schema removed')
