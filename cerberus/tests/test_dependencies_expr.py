# -*- coding: utf-8 -*-

from cerberus import errors, Validator
from cerberus.tests import assert_fail, assert_schema_error, assert_success


auth_schema = {
    'cert': {'type': 'string'},
    'account': {'type': 'string'},
    'token': {'type': 'string'},
    'payload': {
        'dependencies_expr': {
            'any': [
                {'field': 'cert'},
                {'all': [{'field': 'account'}, {'field': 'token'}]},
            ]
        }
    },
}


def test_expr_certificate_or_credentials():
    assert_success({'payload': 1, 'cert': 'x'}, auth_schema)
    assert_success({'payload': 1, 'account': 'a', 'token': 't'}, auth_schema)
    assert_success(
        {'payload': 1, 'cert': 'x', 'account': 'a', 'token': 't'}, auth_schema
    )
    assert_fail({'payload': 1}, auth_schema)
    assert_fail({'payload': 1, 'account': 'a'}, auth_schema)
    assert_fail({'payload': 1, 'token': 't'}, auth_schema)


def test_expr_is_not_evaluated_when_field_is_missing():
    assert_success({'cert': 'x'}, auth_schema)
    assert_success({}, auth_schema)


def test_expr_field_existence():
    schema = {
        'f': {'dependencies_expr': {'field': 'dep'}},
        'dep': {'nullable': True},
    }
    assert_success({'f': 1, 'dep': None}, schema)
    assert_fail({'f': 1}, schema)


def test_expr_distinguishes_missing_from_none():
    schema = {
        'f': {'dependencies_expr': {'field': 'cb', 'equals': None}},
        'cb': {'nullable': True},
    }
    assert_success({'f': 1, 'cb': None}, schema)
    _errors = assert_fail({'f': 1}, schema)
    assert _errors[0].info[0]['problem'] == 'missing'


def test_expr_equals_mismatch_reports_actual_value():
    schema = {
        'f': {'dependencies_expr': {'field': 'mode', 'equals': 'strict'}},
        'mode': {'type': 'string'},
    }
    assert_success({'f': 1, 'mode': 'strict'}, schema)
    _errors = assert_fail({'f': 1, 'mode': 'lax'}, schema)
    report = _errors[0].info[0]
    assert report['problem'] == 'mismatch'
    assert report['expected'] == 'strict'
    assert report['actual'] == 'lax'


def test_expr_not():
    schema = {'f': {'dependencies_expr': {'not': {'field': 'legacy'}}}, 'legacy': {}}
    assert_success({'f': 1}, schema)
    _errors = assert_fail({'f': 1, 'legacy': 1}, schema)
    assert _errors[0].info[0] == {'not': {'field': 'legacy'}}


def test_expr_nested_operators():
    schema = {
        'f': {
            'dependencies_expr': {
                'all': [
                    {'field': 'a'},
                    {'any': [{'field': 'b'}, {'not': {'field': 'c'}}]},
                ]
            }
        },
        'a': {},
        'b': {},
        'c': {},
    }
    assert_success({'f': 1, 'a': 1, 'b': 1}, schema)
    assert_success({'f': 1, 'a': 1, 'b': 1, 'c': 1}, schema)
    assert_success({'f': 1, 'a': 1}, schema)
    assert_fail({'f': 1, 'a': 1, 'c': 1}, schema)
    assert_fail({'f': 1, 'b': 1}, schema)


def test_expr_failure_report_tree():
    validator = Validator(auth_schema)
    assert not validator({'payload': 1, 'account': 'a'})
    assert len(validator._errors) == 1
    error = validator._errors[0]
    assert error.code == errors.DEPENDENCIES_EXPR.code
    assert error.rule == 'dependencies_expr'
    assert error.document_path == ('payload',)
    report = error.info[0]
    assert set(report) == {'any'}
    cert_report, credentials_report = report['any']
    assert cert_report['field'] == 'cert'
    assert cert_report['problem'] == 'missing'
    assert cert_report['path'] == ('cert',)
    assert credentials_report == {
        'all': [{'field': 'token', 'path': ('token',), 'problem': 'missing'}]
    }


