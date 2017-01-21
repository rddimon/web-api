# coding=utf-8
from decimal import Decimal
from functools import wraps
import datetime
from django.core.validators import RegexValidator
from django.utils.dateparse import parse_datetime, parse_date

from django.core import exceptions, validators
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
import phonenumbers
import re
from utils.web_platform.errors.exception import ValidationError


def decode_to_type(value, types):
    if value is None:
        return None
    new_value = None
    for t in types:
        if t == datetime.datetime:
            new_value = decode_to_datetime(value)
            continue
        elif t == datetime.date:
            new_value = decode_to_date(value)
            continue
        new_value = t(value) if new_value is None else t(new_value)
    return new_value


def decode_to_datetime(value):
    try:
        parsed = parse_datetime(value)
        if parsed is not None:
            return parsed
    except ValueError:
        pass
    raise ValidationError(_(u"Не валидные входные данные"))


def decode_to_date(value):
    try:
        parsed = parse_date(value)
        if parsed is not None:
            return parsed
    except ValueError:
        pass
    raise ValidationError(_(u"Не валидные входные данные"))


def validate_fields(data, options):
    if data is None:
        data = dict()
    for name, params in options.items():
        validator = ValidParam(name)
        validator.create_validators(data, **params)
        valid_value = validator.run_validators(data.get(name), params.get('messages'))
        if valid_value is not None:
            data[name] = valid_value
    return data


def validate_input(options):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view_func(cls_obj, data=None, *args, **kwargs):
            data = validate_fields(data, options)
            return view_func(cls_obj, data, *args, **kwargs)

        return _wrapped_view_func

    return decorator


def validate_filter(options):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view_func(cls_obj, data, *args, **kwargs):
            data = data or {}
            filter = data.get('filter')
            validate_filter_params = dict()
            if filter:
                for name, params in options.items():
                    values = filter.get(name)
                    if not values:
                        continue
                    is_array = params.get('is_array', False)
                    type_val = params.get('type', 'str')

                    if is_array and isinstance(values, str):
                        values = [values]
                    elif not is_array and isinstance(values, list):
                        values = values[0]

                    decode_types = [str]
                    if type_val == 'integer':
                        decode_types = [int]
                    elif type_val == 'bool':
                        decode_types = [int, bool]
                    elif type_val == 'datetime':
                        decode_types = [datetime.datetime]
                    elif type_val == 'date':
                        decode_types = [datetime.date]
                    try:
                        values = [decode_to_type(val, decode_types) for val in values] \
                            if isinstance(values, list) else decode_to_type(values, decode_types)
                    except ValueError:
                        continue
                    except ValidationError as e:
                        raise ValidationError({
                            'message': _(u"Не валидные входные данные"),
                            'fields': {str(name): {"message": e.message}}
                        }, 1)
                    validate_filter_params[str(name)] = values
            data['filter'] = validate_filter_params
            return view_func(cls_obj, data, *args, **kwargs)

        return _wrapped_view_func

    return decorator


