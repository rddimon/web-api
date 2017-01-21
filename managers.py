from django.utils import six
from django.db import connection
from django.db.models import Q
import copy
from pymongo import MongoClient


class ManagerOptions(object):
    db_name = None
    table_name = None

    def __new__(cls, meta=None):
        overrides = {}
        if meta:
            for override_name in dir(meta):
                if not override_name.startswith('_'):
                    overrides[override_name] = getattr(meta, override_name)
        if six.PY3:
            return object.__new__(type('ManagerOptions', (cls,), overrides))
        else:
            return object.__new__(type(b'ManagerOptions', (cls,), overrides))


class DeclarativeMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_class = super(DeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)
        opts = getattr(new_class, 'Meta', None)
        new_class._meta = ManagerOptions(opts)
        return new_class


class BaseManager(six.with_metaclass(DeclarativeMetaclass)):
    def __init__(self, fields=None, related_fields=None):
        self.objects = None
        self.fields = fields or []
        self.related_fields = related_fields or ()
        self.clear()

    def clear(self):
        self.objects = None
        return self

    def select_related(self, *args):
        self.objects = self.objects.select_related(*args)
        return self

    def filter(self, **kwargs):
        self.objects = self.objects.filter(**kwargs)
        return self

    def order(self, *args):
        self.objects = self.objects.order_by(*args)
        return self

    def validate_query(self, *fields, **kwargs):
        value = kwargs.pop('value', None)
        operator = kwargs.pop('operator', "OR")
        if not value or fields.__len__() == 0:
            raise Exception
        return value, operator

    def add_subquery(self, query, field, value, suffix='__icontains', operator="OR"):
        subquery = Q(**{"%s%s" % (field, suffix): value})
        if operator == "AND":
            query = query & subquery if query else subquery
        else:
            query = query | subquery if query else subquery
        return query

    def query(self, query=None):
        if query:
            self.objects = self.objects.filter(query)
        return self

    def icontains(self, *fields, **kwargs):
        try:
            value, operator = self.validate_query(*fields, **kwargs)
        except Exception:
            return self
        query = None
        for field in fields:
            query = self.add_subquery(query, field, value, '__icontains', operator)
        return self.query(query)

    def limit(self, start, length):
        self.objects = self.objects[start: start + length]
        return self

    def custom_query(self):
        cursor = connection.cursor()
        cursor.execute(self.objects.values(*self.fields).query.__str__())
        return cursor.fetchall()

    def to_list(self):
        self.objects = self.objects.values(*self.fields)
        return self

    def to_data(self, fields=None, group_fields=None):
        fields, related_fields, allways_fields = self.construct_fields(fields or self.fields,
                                                                       group_fields or [ii[0]
                                                                                        for ii in self.related_fields])
        objects = self.objects.values_list(*allways_fields)

        def mapping(item):
            new_item = dict(zip(fields, item[0:len(fields)]))
            start_pos = len(fields)
            exclude_keys = []
            for rel_f in related_fields:
                keys = rel_f[0].split('__')
                fields_rel = rel_f[1]
                try:
                    required_key = rel_f[2]
                except IndexError:
                    required_key = None
                new_val = dict(zip(fields_rel, item[start_pos:start_pos + len(fields_rel)]))
                if required_key and new_val.get(required_key) is None:
                    start_pos += len(fields_rel)
                    exclude_keys.append(keys)
                    continue
                if keys[0:-1] in exclude_keys:
                    start_pos += len(fields_rel)
                    continue
                reduce(lambda d, key: d[key], keys[0:-1], new_item)\
                    .update({keys[-1]: dict(zip(fields_rel, item[start_pos:start_pos + len(fields_rel)]))})
                start_pos += len(fields_rel)
            return new_item
        return map(mapping, list(objects))

    def construct_fields(self, base_fields, group_fields):
        fields = copy.deepcopy(base_fields)
        related_fields = []
        allways_fields = copy.deepcopy(fields)
        for rel_field in self.related_fields:
            if group_fields and rel_field[0] in group_fields:
                related_fields.append(rel_field)
        for rel_field in related_fields:
            allways_fields += ["%s__%s" % (rel_field[0], f) for f in rel_field[1]]
        return fields, related_fields, allways_fields


class BaseMongoManager(BaseManager):
    def __init__(self):
        super(BaseMongoManager, self).__init__()
        client = MongoClient('localhost', 27017)
        db = getattr(client, self._meta.db_name)
        self.table = getattr(db, self._meta.table_name)