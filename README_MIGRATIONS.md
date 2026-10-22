# HRMS database migrations

Django serves the API, while SQLAlchemy and Alembic continue to own the existing
HRMS schema. Run commands from this backend directory.

Install `requirements.txt` and set `DATABASE_URL` in the environment.
Back up an existing database before applying schema upgrades.

```sh
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini upgrade head
```

The application does not modify the schema during Django web startup.
`AUTO_APPLY_SCHEMA_CHANGES` is no longer a startup setting.

For a new empty database use `python manage.py init_hrms`.
Existing installations use the migration history already associated with their
database. Review that history before stamping a newly created database.

Django's `migrate` and `makemigrations` do not manage the SQLAlchemy HRMS tables.
Production deployments should run Alembic as a separate release step before
starting `config.asgi:application` or `config.wsgi:application`.
