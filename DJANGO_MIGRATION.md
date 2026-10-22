# Django migration

The API is served by Django 5.2. FastAPI and Starlette are no longer runtime
dependencies. `manage.py`, `config.settings`, `config.urls`, and the WSGI/ASGI
applications are the entry points.

## Scope and compatibility

All 231 existing endpoint registrations remain in the 21 API route modules.
`app.http.Router` compiles their typed handlers into Django URL patterns/views.
The adapter validates JSON/query/form inputs with the existing Pydantic schemas,
resolves authorization and request-scoped database dependencies, serializes
responses, and maps domain errors to JSON. API paths accept both trailing-slash
forms without redirects, including POST requests.

JWT login, bearer headers, response schemas, and the Next.js API base URL remain
compatible. Django handles multipart uploads and binary file responses. The two
payment webhooks read native Django request bytes for signature validation.
The API does not use cookie authentication; its bearer-token views are CSRF
exempt. Django CSRF middleware remains enabled for future cookie-based views.

SQLAlchemy models, the existing database, and Alembic migrations are retained.
This is a Django HTTP/runtime migration, **not a conversion to Django ORM or
Django admin**. Retaining persistence avoids recreating the HRMS tables and
rewriting all business services. Do not run Django's `makemigrations` against
these SQLAlchemy models.

## Startup changes

Web startup no longer creates tables, applies schema repairs, seeds demo users,
or starts a scheduler in every worker. Use `manage.py init_hrms` for a new
database, `alembic upgrade head` for existing database upgrades, and
`manage.py init_hrms --demo` only for an explicitly requested demo installation.
No existing database is changed by this code migration.

Run exactly one `python manage.py run_scheduler` process for attendance
auto-checkout. Its 23:59 schedule uses `TIME_ZONE` (default `Asia/Kolkata`),
independently of the number of Django web workers.

Only avatars retain public `/uploads/avatars/...` serving. Employee documents
and leave attachments must use their API endpoints rather than a public static
mount of the whole uploads directory.

## Deployment

Development: `python manage.py runserver 0.0.0.0:8000`.
ASGI: `python -m uvicorn config.asgi:application --host 0.0.0.0 --port 8000`.
WSGI servers can use `config.wsgi:application`.
The old ASGI import `app.main:app` also points to Django.

Set `DJANGO_ALLOWED_HOSTS`, `FRONTEND_ORIGINS`, `SECRET_KEY` (JWT),
`DJANGO_SECRET_KEY`, and `DATABASE_URL` in the deployment environment.
Keep `DJANGO_DEBUG=false` in production. Changing `SECRET_KEY` invalidates
existing JWTs; keep its current deployment value when preserving sessions.

## Checks

```sh
python -m pip install -r requirements-dev.txt
python manage.py check
python -m pytest
```

Pytest collects `tests/` only. The root-level manual scripts include real
database/payment operations and are deliberately excluded from automated
collection. API tests now use Django's test client and scoped dependency
overrides against in-memory SQLite. They do not seed the local HRMS database.

Existing tenant-isolation and authorization limitations in business services
still require a separate security review; changing the web framework alone
does not resolve them.
