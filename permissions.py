from functools import wraps

from utils.web_platform.errors import exception


def authenticated(view_func):
    @wraps(view_func)
    def _wrapped_view_func(cls_obj, *args, **kwargs):
        if cls_obj.user.is_authenticated():
            return view_func(cls_obj, *args, **kwargs)
        raise exception.AuthenticationFailed
    return _wrapped_view_func


def allow_method_by_perms(*perms):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view_func(cls_obj, *args, **kwargs):
            if not cls_obj.user.is_authenticated():
                raise exception.NotAuthenticated
            if cls_obj.user.is_superuser:
                return view_func(cls_obj, *args, **kwargs)
            if cls_obj.user.has_company_perms(cls_obj.company, *perms):
                return view_func(cls_obj, *args, **kwargs)
            raise exception.PermissionDenied
        return _wrapped_view_func
    return decorator


def allow_method_by_group(*groups):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view_func(cls_obj, *args, **kwargs):
            if not cls_obj.user.is_authenticated():
                raise exception.NotAuthenticated
            for gr in groups:
                if cls_obj.user.has_group(gr):
                    response = view_func(cls_obj, *args, **kwargs)
                    return response
            raise exception.PermissionDenied
        return _wrapped_view_func
    return decorator
