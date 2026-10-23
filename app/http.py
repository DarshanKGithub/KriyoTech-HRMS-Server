"""Django view adapters for the existing typed API handlers.

Django owns routing, middleware, requests and responses. Pydantic validates the
existing API contract; request-scoped dependencies keep SQLAlchemy sessions and
authorization shared between handlers without rewriting the business services.
"""
import inspect
import json
import logging
import re
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from http import HTTPStatus
from types import SimpleNamespace
from typing import Annotated, Any, get_origin, get_type_hints

from asgiref.sync import async_to_sync
from django.http import (
    FileResponse as DjangoFileResponse, HttpRequest, HttpResponseBase,
    JsonResponse, StreamingHttpResponse,
)
from django.urls import re_path
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python
from sqlalchemy.inspection import inspect as sa_inspect

logger = logging.getLogger(__name__)
status = SimpleNamespace(**{f'HTTP_{item.value}_{item.name}': item.value for item in HTTPStatus})
Request = HttpRequest


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: Any = None, headers=None):
        self.status_code, self.detail, self.headers = status_code, detail, headers or {}
        super().__init__(str(detail))


@dataclass(frozen=True)
class Depends:
    dependency: Any


@dataclass
class Parameter:
    source: str
    default: Any = ...
    constraints: dict | None = None


def Query(default=..., **kwargs):
    return Parameter('query', default, kwargs)


def File(default=..., **kwargs):
    return Parameter('file', default, kwargs)


def Form(default=..., **kwargs):
    return Parameter('form', default, kwargs)


@dataclass
class HTTPAuthorizationCredentials:
    scheme: str
    credentials: str


class HTTPBearer:
    def __init__(self, auto_error=True):
        self.auto_error = auto_error

    def __call__(self, request: HttpRequest):
        scheme, _, token = request.headers.get('Authorization', '').partition(' ')
        if scheme.lower() == 'bearer' and token.strip():
            return HTTPAuthorizationCredentials(scheme, token.strip())
        if self.auto_error:
            raise HTTPException(401, 'Not authenticated', {'WWW-Authenticate': 'Bearer'})
        return None


class UploadFile:
    """Bridge Django UploadedFile to existing synchronous/async file services."""
    def __init__(self, uploaded):
        self.file = uploaded
        self.filename = uploaded.name
        self.content_type = uploaded.content_type

    async def read(self, size=-1):
        return self.file.read(size)


def FileResponse(path, filename=None, media_type=None, headers=None):
    return DjangoFileResponse(
        (path if hasattr(path, 'read') else open(path, 'rb')), as_attachment=True, filename=filename or '',
        content_type=media_type, headers=headers,
    )


def StreamingResponse(content, media_type=None, headers=None):
    return StreamingHttpResponse(content, content_type=media_type, headers=headers)


_overrides = ContextVar('api_dependency_overrides', default={})


@contextmanager
def override_dependencies(mapping):
    """Scoped overrides for Django API tests; never shared across requests."""
    token = _overrides.set({**_overrides.get(), **mapping})
    try:
        yield
    finally:
        _overrides.reset(token)


class BindingError(Exception):
    def __init__(self, errors):
        self.errors = errors


class Resolver:
    def __init__(self, request, path_params, stack):
        self.request, self.path_params, self.stack = request, path_params, stack
        self.cache = {}
        self.payload = ...

    def body(self):
        if self.payload is ...:
            try:
                self.payload = json.loads(self.request.body)
            except (ValueError, UnicodeDecodeError):
                raise BindingError([{'loc': ['body'], 'msg': 'Invalid JSON', 'type': 'json_invalid'}])
        return self.payload

    def rollback(self):
        from sqlalchemy.orm import Session
        for value in self.cache.values():
            if isinstance(value,Session): value.rollback()

    def call(self, func, dependency=False):
        original = func
        if dependency and original in self.cache:
            return self.cache[original]
        func = _overrides.get().get(func, func)
        target = func if inspect.isfunction(func) else func.__call__
        hints = get_type_hints(target)
        kwargs = {}
        for name, param in inspect.signature(func).parameters.items():
            annotation = hints.get(name, Any)
            default = param.default
            if isinstance(default, Depends):
                kwargs[name] = self.call(default.dependency, dependency=True)
                continue
            if annotation is HttpRequest:
                kwargs[name] = self.request
                continue
            marker = default if isinstance(default, Parameter) else None
            source = marker.source if marker else ('path' if name in self.path_params else 'query')
            if marker and source == 'file':
                uploaded = self.request.FILES.get(name)
                if uploaded is not None:
                    kwargs[name] = UploadFile(uploaded)
                    continue
                value = ...
            elif source == 'form':
                value = self.request.POST.get(name, ...)
            elif source == 'path':
                value = self.path_params[name]
            elif annotation is dict or get_origin(annotation) in (dict, list) or (
                inspect.isclass(annotation) and issubclass(annotation, BaseModel)
            ):
                source, value = 'body', self.body()
            else:
                value = self.request.GET.get(name, ...)
            fallback = marker.default if marker else default
            if value is ...:
                if fallback is not ... and fallback is not inspect.Parameter.empty:
                    kwargs[name] = fallback
                    continue
                raise BindingError([{'loc': [source, name], 'msg': 'Field required', 'type': 'missing'}])
            try:
                if marker and marker.constraints:
                    annotation = Annotated[annotation, Field(**marker.constraints)]
                kwargs[name] = TypeAdapter(annotation).validate_python(value)
            except ValidationError as exc:
                errors = exc.errors(include_url=False, include_context=False, include_input=False)
                for error in errors:
                    error['loc'] = [source, name, *error['loc']]
                raise BindingError(errors) from exc
        if inspect.isgeneratorfunction(func):
            result = self.stack.enter_context(contextmanager(func)(**kwargs))
        elif inspect.iscoroutinefunction(func):
            result = async_to_sync(func)(**kwargs)
        else:
            result = func(**kwargs)
        if dependency:
            self.cache[original] = result
        return result


