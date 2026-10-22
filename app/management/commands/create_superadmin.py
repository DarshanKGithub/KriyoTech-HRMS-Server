"""Provision a platform Super Admin without changing an existing account."""
import getpass
import secrets
import string

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from sqlalchemy import select

from app.core.security import hash_password
from app.db.database import SessionLocal
from app.db.models import User


class Command(BaseCommand):
    help = 'Create a KriyoHR platform Super Admin account (not a Django auth user).'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--name', default='KriyoHR Super Admin')
        parser.add_argument('--generate-password', action='store_true')

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        name = options['name'].strip()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError('Enter a valid email address.') from exc
        if not name or len(name) > 120:
            raise CommandError('Name must contain between 1 and 120 characters.')

        with SessionLocal() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise CommandError('An account already exists with this email; it was not modified.')
            if options['generate_password']:
                alphabet = string.ascii_letters + string.digits + '!@#%_-'
                password = ''.join(secrets.choice(alphabet) for _ in range(24))
            else:
                password = getpass.getpass('Password: ')
                if password != getpass.getpass('Confirm password: '):
                    raise CommandError('Passwords do not match.')
            if len(password) < 12:
                raise CommandError('Use a password with at least 12 characters.')

            db.add(User(
                full_name=name,
                email=email,
                password_hash=hash_password(password),
                role='Super Admin',
                tenant_id=None,
                is_active=True,
            ))
            db.commit()

        self.stdout.write(self.style.SUCCESS('Super Admin account created.'))
        self.stdout.write(f'Email: {email}')
        if options['generate_password']:
            self.stdout.write(f'Password: {password}')
