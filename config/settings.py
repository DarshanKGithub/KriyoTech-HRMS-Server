import os
from pathlib import Path

from app.core.config import settings as api_settings

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', api_settings.secret_key)
DEBUG = os.getenv('DJANGO_DEBUG', 'false').lower() in ('true', '1', 'yes')
ALLOWED_HOSTS = [host.strip() for host in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],testserver').split(',') if host.strip()]
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'
INSTALLED_APPS = ['app.apps.HrmsConfig']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'app.middleware.ApiCorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
# SQLAlchemy/Alembic continue to own the existing HRMS database and schema.
DATABASES = {}
APPEND_SLASH = False
USE_TZ = True
TIME_ZONE = os.getenv('TIME_ZONE', 'Asia/Kolkata')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
