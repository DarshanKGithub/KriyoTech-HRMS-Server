# HRMS Django backend

Django 5.2 API for employees, attendance, leave, payroll, recruitment,
performance, documents, engagement, lifecycle, notifications and subscriptions.

The frontend remains Next.js. Existing API paths, bearer JWT authentication,
Pydantic contracts, SQLAlchemy models and Alembic migrations are retained.
See [DJANGO_MIGRATION.md](DJANGO_MIGRATION.md) for architecture and deployment changes.

## Local setup

Use Python 3.12 or newer.

```sh
python -m venv .venv-local
# Windows: .venv-local\Scripts\activate
# Linux/macOS: source .venv-local/bin/activate
python -m pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and configure database, secrets and allowed hosts.
The default database is SQLite (`sqlite:///./hrms.db`). PostgreSQL is supported
through `DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/hrms`.

For a **new empty database**:

```sh
python manage.py init_hrms
```

For an **existing database**, retain it and apply reviewed Alembic migrations
as described in [README_MIGRATIONS.md](README_MIGRATIONS.md). Web startup does
not modify the schema or seed accounts.

Start the API:

```sh
python manage.py check
python manage.py runserver 0.0.0.0:8000
```

Set the UI's `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

## Demo data

Only on a demo installation, run `python manage.py init_hrms --demo`.
This creates the existing Admin, HR, Manager, Employee and CEO demo accounts.
Demo credentials are for local development only.

## Attendance scheduler

Run one separate process:

```sh
python manage.py run_scheduler
```

## Tests

```sh
python -m pytest
```

Tests use isolated in-memory databases. Root-level manual database/payment
scripts are excluded by `pytest.ini`.

## Production

```sh
python -m uvicorn config.asgi:application --host 0.0.0.0 --port 8000
```

Set deployment-specific `DJANGO_ALLOWED_HOSTS`, `FRONTEND_ORIGINS`,
`DATABASE_URL`, `SECRET_KEY` and `DJANGO_SECRET_KEY`; leave
`DJANGO_DEBUG=false`. WSGI deployments use `config.wsgi:application`.
