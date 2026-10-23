"""Run isolated PostgreSQL, SMTP, Django, mail worker and browser acceptance."""
import json,os,re,shutil,subprocess,sys,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from urllib.request import urlopen
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from app.core.config import settings
from tests.mailbox import mailbox

ROOT=Path(__file__).resolve().parents[1]
UI=Path(os.environ.get('HRMS_UI_PATH',str(ROOT.parent/'AviCorex-HRMS-UI'))).resolve()
LOGS=ROOT/'.venv-local'/'release-acceptance';LOGS.mkdir(parents=True,exist_ok=True)
node=shutil.which('node')
if not node: raise RuntimeError('Node.js is required')
url=make_url(settings.sqlalchemy_database_url)
if url.get_backend_name()!='postgresql': raise RuntimeError('Release acceptance requires PostgreSQL')
schema='hrms_release_'+uuid4().hex
engine=create_engine(url)
processes=[];logs=[];fixture=None

def launch(args,env,cwd,label):
    log=open(LOGS/(label+'.log'),'w');logs.append(log)
    process=subprocess.Popen(args,env=env,cwd=cwd,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    processes.append(process);return process

def ready(address):
    for _ in range(90):
        try:
            with urlopen(address,timeout=1) as response:
                if response.status==200:return
        except OSError:time.sleep(.5)
    raise RuntimeError('Acceptance service did not start: '+address)

with engine.begin() as conn:conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
try:
    scoped=url.update_query_dict({'options':f'-csearch_path={schema}'}).render_as_string(hide_password=False)
    os.environ['HRMS_TEST_DATABASE_URL']=scoped
    from tests.test_core_hr_journey import api,auth
    from app.db.models import Attendance
    from datetime import date
    fixture=api.__wrapped__();client,db=next(fixture)
    salary=client.post('/financials/salary-structures',headers=auth('a-hr'),json={'employee_id':'a-employee','base_salary':22000,'hra':0,'da':0,'special_allowance':0,'pf_percentage':0,'esi_percentage':0,'tax_bracket_percentage':0,'effective_from':'2026-09-01'})
    if salary.status_code!=200:raise RuntimeError('Acceptance salary fixture failed')
    db.info.pop('actor',None);db.add(Attendance(tenant_id='a',employee_id='a-employee',attendance_date=date(2026,9,1),status='present',is_half_day=True));db.commit()
    with mailbox() as smtp:
        class Inbox(BaseHTTPRequestHandler):
            def do_GET(self):
                if urlparse(self.path).path!='/messages':self.send_error(404);return
                recipient=parse_qs(urlparse(self.path).query).get('to',[None])[0]
                body=json.dumps([message for message in smtp.messages if recipient is None or message['to']==recipient]).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        inbox=ThreadingHTTPServer(('127.0.0.1',8025),Inbox)
        thread=threading.Thread(target=inbox.serve_forever,daemon=True);thread.start()
        try:
            env=dict(os.environ,DATABASE_URL=scoped,SECRET_KEY=settings.secret_key,FRONTEND_ORIGINS='http://localhost:3011',PUBLIC_APP_URL='http://localhost:3011',MAIL_TRANSPORT='smtp',SMTP_SERVER='127.0.0.1',SMTP_PORT=str(smtp.server_address[1]),SMTP_USERNAME='',SMTP_PASSWORD='',SMTP_FROM='test@kriyohr.local',SMTP_USE_TLS='false',SMTP_ALLOW_INSECURE_LOOPBACK='true',UPLOAD_ROOT=str(LOGS/'uploads'),PYTHONDONTWRITEBYTECODE='1')
            launch([sys.executable,'-B','-u','manage.py','runserver','127.0.0.1:8001','--noreload'],env,ROOT,'django')
            ready('http://127.0.0.1:8001/health')
            launch([sys.executable,'-B','-u','manage.py','run_mail_worker'],env,ROOT,'mail-worker')
            ui_env=dict(os.environ,NEXT_BUILD_DIR=os.environ.get('NEXT_BUILD_DIR','.next-release-preview'))
            launch([node,'node_modules/next/dist/bin/next','start','-H','localhost','-p','3011'],ui_env,UI,'next')
            ready('http://localhost:3011/login')
            browser_env=dict(os.environ)
            if os.name=='nt' and not browser_env.get('E2E_CHROMIUM_PATH'):browser_env['E2E_CHROMIUM_PATH']=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
            regression=subprocess.run([node,'node_modules/@playwright/test/cli.js','test','-c','playwright.enterprise.config.ts'],env=browser_env,cwd=UI)
            if regression.returncode:raise SystemExit(regression.returncode)
            result=subprocess.run([node,'node_modules/@playwright/test/cli.js','test','-c','playwright.release.config.ts'],env=browser_env,cwd=UI)
            raise SystemExit(result.returncode)
        finally:inbox.shutdown();inbox.server_close();thread.join(timeout=5)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
            else:process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    for log in logs:log.close()
    if fixture:fixture.close()
    if not re.fullmatch(r'hrms_release_[a-f0-9]{32}',schema):raise RuntimeError('Invalid cleanup schema')
    with engine.begin() as conn:conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    engine.dispose();print('Release acceptance services stopped; temporary database schema removed')
