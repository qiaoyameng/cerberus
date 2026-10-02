# -*- coding: utf-8 -*-

from copy import deepcopy
from itertools import permutations
from tempfile import NamedTemporaryFile

from pytest import mark

from cerberus import Validator, errors
from cerberus.tests import (
    assert_fail,
    assert_has_error,
    assert_normalized,
    assert_success,
)


def must_not_be_called(*args, **kwargs):
    raise RuntimeError('This shall not be called.')


def test_coerce():
    schema = {'amount': {'coerce': int}}
    document = {'amount': '1'}
    expected = {'amount': 1}
    assert_normalized(document, expected, schema)


def test_coerce_in_dictschema():
    schema = {'thing': {'type': 'dict', 'schema': {'amount': {'coerce': int}}}}
    document = {'thing': {'amount': '2'}}
    expected = {'thing': {'amount': 2}}
    assert_normalized(document, expected, schema)


def test_coerce_in_listschema():
    schema = {'things': {'type': 'list', 'schema': {'coerce': int}}}
    document = {'things': ['1', '2', '3']}
    expected = {'things': [1, 2, 3]}
    assert_normalized(document, expected, schema)


def test_coerce_in_listitems():
    schema = {'things': {'type': 'list', 'items': [{'coerce': int}, {'coerce': str}]}}
    document = {'things': ['1', 2]}
    expected = {'things': [1, '2']}
    assert_normalized(document, expected, schema)

    validator = Validator(schema)
    document['things'].append(3)
    assert not validator(document)
    assert validator.document['things'] == document['things']


def test_coerce_in_dictschema_in_listschema():
    item_schema = {'type': 'dict', 'schema': {'amount': {'coerce': int}}}
    schema = {'things': {'type': 'list', 'schema': item_schema}}
    document = {'things': [{'amount': '2'}]}
    expected = {'things': [{'amount': 2}]}
    assert_normalized(document, expected, schema)


def test_coerce_not_destructive():
    schema = {'amount': {'coerce': int}}
    v = Validator(schema)
    doc = {'amount': '1'}
    v.validate(doc)
    assert v.document is not doc


def test_coerce_catches_ValueError():
    schema = {'amount': {'coerce': int}}
    _errors = assert_fail({'amount': 'not_a_number'}, schema)
    _errors[0].info = ()  # ignore exception message here
    assert_has_error(
        _errors, 'amount', ('amount', 'coerce'), errors.COERCION_FAILED, int
    )


def test_coerce_in_listitems_catches_ValueError():
    schema = {'things': {'type': 'list', 'items': [{'coerce': int}, {'coerce': str}]}}
    document = {'things': ['not_a_number', 2]}
    _errors = assert_fail(document, schema)
    _errors[0].info = ()  # ignore exception message here
    assert_has_error(
        _errors,
        ('things', 0),
        ('things', 'items', 'coerce'),
        errors.COERCION_FAILED,
        int,
    )


def test_coerce_catches_TypeError():
    schema = {'name': {'coerce': str.lower}}
    _errors = assert_fail({'name': 1234}, schema)
    _errors[0].info = ()  # ignore exception message here
    assert_has_error(
        _errors, 'name', ('name', 'coerce'), errors.COERCION_FAILED, str.lower
    )


def test_coerce_in_listitems_catches_TypeError():
    schema = {
        'things': {'type': 'list', 'items': [{'coerce': int}, {'coerce': str.lower}]}
    }
    document = {'things': ['1', 2]}
    _errors = assert_fail(document, schema)
    _errors[0].info = ()  # ignore exception message here
    assert_has_error(
        _errors,
        ('things', 1),
        ('things', 'items', 'coerce'),
        errors.COERCION_FAILED,
        str.lower,
    )


def test_coerce_unknown():
    schema = {'foo': {'schema': {}, 'allow_unknown': {'coerce': int}}}
    document = {'foo': {'bar': '0'}}
    expected = {'foo': {'bar': 0}}
    assert_normalized(document, expected, schema)


