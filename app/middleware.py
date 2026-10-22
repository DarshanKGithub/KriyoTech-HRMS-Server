from django.http import HttpResponse
from django.utils.cache import patch_vary_headers

from app.core.config import settings


class ApiCorsMiddleware:
    """Allow the existing separate Next.js frontend to call bearer-token APIs."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get('Origin')
        allowed = origin in settings.cors_origins
        preflight = request.method == 'OPTIONS' and 'Access-Control-Request-Method' in request.headers
        response = HttpResponse(status=204 if allowed else 403) if preflight else self.get_response(request)
        if allowed:
            response['Access-Control-Allow-Origin'] = origin
            response['Access-Control-Allow-Credentials'] = 'true'
            if preflight:
                response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS'
                response['Access-Control-Allow-Headers'] = request.headers.get('Access-Control-Request-Headers', 'Authorization, Content-Type')
                response['Access-Control-Max-Age'] = '600'
        patch_vary_headers(response, ['Origin'])
        return response
