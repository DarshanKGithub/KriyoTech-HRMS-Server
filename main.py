"""Run the Django development server (production: config.asgi:application)."""
import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line([sys.argv[0], 'runserver', '0.0.0.0:8000', *sys.argv[1:]])
