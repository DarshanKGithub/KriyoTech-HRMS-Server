"""Django test client with JSON/query conveniences for API contract tests."""
import os
from urllib.parse import urlencode

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.test import Client


class APIClient(Client):
    def _api_request(self, method, path, *, json=None, params=None, headers=None, **kwargs):
        if params:
            path += ('&' if '?' in path else '?') + urlencode(params, doseq=True)
        if json is not None:
            kwargs['data'] = json
            kwargs['content_type'] = 'application/json'
        return getattr(super(), method)(path, headers=headers, **kwargs)

    def get(self, path, **kwargs):
        return self._api_request('get', path, **kwargs)

    def post(self, path, **kwargs):
        return self._api_request('post', path, **kwargs)

    def put(self, path, **kwargs):
        return self._api_request('put', path, **kwargs)

    def patch(self, path, **kwargs):
        return self._api_request('patch', path, **kwargs)

    def delete(self, path, **kwargs):
        return self._api_request('delete', path, **kwargs)
