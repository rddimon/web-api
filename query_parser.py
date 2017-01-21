# coding=utf-8
from functools import wraps


def decode_keys(params_mapping, data):
    new_data = dict()
    for key, value in params_mapping.items():
        new_data[key] = data.get(value, None)
    return new_data


def decode_filter_data(path):
    items = path.split(",") if path else []
    new_items = dict()
    for item in items:
        try:
            spl_val = item.split(":")
            if len(spl_val) == 1:
                raise ValueError
            elif len(spl_val) > 2:
                key = spl_val[0]
                values = ":".join(spl_val[1:])
            else:
                key, values = spl_val
        except ValueError:
            continue
        new_items[str(key)] = values.split("|")
    return new_items


def decode_order_data(path, **params_mapping):
    items = path.split("|")
    new_items = []
    inv_map = {v: k for k, v in params_mapping.items()}
    for item in items:
        if item:
            prefix = "-" if item[0] == "-" else ""
            if prefix:
                item = item[1:]
            if item in inv_map:
                new_items.append({inv_map[item]: "desc" if prefix else "asc"})
    return new_items


def filter_mapping(**params_mapping):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view_func(cls_obj, request, *args, **kwargs):
            data = request.data
            if data and data.get('f'):
                decode_data = decode_filter_data(data['f'])
                request.data['f'] = decode_keys(params_mapping, decode_data)
            return view_func(cls_obj, request, *args, **kwargs)
        return _wrapped_view_func
    return decorator


def order_mapping(**params_mapping):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view_func(cls_obj, request, *args, **kwargs):
            data = request.data
            if data and data.get('o'):
                decode_data = decode_order_data(data['o'], **params_mapping)
                request.data['o'] = decode_data
            return view_func(cls_obj, request, *args, **kwargs)
        return _wrapped_view_func
    return decorator