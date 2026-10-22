"""Back up the configured PostgreSQL database without exposing credentials."""
import os
from pathlib import Path
import subprocess
from datetime import datetime
from sqlalchemy.engine import make_url
from app.core.config import settings

url = make_url(settings.sqlalchemy_database_url)
if url.get_backend_name() != 'postgresql':
    raise RuntimeError('This backup command requires PostgreSQL')
folder = Path('.venv-local/backups')
folder.mkdir(parents=True, exist_ok=True)
output = folder / f'pre-core-upgrade-{datetime.now():%Y%m%d-%H%M%S}.dump'
bin_dir = Path(r'C:\Program Files\PostgreSQL\18\bin')
env = dict(os.environ, PGPASSWORD=url.password or '')
args = ['--host', url.host or 'localhost', '--port', str(url.port or 5432), '--username', url.username or 'postgres', '--dbname', url.database]
subprocess.run([str(bin_dir / 'pg_dump.exe'), *args, '--format=custom', '--file', str(output)], env=env, check=True, capture_output=True)
result = subprocess.run([str(bin_dir / 'pg_restore.exe'), '--list', str(output)], check=True, capture_output=True)
print(f'Backup verified: {output.resolve()} ({output.stat().st_size} bytes; {len(result.stdout.splitlines())} catalog lines)')