def serialize(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize(item) for item in value]
    mapper = sa_inspect(value, raiseerr=False) if value is not None else None
    if mapper is not None and hasattr(mapper, 'mapper'):
        return {col.key: serialize(getattr(value, col.key)) for col in mapper.mapper.column_attrs}
    return to_jsonable_python(value)


class Router:
    def __init__(self, prefix='', tags=None):
        self.prefix = prefix
        self.routes = []

    def route(self, method, path, response_model=None, status_code=200, **options):
        def decorator(handler):
            self.routes.append((method, self.prefix + path, handler, response_model, status_code))
            return handler
        return decorator

    def get(self, path, **options):
        return self.route('GET', path, **options)

    def post(self, path, **options):
        return self.route('POST', path, **options)

    def put(self, path, **options):
        return self.route('PUT', path, **options)

    def patch(self, path, **options):
        return self.route('PATCH', path, **options)

    def delete(self, path, **options):
        return self.route('DELETE', path, **options)


def url_patterns(routers):
    """Group methods by URL so Django can return 405 and an accurate Allow header."""
    grouped = {}
    for prefix, router in routers:
        for method, path, handler, model, code in router.routes:
            full_path = (prefix + path).strip('/')
            grouped.setdefault(full_path, {})[method] = (handler, model, code)

    def make_view(methods):
        # These APIs authenticate explicit Authorization headers, never cookies.
        @csrf_exempt
        def view(request, **path_params):
            method = 'GET' if request.method == 'HEAD' else request.method
            if method not in methods:
                response = JsonResponse({'detail': 'Method not allowed'}, status=405)
                response['Allow'] = ', '.join(sorted(set(methods) | ({'HEAD'} if 'GET' in methods else set())))
                return response
            handler, model, code = methods[method]
            try:
                with ExitStack() as stack:
                    resolver = Resolver(request, path_params, stack)
                    from app.core.access import enforce
                    enforce(request, resolver, handler)
                    result = resolver.call(handler)
                    if isinstance(result, HttpResponseBase):
                        return result
                    if model is not None:
                        result = TypeAdapter(model).validate_python(result, from_attributes=True)
                    return JsonResponse(serialize(result), safe=False, status=code)
            except HTTPException as exc:
                resolver.rollback()
                return JsonResponse({'detail': exc.detail}, status=exc.status_code, headers=exc.headers)
            except BindingError as exc:
                resolver.rollback()
                return JsonResponse({'error_code': 'VALIDATION_ERROR', 'detail': 'Invalid request parameters', 'errors': exc.errors}, status=422)
            except Exception as exc:
                resolver.rollback()
                from app.core.exceptions import APIException
                if isinstance(exc, APIException):
                    return JsonResponse({'error_code': exc.error_code, 'detail': exc.detail}, status=exc.status_code)
                logger.exception('Unhandled API error: %s %s', request.method, request.path)
                return JsonResponse({'error_code': 'INTERNAL_SERVER_ERROR', 'detail': 'An unexpected error occurred. Please try again later.'}, status=500)
        return view

    # Literal routes must win over parameter routes, e.g. /employees/documents/...
    patterns = []
    for path, methods in sorted(grouped.items(), key=lambda item: item[0].count('{')):
        parts = re.split(r'(\{\w+\})', path)
        pattern = ''.join(f'(?P<{part[1:-1]}>[^/]+)' if part.startswith('{') else re.escape(part) for part in parts)
        patterns.append(re_path(r'^' + pattern + (r'/?$' if path else r'$'), make_view(methods)))
    return patterns
