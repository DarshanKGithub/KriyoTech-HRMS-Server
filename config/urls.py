from importlib import import_module

from django.http import JsonResponse
from django.urls import path
from django.views.static import serve
from django.conf import settings

from app.http import url_patterns

ROUTERS = [
    ('auth', '/auth'), ('org', '/org'), ('employees', '/employees'),
    ('dashboard', '/dashboard'), ('attendance', '/attendance'),
    ('advanced_attendance', '/advanced-attendance'), ('leave', '/leave'),
    ('payroll', '/payroll'), ('engagement', '/engagement'), ('performance', ''),
    ('todo', '/todo'), ('recruitment', '/recruitment'), ('financials', '/financials'),
    ('notifications', '/notifications'), ('workflow', '/workflow'),
    ('documents', '/documents'), ('lifecycle', '/lifecycle'),
    ('admin', '/admin'), ('billing', '/billing'), ('tenants', '/tenants'),
    ('webhooks', '/api/webhooks'),
]

urlpatterns = [
    path('uploads/avatars/<path:path>', serve, {'document_root': settings.BASE_DIR / 'uploads' / 'avatars'}),
    path('', lambda request: JsonResponse({'message': 'HRMS API is running'})),
    path('health', lambda request: JsonResponse({'status': 'ok'})),
    path('health/', lambda request: JsonResponse({'status': 'ok'})),
] + url_patterns([(prefix, import_module(f'app.api.routes.{name}').router) for name, prefix in ROUTERS])


def not_found(request, exception):
    return JsonResponse({'detail': 'Not found'}, status=404)


handler404 = not_found