def test_custom_coerce_and_rename():
    class MyNormalizer(Validator):
        def __init__(self, multiplier, *args, **kwargs):
            super(MyNormalizer, self).__init__(*args, **kwargs)
            self.multiplier = multiplier

        def _normalize_coerce_multiply(self, value):
            return value * self.multiplier

    v = MyNormalizer(2, {'foo': {'coerce': 'multiply'}})
    assert v.normalized({'foo': 2})['foo'] == 4

    v = MyNormalizer(3, allow_unknown={'rename_handler': 'multiply'})
    assert v.normalized({3: None}) == {9: None}


def test_coerce_chain():
    drop_prefix = lambda x: x[2:]  # noqa: E731
    upper = lambda x: x.upper()  # noqa: E731
    schema = {'foo': {'coerce': [hex, drop_prefix, upper]}}
    assert_normalized({'foo': 15}, {'foo': 'F'}, schema)


def test_coerce_chain_aborts(validator):
    def dont_do_me(value):
        raise AssertionError('The coercion chain did not abort after an ' 'error.')

    schema = {'foo': {'coerce': [hex, dont_do_me]}}
    validator({'foo': '0'}, schema)
    assert errors.COERCION_FAILED in validator._errors


def test_coerce_non_digit_in_sequence(validator):
    # https://github.com/pyeve/cerberus/issues/211
    schema = {'data': {'type': 'list', 'schema': {'type': 'integer', 'coerce': int}}}
    document = {'data': ['q']}
    assert validator.validated(document, schema) is None
    assert (
        validator.validated(document, schema, always_return_document=True) == document
    )  # noqa: W503


def test_nullables_dont_fail_coerce():
    schema = {'foo': {'coerce': int, 'nullable': True, 'type': 'integer'}}
    document = {'foo': None}
    assert_normalized(document, document, schema)


def test_nullables_fail_coerce_on_non_null_values(validator):
    def failing_coercion(value):
        raise Exception("expected to fail")

    schema = {'foo': {'coerce': failing_coercion, 'nullable': True, 'type': 'integer'}}
    document = {'foo': None}
    assert_normalized(document, document, schema)

    validator({'foo': 2}, schema)
    assert errors.COERCION_FAILED in validator._errors


def test_normalized():
    schema = {'amount': {'coerce': int}}
    document = {'amount': '2'}
    expected = {'amount': 2}
    assert_normalized(document, expected, schema)


def test_rename(validator):
    schema = {'foo': {'rename': 'bar'}}
    document = {'foo': 0}
    expected = {'bar': 0}
    # We cannot use assertNormalized here since there is bug where
    # Cerberus says that the renamed field is an unknown field:
    # {'bar': 'unknown field'}
    validator(document, schema, False)
    assert validator.document == expected


def test_rename_handler():
    validator = Validator(allow_unknown={'rename_handler': int})
    schema = {}
    document = {'0': 'foo'}
    expected = {0: 'foo'}
    assert_normalized(document, expected, schema, validator)


def normalization_result(document, schema, **kwargs):
    validator = Validator(schema, **kwargs)
    result = validator.normalized(deepcopy(document), always_return_document=True)
    errors = tuple(
        (
            error.document_path,
            error.code,
            error.constraint,
            error.info,
        )
        for error in validator._errors
    )
    return result, errors


def test_simultaneous_rename_swap_is_order_independent():
    schema = {'a': {'rename': 'b'}, 'b': {'rename': 'a'}}
    document = {'a': 1, 'b': 2}
    expected = {'a': 2, 'b': 1}

    results = [
        normalization_result(dict(items), schema, simultaneous_renaming=True)
        for items in permutations(document.items())
    ]

    assert all(result == results[0][0] for result, _ in results[1:])
    assert all(actual_errors == results[0][1] for _, actual_errors in results[1:])
    assert results[0] == (expected, ())


