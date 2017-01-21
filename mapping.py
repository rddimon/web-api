import types

import copy
import importlib

from django.utils import six


class MappingOptions(object):
    fields = {}
    resource_fields = {}

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
        resources = {}
        for field_name, obj in attrs.copy().items():
            if hasattr(obj, 'mapping_type'):
                field = attrs.pop(field_name)
                resources[field_name] = field.to_class()

        attrs['resources'] = resources
        new_class = super(DeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)
        opts = getattr(new_class, 'Meta', None)
        new_class._meta = MappingOptions(opts)
        new_class._meta.resources = resources
        return new_class


class BaseMapping(six.with_metaclass(DeclarativeMetaclass)):
    def __init__(self, mapping_path=None):
        self.mapping_path = mapping_path
        self.fields = {}
        self.resource_fields = {}
        self.encode_fields = {}
        self.encode_resource_fields = {}
        self._create_fields()
        self._create_resource_fields()

    def _create_fields(self):
        fields = copy.deepcopy(self._meta.fields)
        fields.update(self.update_fields())
        self.fields = fields
        self.encode_fields = {v: k for k, v in fields.items()}

    def _create_resource_fields(self):
        resource_fields = copy.deepcopy(self._meta.resource_fields)
        resource_fields.update(self.update_resource_fields())
        self.resource_fields = resource_fields
        self.encode_resource_fields = {v: k for k, v in resource_fields.items()}

    def get_all_fields(self):
        return self.encode_fields.keys() + self.encode_resource_fields.keys()

    def update_fields(self):
        return {}

    def update_resource_fields(self):
        return {}

    def encode(self, data, auto_encode=False):
        if self.mapping_path:
            data_path = None
            for p in self.mapping_path.split('.'):
                try:
                    data_path = data_path.get(p) if data_path else data.get(p)
                except AttributeError:
                    pass
            return self.encode_data(data_path, auto_encode)
        return self.encode_data(data, auto_encode)

    def encode_data(self, data, auto_encode=False):
        if data is None:
            return None
        if isinstance(data, (list, types.GeneratorType)):
            mapped_items = []
            for item in data:
                mapped_items.append(self.convert(item, auto_encode))
            return mapped_items
        return self.convert(data, auto_encode)

    def convert(self, item, auto_encode=False):
        new_item = {}

        for key, new_key in self.encode_fields.items():
            if not isinstance(item, dict):
                return None
            val = item.get(key, None)
            if isinstance(val, (dict, list)) and auto_encode:
                new_item[new_key] = self.auto_encode_data(val)
            else:
                new_item[new_key] = val

        for key, new_key in self.encode_resource_fields.items():
            val = item.get(key, None)
            if isinstance(val, list):
                res_items = []
                for res_item in val:
                    res_items.append(self.resources[new_key].encode_data(res_item, auto_encode))
                new_item[new_key] = res_items
            elif isinstance(val, dict) and not val:
                new_item[new_key] = None
            elif val is None:
                new_item[new_key] = None
            else:
                mapping = self.resources[key]
                new_item[new_key] = mapping.encode_data(val, auto_encode)
        return new_item

    def auto_encode_data(self, data, **kwargs):
        if isinstance(data, dict):
            return self.auto_encode_item(data, **kwargs)
        elif isinstance(data, list):
            return self.auto_encode_list(data, **kwargs)
        return data

    def auto_encode_list(self, data, **kwargs):
        new_data = []
        for item in data:
            if isinstance(item, dict):
                new_data.append(self.auto_encode_item(item, **kwargs))
            elif isinstance(item, list):
                new_data.append(self.auto_encode_list(item, **kwargs))
            else:
                new_data.append(item)
        return new_data

    def auto_encode_item(self, data, **kwargs):
        new_item = dict()
        for key, value in data.items():
            if kwargs and key in kwargs:
                new_key = kwargs[key]
            else:
                key_components = [component.title() for component in key.split('_')]
                new_key = key_components[0].lower() + "".join(key_components[1:]) \
                    if key_components.__len__() > 1 else key_components[0].lower()
            if isinstance(value, dict):
                new_item[new_key] = self.auto_encode_item(value, **kwargs)
            elif isinstance(value, list):
                new_item[new_key] = self.auto_encode_list(value, **kwargs)
            else:
                new_item[new_key] = value
        return new_item
    """
    def decode(self, data):
        if isinstance(data, dict):
            return self.decode_item(data)
        elif isinstance(data, list):
            return self.decode_list(data)
        return data

    def decode_list(self, data):
        new_data = []
        for item in data:
            if isinstance(item, dict):
                new_data.append(self.decode_item(item))
            elif isinstance(item, list):
                new_data.append(self.decode_list(item))
            else:
                new_data.append(item)
        return new_data

    def decode_item(self, data):
        new_item = dict()
        for key, value in data.items():
            if self.fields and key in self.fields:
                new_key = self.fields[key]
            else:
                continue
            if isinstance(value, dict):
                new_item[new_key] = self.decode_item(value)
            elif isinstance(value, list):
                new_item[new_key] = self.decode_list(value)
            else:
                new_item[new_key] = value
        return new_item
    """


class MappingResourceField(object):
    mapping_type = True

    def __init__(self, path):
        self.map_cls = path
        if isinstance(self.map_cls, six.string_types):
            module_bits = self.map_cls.split('.')
            module_path, class_name = '.'.join(module_bits[:-1]), module_bits[-1]
            module = importlib.import_module(module_path)
            self.map_cls = getattr(module, class_name)

    @property
    def to_class(self):
        return self.map_cls


class PagingMapping(BaseMapping):
    #avatar = MappingResourceField(ImageFieldMapping)

    class Meta:
        fields = {
            "page": "page",
            "perPage": "per_page",
        }

        resource_fields = {
            "data": "data"
        }