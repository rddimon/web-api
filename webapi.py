from copy import copy
import traceback
from django.core.serializers import json
from django.utils.functional import Promise
import six
import logging
from django.conf import settings
from django.http import HttpResponse
from django.template import Template, RequestContext
from django.views.decorators.csrf import csrf_exempt
import types

from utils.web_platform.errors import exception
import sys

logger = logging.getLogger('error_server')


class HttpMethodNotAllowed(HttpResponse):
    status_code = 405


def method_allowed(*methods):
    def decorator(view_func):
        @six.wraps(view_func)
        def _wrapped_view_func(cls_obj, request, *args, **kwargs):
            if request.method.lower() in methods:
                response = view_func(cls_obj, request, *args, **kwargs)
                return response
            allows = ', '.join([meth.upper() for meth in methods])
            response = HttpMethodNotAllowed(allows)
            response['Allow'] = allows
            return response

        return _wrapped_view_func

    return decorator


def decode_data(params_mapping, data, exclude_params=None):
    new_data = dict()
    for key, value in params_mapping.items():
        if isinstance(value, dict):
            param_value = copy(value.get("params", {}))
            value = data.get(value.get("key", None), None)
            if value:
                new_data[key] = decode_data(param_value, value, exclude_params)
        else:
            if exclude_params is None:
                new_data[key] = data.get(value, None)
            elif value in data:
                new_data[key] = data.get(value, None)

    return new_data


def mapping(exclude_params=None, **params_mapping):
    def decorator(view_func):
        @six.wraps(view_func)
        def _wrapped_view_func(cls_obj, request, *args, **kwargs):
            data = request.data or {}
            request.data = decode_data(params_mapping, data, exclude_params)
            try:
                return view_func(cls_obj, request, *args, **kwargs)
            except exception.ValidationError as e:
                if 'fields' in e.detail:
                    e.detail['fields'] = BaseWebApi().mapping_data(e.detail['fields'], **params_mapping)
                raise e

        return _wrapped_view_func

    return decorator


def response_mapping(cls, mapping_path=None, auto_encode=False):
    """
    if data doesn't have 'mapping_path' then data will mapped all
    """

    def decorator(view_func):
        @six.wraps(view_func)
        def _wrapped_view_func(cls_obj, request, *args, **kwargs):
            data = view_func(cls_obj, request, *args, **kwargs)
            if data and mapping_path:
                try:
                    input_data = data.pop(mapping_path)
                    map_data = cls(mapping_path).encode({mapping_path: input_data}, auto_encode)
                    data = BaseWebApi().mapping_data(data)
                    data[mapping_path] = map_data
                    return data
                except TypeError:
                    return cls(None).encode(data, auto_encode)
            return cls(mapping_path).encode(data, auto_encode)

        return _wrapped_view_func

    return decorator


class JsonEncoder(json.DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, Promise):
            return o
        elif isinstance(o, (set, types.GeneratorType)):
            return list(o)
        return super(JsonEncoder, self).default(o)


class ResourceOptions(object):
    default_format = "application/json"
    method_suffix = {
        'get': '',
        'detail': '_detail',
        'post': '_add',
        'put': '_update',
        'delete': '_delete',
        'patch': '_patch'
    }

    def __new__(cls, meta=None):
        overrides = {}
        if meta:
            for override_name in dir(meta):
                if not override_name.startswith('_'):
                    overrides[override_name] = getattr(meta, override_name)

        if six.PY3:
            return object.__new__(type('ResourceOptions', (cls,), overrides))
        else:
            return object.__new__(type(b'ResourceOptions', (cls,), overrides))


class DeclarativeMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_class = super(DeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)
        opts = getattr(new_class, 'Meta', None)
        new_class._meta = ResourceOptions(opts)
        return new_class