def test_simultaneous_rename_three_node_cycle_is_order_independent():
    schema = {
        'a': {'rename': 'b'},
        'b': {'rename': 'c'},
        'c': {'rename': 'a'},
    }
    document = {'a': 1, 'b': 2, 'c': 3}
    expected = {'a': 3, 'b': 1, 'c': 2}

    results = [
        normalization_result(dict(items), schema, simultaneous_renaming=True)
        for items in permutations(document.items())
    ]

    assert all(result == results[0][0] for result, _ in results[1:])
    assert all(actual_errors == results[0][1] for _, actual_errors in results[1:])
    assert results[0] == (expected, ())


def test_simultaneous_rename_chain():
    schema = {'a': {'rename': 'b'}, 'b': {'rename': 'c'}}
    result, actual_errors = normalization_result(
        {'a': 1, 'b': 2}, schema, simultaneous_renaming=True
    )
    assert result == {'b': 1, 'c': 2}
    assert actual_errors == ()


def test_simultaneous_rename_merge_is_order_independent():
    schema = {'a': {'rename': 'c'}, 'b': {'rename': 'c'}}
    document = {'a': 1, 'b': 2}

    results = [
        normalization_result(dict(items), schema, simultaneous_renaming=True)
        for items in permutations(document.items())
    ]

    assert all(result == results[0][0] for result, _ in results[1:])
    assert all(actual_errors == results[0][1] for _, actual_errors in results[1:])
    result, actual_errors = results[0]
    assert result == document
    assert len(actual_errors) == 1
    document_path, code, constraint, info = actual_errors[0]
    assert document_path == ('a',)
    assert code == errors.RENAMING_CONFLICT.code
    assert constraint == 'c'
    assert info == (('a', 'b'),)


def test_simultaneous_rename_conflict_with_existing_target():
    schema = {'a': {'rename': 'b'}, 'b': {}}
    document = {'a': 1, 'b': 2}

    result, actual_errors = normalization_result(
        document, schema, simultaneous_renaming=True
    )

    assert result == document
    assert len(actual_errors) == 1
    assert actual_errors[0][1] == errors.RENAMING_CONFLICT.code
    assert actual_errors[0][2] == 'b'
    assert actual_errors[0][3] == (('a',),)


def test_simultaneous_rename_conflict_with_existing_unknown_target():
    schema = {'a': {'rename': 'b'}}
    document = {'a': 1, 'b': 2}

    result, actual_errors = normalization_result(
        document, schema, simultaneous_renaming=True
    )

    assert result == document
    assert len(actual_errors) == 1
    assert actual_errors[0][0] == ('a',)
    assert actual_errors[0][2] == 'b'
    assert actual_errors[0][3] == (('a',),)


def test_simultaneous_rename_handler_conflict_with_existing_target():
    schema = {'a': {'rename_handler': lambda field: 'b'}, 'b': {}}

    result, actual_errors = normalization_result(
        {'a': 1, 'b': 2}, schema, simultaneous_renaming=True
    )

    assert result == {'a': 1, 'b': 2}
    assert actual_errors[0][3] == (('a',),)


def test_simultaneous_rename_handler_swap_for_unknown_fields():
    result, actual_errors = normalization_result(
        {'1': 1, '2': 2},
        {},
        allow_unknown={
            'rename_handler': lambda field: {'1': '2', '2': '1'}[field]
        },
        simultaneous_renaming=True,
    )

    assert result == {'1': 2, '2': 1}
    assert actual_errors == ()


def test_simultaneous_rename_handler_exception_leaves_other_renames_order_independent():
    def rename_handler(field):
        if field in ('a', 'b'):
            raise ValueError('cannot rename ' + field)
        return field.upper()

    schema = {
        'a': {'rename_handler': rename_handler},
        'b': {'rename_handler': rename_handler},
        'c': {'rename_handler': rename_handler},
    }
    document = {'a': 1, 'b': 2, 'c': 3}

    results = [
        normalization_result(dict(items), schema, simultaneous_renaming=True)
        for items in permutations(document.items())
    ]

    assert all(result == results[0][0] for result, _ in results[1:])
    assert all(actual_errors == results[0][1] for _, actual_errors in results[1:])
    result, actual_errors = results[0]
    assert result == {'a': 1, 'b': 2, 'C': 3}
    assert [error[0] for error in actual_errors] == [('a',), ('b',)]
    assert {error[1] for error in actual_errors} == {errors.RENAMING_FAILED.code}


