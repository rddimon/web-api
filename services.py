import os
from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models import QuerySet
from django.db.models.fields.files import ImageFieldFile, FieldFile
from django.db.models.fields.related import ManyToManyField
import six


class ResourceOptions(object):
    method_allowed = ()

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


class BaseService(six.with_metaclass(DeclarativeMetaclass)):
    def __init__(self, user=None):
        self.user = user or AnonymousUser()

    def set_user(self, user):
        self.user = user
        return self

    def unpack_model_objects(self, obj):
        if isinstance(obj, (list, set, QuerySet)):
            items = []
            for ii in obj:
                items.append(self.unpack_model_object(ii))
            return items
        else:
            return self.unpack_model_object(obj)

    def unpack_model_object(self, obj):
        if isinstance(obj, models.Model):
            item = self.model_to_dict(obj)
            return item
        return None

    @staticmethod
    def model_to_dict(instance, fields=None, exclude=None):
        if not instance:
            return
        opts = instance._meta
        data = {}
        for f in opts.concrete_fields + opts.many_to_many:
            # if not getattr(f, 'editable', False):
            #    continue
            if fields and f.name not in fields:
                continue
            if exclude and f.name in exclude:
                continue
            if isinstance(f, ManyToManyField):
                continue
            else:
                value = f.value_from_object(instance)
                if isinstance(value, ImageFieldFile) or isinstance(value, FieldFile):
                    value = {
                        'url': value.url,
                        'size': value.size,
                        'name': value.name,
                        'filename': os.path.basename(value.name)
                    } if value and os.path.exists(value.path) and value.name else None
                data[f.name] = value
        return data

    @staticmethod
    def user_model_to_dict(instance, fields=None, exclude=None):
        opts = instance._meta
        data = {}
        for f in opts.concrete_fields + opts.many_to_many:
            if not getattr(f, 'editable', False):
                pass
            if fields and not f.name in fields:
                continue
            if exclude and f.name in exclude:
                continue
            if isinstance(f, ManyToManyField):
                continue
            else:
                data[f.name] = f.value_from_object(instance)
        return data

    @staticmethod
    def resource_format(data=None):
        return {
            "count": len(data) if isinstance(data, list) else 1,
            "data": data
        }

    @staticmethod
    def objects_to_paging(objects, page=1, per_page=20):
        count = 0
        page_objects = []
        if isinstance(objects, QuerySet):
            count = objects.count()
        elif isinstance(objects, list):
            count = objects.__len__()
        if count > 0:
            page_objects = objects[(page - 1) * per_page: page * per_page]
        return {
            "count": count,
            "page": page,
            "per_page": per_page,
            "data": page_objects
        }

    @staticmethod
    def mapping_by_cls(cls, data, auto_encode=False):
        return cls(None).encode(data, auto_encode)

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