class BaseWebApi(six.with_metaclass(DeclarativeMetaclass)):
    template = """
         <!DOCTYPE html>
        <html>
            <head lang="en">
                <meta charset="UTF-8">
                <title></title>
            </head>

            <body>
                {{ data }}
            </body>
        </html>
    """

    def method(self, view):
        @csrf_exempt
        def wrapper(request, *args, **kwargs):
            if request.method == "OPTIONS":
                response = HttpResponse()
                response['Access-Control-Allow-Origin'] = '*'
                response['Access-Control-Allow-Headers'] = \
                    'Origin, X-Requested-With, Content-Type, Accept, Key, Authorization'
                return response
            try:
                convert_view = "%s%s" % (view, self._meta.method_suffix[request.method.lower()])
                self.convert_request_data(request)
                if hasattr(self, convert_view):
                    callback = getattr(self, convert_view)
                else:
                    callback = getattr(self, view)
                if not callback:
                    raise exception.NotFound
                response = callback(request, *args, **kwargs)
                if settings.DEBUG and 'debug' in request.GET.dict():
                    template = Template(self.template)
                    html = template.render(RequestContext(request, {"data": response}))
                    return HttpResponse(html)
                return self.json_response(response)
            except exception.APIException as e:
                return self.error_response(e)
            except Exception as e:
                return self.server_error(e)

        return wrapper

    @staticmethod
    def _error_response(error):
        return HttpResponse(error.json_info(), status=error.status_code, content_type='application/json')

    def convert_request_data(self, request):
        request.data = None
        request.files = None

        if request.method.lower() in ['put', 'patch']:
            def_method = str(request.method.upper())
            if hasattr(request, '_post'):
                del (request._post)
                del (request._files)
            request.method = "POST"
            request._load_post_and_files()
            request.method = def_method
            setattr(request, def_method, request.POST)

        if request.method.lower() in ['post', 'put', 'patch']:
            if request.FILES:
                request.files = request.FILES.copy()

            content_type = ''
            if 'CONTENT_TYPE' in request.META:
                content_type = request.META['CONTENT_TYPE'].split(';')[0].lower()

            if content_type == "application/json":
                try:
                    request.data = json.json.loads(request.body.decode('utf-8')) if request.body else None
                except ValueError:
                    raise exception.ParseError
            elif content_type == "text/plain":
                request.data = request.body if request.body else None
            elif content_type == "application/x-www-form-urlencoded":
                request.data = dict(request.POST.copy())
            elif content_type == "multipart/form-data":
                request.data = dict(request.POST.copy())
                if request.files:
                    request.data.update(request.files)
        elif request.GET:
            request.data = request.GET.dict()
        if request.data is None:
            request.data = {}

    @staticmethod
    def error_response(error):
        return HttpResponse(error.json_info(), status=error.status_code, content_type='application/json')

    @staticmethod
    def server_error(message):
        the_trace = ''.join(traceback.format_exception(*(sys.exc_info())))
        logger.error(the_trace)
        return HttpResponse(message, status=500, content_type='text/plain')

    def mapping_data(self, data, **kwargs):
        if isinstance(data, dict):
            return self.mapping_item(data, **kwargs)
        elif isinstance(data, list):
            return self.mapping_list(data, **kwargs)
        return data

    def mapping_list(self, data, **kwargs):
        new_data = []
        for item in data:
            if isinstance(item, dict):
                new_data.append(self.mapping_item(item, **kwargs))
            elif isinstance(item, list):
                new_data.append(self.mapping_list(item, **kwargs))
            else:
                new_data.append(item)
        return new_data

    def mapping_item(self, data, **kwargs):
        new_item = dict()
        for key, value in data.items():
            if kwargs and key in kwargs:
                new_key = kwargs[key]
            else:
                key_components = [component.title() for component in key.split('_')]
                new_key = key_components[0].lower() + "".join(key_components[1:]) \
                    if key_components.__len__() > 1 else key_components[0].lower()
            if isinstance(new_key, dict):
                new_key = new_key.get('key', 'undefined')
            if isinstance(value, dict):
                new_item[new_key] = self.mapping_item(value, **kwargs)
            elif isinstance(value, list):
                new_item[new_key] = self.mapping_list(value, **kwargs)
            else:
                new_item[new_key] = value
        return new_item

    def response(self, data):
        if self._meta.default_format == "application/json":
            return self.json_response(data)
        elif self._meta.default_format == "text/xml":
            return self.xml_response(data)
        else:
            return data

    def json_response(self, data, response_class=None):
        if isinstance(data, HttpResponse):
            return data
        if not response_class:
            response_class = HttpResponse
        data_convert = json.json.dumps(data, cls=JsonEncoder, sort_keys=True, ensure_ascii=False)
        return response_class(data_convert, content_type=self._meta.default_format)

    def xml_response(self, data, response_class=None):
        if isinstance(data, HttpResponse):
            return data
        if not response_class:
            response_class = HttpResponse
        return response_class(data, content_type="%s;charset=utf-8" % self._meta.default_format)