def test_simultaneous_rename_is_planned_separately_for_nested_mappings():
    schema = {
        'outer': {
            'type': 'dict',
            'schema': {'a': {'rename': 'b'}, 'b': {'rename': 'a'}},
        }
    }
    document = {'outer': {'a': 1, 'b': 2}}

    result, actual_errors = normalization_result(
        document, schema, simultaneous_renaming=True
    )

    assert result == {'outer': {'a': 2, 'b': 1}}
    assert actual_errors == ()


def test_rename_remains_sequential_by_default():
    schema = {'a': {'rename': 'b'}, 'b': {'rename': 'a'}}

    result, actual_errors = normalization_result(
        {'a': 1, 'b': 2}, schema
    )

    assert result == {'a': 1}
    assert actual_errors == ()


def test_purge_unknown():
    validator = Validator(purge_unknown=True)
    schema = {'foo': {'type': 'string'}}
    document = {'bar': 'foo'}
    expected = {}
    assert_normalized(document, expected, schema, validator)


def test_purge_unknown_in_subschema():
    schema = {
        'foo': {
            'type': 'dict',
            'schema': {'foo': {'type': 'string'}},
            'purge_unknown': True,
        }
    }
    document = {'foo': {'bar': ''}}
    expected = {'foo': {}}
    assert_normalized(document, expected, schema)


def test_issue_147_complex():
    schema = {'revision': {'coerce': int}}
    document = {'revision': '5', 'file': NamedTemporaryFile(mode='w+')}
    document['file'].write(r'foobar')
    document['file'].seek(0)
    normalized = Validator(schema, allow_unknown=True).normalized(document)
    assert normalized['revision'] == 5
    assert normalized['file'].read() == 'foobar'
    document['file'].close()
    normalized['file'].close()


def test_issue_147_nested_dict():
    schema = {'thing': {'type': 'dict', 'schema': {'amount': {'coerce': int}}}}
    ref_obj = '2'
    document = {'thing': {'amount': ref_obj}}
    normalized = Validator(schema).normalized(document)
    assert document is not normalized
    assert normalized['thing']['amount'] == 2
    assert ref_obj == '2'
    assert document['thing']['amount'] is ref_obj


def test_coerce_in_valuesrules():
    # https://github.com/pyeve/cerberus/issues/155
    schema = {
        'thing': {'type': 'dict', 'valuesrules': {'coerce': int, 'type': 'integer'}}
    }
    document = {'thing': {'amount': '2'}}
    expected = {'thing': {'amount': 2}}
    assert_normalized(document, expected, schema)


def test_coerce_in_keysrules():
    # https://github.com/pyeve/cerberus/issues/155
    schema = {
        'thing': {'type': 'dict', 'keysrules': {'coerce': int, 'type': 'integer'}}
    }
    document = {'thing': {'5': 'foo'}}
    expected = {'thing': {5: 'foo'}}
    assert_normalized(document, expected, schema)


def test_coercion_of_sequence_items(validator):
    # https://github.com/pyeve/cerberus/issues/161
    schema = {'a_list': {'type': 'list', 'schema': {'type': 'float', 'coerce': float}}}
    document = {'a_list': [3, 4, 5]}
    expected = {'a_list': [3.0, 4.0, 5.0]}
    assert_normalized(document, expected, schema, validator)
    for x in validator.document['a_list']:
        assert isinstance(x, float)


@mark.parametrize(
    'default', ({'default': 'bar_value'}, {'default_setter': lambda doc: 'bar_value'})
)
def test_default_missing(default):
    bar_schema = {'type': 'string'}
    bar_schema.update(default)
    schema = {'foo': {'type': 'string'}, 'bar': bar_schema}
    document = {'foo': 'foo_value'}
    expected = {'foo': 'foo_value', 'bar': 'bar_value'}
    assert_normalized(document, expected, schema)