def validate_order(*fields, **base_kwargs):
    """
    format = 0 - with asc and desc
    format = 1 - with '-' or empty
    format = 2 - django order_by format
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view_func(cls_obj, data=None, *args, **kwargs):
            format_item = base_kwargs.get('format', 0)
            data = data or {}
            default_order_items = list(map(lambda x: list(x.keys())[0], base_kwargs.get("default", [])))
            order_items = data.get('order') or base_kwargs.get("default", [])
            if not isinstance(order_items, list):
                order_items = []
            items = []
            all_fields = list(fields) + default_order_items
            for item in order_items or []:
                field = list(item.keys())[0]
                if not field in all_fields:
                    continue
                if format_item == 1:
                    items.append({field: "-" if item[field] == "desc" else ""})
                elif format_item == 2:
                    items.append(("-" if item[field] == "desc" else "") + field)
                else:
                    items.append(item)
            data['order'] = items
            return view_func(cls_obj, data, *args, **kwargs)

        return _wrapped_view_func

    return decorator


class ValidParam(object):
    def __init__(self, name):
        self.validators = []
        self.name = name

    @staticmethod
    def get_validator_by_type(_type, value=None):
        """
        Return
        :param _type:
        :param value:
        :return:
        """
        if _type == 'default':
            return DefaultValidator(value)
        if _type == 'required':
            return RequiredValidator(value)
        if _type == 'min_length':
            return validators.MinLengthValidator(value)
        if _type == 'max_length':
            return validators.MaxLengthValidator(value)
        if _type == 'type':
            return ConvertToTypeValidator(value)
        if _type == 'min_value':
            return validators.MinValueValidator(value)
        if _type == 'max_value':
            return validators.MaxValueValidator(value)
        if _type == 'equal_to':
            return EqualToValidator(value)
        if _type == 'email':
            return validators.EmailValidator(code='email')
        if _type == 'phone':
            return PhoneNumberValidator(value)
        if _type == 'phone_simple':
            return SimplePhoneNumberValidator(value)
        if _type == 'datetime':
            return DateTimeValidator()
        if _type == 'file':
            return FileValidator()
        return None

    @staticmethod
    def check_validator(validator, value):
        """
        try to validate value
        if success return tuple False, valid_value
        if error return tuple False, dict with param: message, code
        :param validator:
        :param value:
        :return: bool, valid_value or dict
        """
        try:
            return True, validator(value)
        except exceptions.ValidationError as e:
            message = {'message': e.messages[0], 'code': None}
            if hasattr(e, 'code'):
                message['code'] = e.code
        return False, message

    def create_validators(self, data, **kwargs):
        if kwargs.get("default"):
            self.validators.append(self.get_validator_by_type('default', kwargs.get("default")))
        if kwargs.get("required") or kwargs.get("required") is None:
            self.validators.append(self.get_validator_by_type('required'))
        elif not data.get(self.name):
            return

        if kwargs.get("min_length"):
            self.validators.append(self.get_validator_by_type('min_length', kwargs.get("min_length")))
        if kwargs.get("max_length"):
            self.validators.append(self.get_validator_by_type('max_length', kwargs.get("max_length")))
        if kwargs.get("type"):
            self.validators.append(self.get_validator_by_type('type', kwargs.get("type")))
        if kwargs.get("min_value"):
            self.validators.append(self.get_validator_by_type('min_value', kwargs.get("min_value")))
        if kwargs.get("max_value"):
            self.validators.append(self.get_validator_by_type('max_value', kwargs.get("max_value")))
        if kwargs.get("equal_to"):
            self.validators.append(self.get_validator_by_type('equal_to', data.get(kwargs["equal_to"])))

        if kwargs.get("validation_type"):
            _type = kwargs.get("validation_type")
            type_validators = None
            if type(_type) == str:
                type_validators = [self.get_validator_by_type(_type)]
            elif type(_type) == list:
                type_validators = [self.get_validator_by_type(x) for x in _type]
            if type_validators:
                self.validators.append({
                    'code': 'validation_type',
                    'validators': type_validators
                })

    def add_custom_validators(self, vs):
        if vs:
            self.validators = self.validators + vs

    def run_validators(self, value, messages=None):
        default_error_message = _(u"Не валидные входные данные")
        new_value = None
        fields_error = {}
        group_error_info = {}
        for v in self.validators:
            valid = True
            res_or_error = None
            _value = new_value if new_value is not None else value
            if type(v) == dict:
                group_error_message = messages.get(v.get('code')) if messages else '' or default_error_message
                group_error_info[v.get('code')] = group_error_message
                for item in v.get('validators'):
                    valid, res_or_error = self.check_validator(item, _value)
                    if valid:
                        break
            else:
                valid, res_or_error = self.check_validator(v, _value)
            if not valid:
                if messages and messages.get(res_or_error.get('code')):
                    res_or_error['detail'] = messages.get(res_or_error.get('code'))

                if messages and messages.get('default'):
                    error_message = messages.get('default')
                else:
                    error_message = group_error_info or res_or_error

                fields_error['fields'] = {self.name: error_message}

                raise ValidationError(detail=default_error_message, **fields_error)
            elif res_or_error is not None:
                new_value = res_or_error
        return new_value


class RequiredValidator(validators.BaseValidator):
    # clean = lambda self, x: None if isinstance(x, (str, unicode)) and x.__len__() == 0 else x
    compare = lambda self, a, b: a is b
    message = _('This field cannot be null.')
    code = 'required'

    def clean(self, x):
        if isinstance(x, (str, list)) and x.__len__() == 0:
            return None
        else:
            return x

    def __call__(self, value):
        cleaned = self.clean(value)
        params = {'limit_value': self.limit_value, 'show_value': cleaned}
        if self.compare(cleaned, self.limit_value):
            raise exceptions.ValidationError(self.message, code=self.code, params=params)


class DefaultValidator(validators.BaseValidator):
    message = _('Error.')
    code = 'default'

    def __call__(self, value):
        cleaned = self.clean(value)
        return cleaned or self.limit_value


class EqualToValidator(validators.BaseValidator):
    compare = lambda self, a, b: a != b
    message = _("The two fields didn't match.")
    code = 'equal_to'

    def __call__(self, value):
        cleaned = self.clean(value)
        params = {'limit_value': self.limit_value, 'show_value': cleaned}
        if self.compare(cleaned, self.limit_value):
            raise exceptions.ValidationError(self.message, code=self.code, params=params)


class SimplePhoneNumberValidator(validators.BaseValidator):
    regex = re.compile(r'^\+?1?\d{9,15}$')
    message = _('Enter a valid phone number.')
    code = 'phone_simple'

    def __call__(self, value):
        cleaned = self.clean(value)
        params = {'limit_value': self.limit_value, 'show_value': cleaned}
        if not self.regex.match(value):
            raise exceptions.ValidationError(self.message, code=self.code, params=params)


class PhoneNumberValidator(validators.BaseValidator):
    clean = lambda self, x: force_text(x)
    message = _('Enter a valid phone number.')
    code = 'invalid'
    formats = {
        "INTERNATIONAL": phonenumbers.PhoneNumberFormat.E164,
        "NATIONAL": phonenumbers.PhoneNumberFormat.NATIONAL
    }
    messages = {
        0: _(u"INVALID_COUNTRY_CODE"),
        1: _(u"NOT_A_NUMBER"),
        2: _(u"TOO_SHORT_AFTER_IDD"),
        3: _(u"TOO_SHORT_NSN"),
        4: _(u"TOO_LONG")
    }

    def __init__(self, format="INTERNATIONAL"):
        super(PhoneNumberValidator, self).__init__(limit_value=None)
        self.format = format
        if not self.format in self.formats.keys():
            self.format = "INTERNATIONAL"

    def __call__(self, value):
        cleaned = self.clean(value)
        try:
            phone = phonenumbers.parse(cleaned, None)
        except phonenumbers.NumberParseException as e:
            raise exceptions.ValidationError(self.messages.get(e.error_type, self.message),
                                             code=self.code, params={'show_value': cleaned})
        is_valid = phonenumbers.is_valid_number(phone)
        if not is_valid:
            raise exceptions.ValidationError(self.message, code=self.code, params={'show_value': cleaned})
        return phonenumbers.format_number(phone, self.formats[self.format]) \
            .replace(' ', '').replace('+', '').replace('-', '')


validate_simple_phone = RegexValidator(r'^[-a-zA-Z0-9_]+\Z', _('Enter a valid phone number.'))


class DateTimeValidator(validators.BaseValidator):
    clean = lambda self, x: force_text(x)
    message = _('Enter a valid date.')
    code = 'invalid'
    ISO_8601 = 'iso-8601'
    input_formats = list(settings.DATETIME_INPUT_FORMATS)  # formats.get_format_lazy('DATETIME_INPUT_FORMATS')
    input_formats += [ISO_8601]

    def __init__(self):
        super(DateTimeValidator, self).__init__(limit_value=None)

    def __call__(self, value):
        cleaned = self.clean(value)
        parsed = None

        for format in self.input_formats:
            if format.lower() == self.ISO_8601:
                try:
                    parsed = parse_datetime(cleaned)
                except (ValueError, TypeError):
                    continue
            else:
                try:
                    parsed = datetime.datetime.strptime(cleaned, format)
                except (ValueError, TypeError):
                    continue
        if not parsed:
            raise exceptions.ValidationError(self.message, code=self.code, params={'show_value': cleaned})
        return parsed


class FileValidator(validators.BaseValidator):
    def __init__(self):
        super(FileValidator, self).__init__(limit_value=None)

    def __call__(self, value):
        pass


class ConvertToTypeValidator(validators.BaseValidator):
    compare = lambda self, x: x
    message = _("Value not type %s")
    code = 'type'

    def __call__(self, value):
        cleaned = self.clean(value)
        params = {'limit_value': self.limit_value, 'show_value': cleaned}
        try:
            if self.limit_value == "text":
                cleaned = cleaned
            elif self.limit_value == "decimal":
                cleaned = Decimal(cleaned)
            elif self.limit_value == "integer":
                cleaned = int(cleaned)
            elif self.limit_value == "bool":
                cleaned = bool(int(cleaned))
            return cleaned
        except ValueError:
            raise exceptions.ValidationError(self.message % self.limit_value, code=self.code, params=params)