def test_expr_all_reports_all_unfulfilled_operands():
    schema = {
        'f': {'dependencies_expr': {'all': [{'field': 'a'}, {'field': 'b'}]}},
        'a': {},
        'b': {},
    }
    _errors = assert_fail({'f': 1}, schema)
    report = _errors[0].info[0]
    assert [x['field'] for x in report['all']] == ['a', 'b']


def test_expr_relative_path_in_subdocument():
    schema = {
        'record': {
            'type': 'dict',
            'schema': {
                'token': {'type': 'string'},
                'name': {'dependencies_expr': {'field': 'token'}},
            },
        }
    }
    assert_success({'record': {'name': 'a', 'token': 't'}}, schema)
    validator = Validator(schema)
    assert not validator({'record': {'name': 'a'}})
    error = validator._errors[0].child_errors[0]
    assert error.document_path == ('record', 'name')
    assert error.info[0]['path'] == ('record', 'token')


def test_expr_root_document_path():
    schema = {
        'ca': {'type': 'string'},
        'record': {
            'type': 'dict',
            'schema': {
                'name': {'dependencies_expr': {'field': '^ca'}},
            },
        },
    }
    assert_success({'ca': 'x', 'record': {'name': 'a'}}, schema)
    validator = Validator(schema)
    assert not validator({'record': {'name': 'a'}})
    error = validator._errors[0].child_errors[0]
    assert error.document_path == ('record', 'name')
    assert error.info[0]['path'] == ('ca',)


def test_expr_in_list_of_records():
    schema = {
        'records': {
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {
                    'account': {'type': 'string'},
                    'token': {'type': 'string'},
                    'name': {
                        'type': 'string',
                        'dependencies_expr': {
                            'all': [{'field': 'account'}, {'field': 'token'}]
                        },
                    },
                },
            },
        }
    }
    document = {
        'records': [
            {'name': 'a', 'account': 'x', 'token': 'y'},
            {'name': 'b', 'account': 'x'},
            {'name': 'c'},
        ]
    }
    validator = Validator(schema)
    assert not validator(document)
    group_error = validator._errors[0]
    assert group_error.document_path == ('records',)
    item_errors = group_error.child_errors
    assert len(item_errors) == 2
    assert item_errors[0].document_path == ('records', 1)
    assert item_errors[1].document_path == ('records', 2)
    field_error = item_errors[0].child_errors[0]
    assert field_error.document_path == ('records', 1, 'name')
    assert field_error.info[0] == {
        'all': [
            {
                'field': 'token',
                'path': ('records', 1, 'token'),
                'problem': 'missing',
            }
        ]
    }


def test_expr_schema_must_be_a_mapping():
    assert_schema_error({}, {'f': {'dependencies_expr': 'cert'}})
    assert_schema_error({}, {'f': {'dependencies_expr': ['cert']}})


def test_expr_schema_empty_combination():
    assert_schema_error({}, {'f': {'dependencies_expr': {'all': []}}})
    assert_schema_error({}, {'f': {'dependencies_expr': {'any': []}}})


def test_expr_schema_invalid_operands():
    assert_schema_error({}, {'f': {'dependencies_expr': {'all': 'cert'}}})
    assert_schema_error({}, {'f': {'dependencies_expr': {'any': 42}}})
    assert_schema_error({}, {'f': {'dependencies_expr': {'not': ['cert']}}})
    assert_schema_error({}, {'f': {'dependencies_expr': {'field': 42}}})
    assert_schema_error({}, {'f': {'dependencies_expr': {'equals': 'x'}}})


def test_expr_schema_illegal_nodes():
    assert_schema_error({}, {'f': {'dependencies_expr': {'unknown': 'x'}}})
    assert_schema_error(
        {}, {'f': {'dependencies_expr': {'all': [{'field': 'a'}], 'field': 'b'}}}
    )
    assert_schema_error({}, {'f': {'dependencies_expr': {'all': ['cert']}}})


def test_expr_schema_validation_is_not_short_circuited():
    # the invalid empty combination in the second branch must be detected
    # although the evaluation against a document would short-circuit on the
    # first branch
    assert_schema_error(
        {},
        {'f': {'dependencies_expr': {'any': [{'field': 'a'}, {'all': []}]}}},
    )
    assert_schema_error(
        {},
        {'f': {'dependencies_expr': {'all': [{'field': 'a'}, {'any': []}]}}},
    )