@mark.parametrize(
    'default', ({'default': 'bar_value'}, {'default_setter': must_not_be_called})
)
def test_default_existent(default):
    bar_schema = {'type': 'string'}
    bar_schema.update(default)
    schema = {'foo': {'type': 'string'}, 'bar': bar_schema}
    document = {'foo': 'foo_value', 'bar': 'non_default'}
    assert_normalized(document, document.copy(), schema)


@mark.parametrize(
    'default', ({'default': 'bar_value'}, {'default_setter': must_not_be_called})
)
def test_default_none_nullable(default):
    bar_schema = {'type': 'string', 'nullable': True}
    bar_schema.update(default)
    schema = {'foo': {'type': 'string'}, 'bar': bar_schema}
    document = {'foo': 'foo_value', 'bar': None}
    assert_normalized(document, document.copy(), schema)


@mark.parametrize(
    'default', ({'default': 'bar_value'}, {'default_setter': lambda doc: 'bar_value'})
)
def test_default_none_nonnullable(default):
    bar_schema = {'type': 'string', 'nullable': False}
    bar_schema.update(default)
    schema = {'foo': {'type': 'string'}, 'bar': bar_schema}
    document = {'foo': 'foo_value', 'bar': None}
    expected = {'foo': 'foo_value', 'bar': 'bar_value'}
    assert_normalized(document, expected, schema)


def test_default_none_default_value():
    schema = {
        'foo': {'type': 'string'},
        'bar': {'type': 'string', 'nullable': True, 'default': None},
    }
    document = {'foo': 'foo_value'}
    expected = {'foo': 'foo_value', 'bar': None}
    assert_normalized(document, expected, schema)


@mark.parametrize(
    'default', ({'default': 'bar_value'}, {'default_setter': lambda doc: 'bar_value'})
)
def test_default_missing_in_subschema(default):
    bar_schema = {'type': 'string'}
    bar_schema.update(default)
    schema = {
        'thing': {
            'type': 'dict',
            'schema': {'foo': {'type': 'string'}, 'bar': bar_schema},
        }
    }
    document = {'thing': {'foo': 'foo_value'}}
    expected = {'thing': {'foo': 'foo_value', 'bar': 'bar_value'}}
    assert_normalized(document, expected, schema)


def test_depending_default_setters():
    schema = {
        'a': {'type': 'integer'},
        'b': {'type': 'integer', 'default_setter': lambda d: d['a'] + 1},
        'c': {'type': 'integer', 'default_setter': lambda d: d['b'] * 2},
        'd': {'type': 'integer', 'default_setter': lambda d: d['b'] + d['c']},
    }
    document = {'a': 1}
    expected = {'a': 1, 'b': 2, 'c': 4, 'd': 6}
    assert_normalized(document, expected, schema)


def test_circular_depending_default_setters(validator):
    schema = {
        'a': {'type': 'integer', 'default_setter': lambda d: d['b'] + 1},
        'b': {'type': 'integer', 'default_setter': lambda d: d['a'] + 1},
    }
    validator({}, schema)
    assert errors.SETTING_DEFAULT_FAILED in validator._errors


def test_issue_250():
    # https://github.com/pyeve/cerberus/issues/250
    schema = {
        'list': {
            'type': 'list',
            'schema': {
                'type': 'dict',
                'allow_unknown': True,
                'schema': {'a': {'type': 'string'}},
            },
        }
    }
    document = {'list': {'is_a': 'mapping'}}
    assert_fail(
        document,
        schema,
        error=('list', ('list', 'type'), errors.BAD_TYPE, schema['list']['type']),
    )


def test_issue_250_no_type_pass_on_list():
    # https://github.com/pyeve/cerberus/issues/250
    schema = {
        'list': {
            'schema': {
                'allow_unknown': True,
                'type': 'dict',
                'schema': {'a': {'type': 'string'}},
            }
        }
    }
    document = {'list': [{'a': 'known', 'b': 'unknown'}]}
    assert_normalized(document, document, schema)


def test_issue_250_no_type_fail_on_dict():
    # https://github.com/pyeve/cerberus/issues/250
    schema = {
        'list': {'schema': {'allow_unknown': True, 'schema': {'a': {'type': 'string'}}}}
    }
    document = {'list': {'a': {'a': 'known'}}}
    assert_fail(
        document,
        schema,
        error=(
            'list',
            ('list', 'schema'),
            errors.BAD_TYPE_FOR_SCHEMA,
            schema['list']['schema'],
        ),
    )


def test_issue_250_no_type_fail_pass_on_other():
    # https://github.com/pyeve/cerberus/issues/250
    schema = {
        'list': {'schema': {'allow_unknown': True, 'schema': {'a': {'type': 'string'}}}}
    }
    document = {'list': 1}
    assert_normalized(document, document, schema)


def test_allow_unknown_with_of_rules():
    # https://github.com/pyeve/cerberus/issues/251
    schema = {
        'test': {
            'oneof': [
                {
                    'type': 'dict',
                    'allow_unknown': True,
                    'schema': {'known': {'type': 'string'}},
                },
                {'type': 'dict', 'schema': {'known': {'type': 'string'}}},
            ]
        }
    }
    # check regression and that allow unknown does not cause any different
    # than expected behaviour for one-of.
    document = {'test': {'known': 's'}}
    assert_fail(
        document,
        schema,
        error=('test', ('test', 'oneof'), errors.ONEOF, schema['test']['oneof']),
    )
    # check that allow_unknown is actually applied
    document = {'test': {'known': 's', 'unknown': 'asd'}}
    assert_success(document, schema)


def test_271_normalising_tuples():
    # https://github.com/pyeve/cerberus/issues/271
    schema = {
        'my_field': {'type': 'list', 'schema': {'type': ('string', 'number', 'dict')}}
    }
    document = {'my_field': ('foo', 'bar', 42, 'albert', 'kandinsky', {'items': 23})}
    assert_success(document, schema)

    normalized = Validator(schema).normalized(document)
    assert normalized['my_field'] == (
        'foo',
        'bar',
        42,
        'albert',
        'kandinsky',
        {'items': 23},
    )


def test_allow_unknown_wo_schema():
    # https://github.com/pyeve/cerberus/issues/302
    v = Validator({'a': {'type': 'dict', 'allow_unknown': True}})
    v({'a': {}})


def test_allow_unknown_with_purge_unknown():
    validator = Validator(purge_unknown=True)
    schema = {'foo': {'type': 'dict', 'allow_unknown': True}}
    document = {'foo': {'bar': True}, 'bar': 'foo'}
    expected = {'foo': {'bar': True}}
    assert_normalized(document, expected, schema, validator)


def test_allow_unknown_with_purge_unknown_subdocument():
    validator = Validator(purge_unknown=True)
    schema = {
        'foo': {
            'type': 'dict',
            'schema': {'bar': {'type': 'string'}},
            'allow_unknown': True,
        }
    }
    document = {'foo': {'bar': 'baz', 'corge': False}, 'thud': 'xyzzy'}
    expected = {'foo': {'bar': 'baz', 'corge': False}}
    assert_normalized(document, expected, schema, validator)


def test_purge_readonly():
    schema = {
        'description': {'type': 'string', 'maxlength': 500},
        'last_updated': {'readonly': True},
    }
    validator = Validator(schema=schema, purge_readonly=True)
    document = {'description': 'it is a thing'}
    expected = deepcopy(document)
    document['last_updated'] = 'future'
    assert_normalized(document, expected, validator=validator)


def test_defaults_in_allow_unknown_schema():
    schema = {'meta': {'type': 'dict'}, 'version': {'type': 'string'}}
    allow_unknown = {
        'type': 'dict',
        'schema': {
            'cfg_path': {'type': 'string', 'default': 'cfg.yaml'},
            'package': {'type': 'string'},
        },
    }
    validator = Validator(schema=schema, allow_unknown=allow_unknown)

    document = {'version': '1.2.3', 'plugin_foo': {'package': 'foo'}}
    expected = {
        'version': '1.2.3',
        'plugin_foo': {'package': 'foo', 'cfg_path': 'cfg.yaml'},
    }
    assert_normalized(document, expected, schema, validator)
