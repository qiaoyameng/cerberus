# -*- coding: utf-8 -*-

from copy import deepcopy

from cerberus import MISSING, Validator, errors


combined_schema = {
    'old_name': {'rename': 'name'},
    'name': {'coerce': str},
    'amount': {'coerce': int},
    'role': {'default': 'user'},
    'settings': {
        'type': 'dict',
        'schema': {
            'theme': {'default': 'light'},
            'level': {'coerce': int},
        },
    },
    'tags': {'type': 'list', 'schema': {'coerce': str}},
}

combined_document = {
    'old_name': 42,
    'amount': '3',
    'settings': {'level': '5'},
    'tags': [1, 'a'],
    'junk': 'x',
}


def make_validator(schema, **kwargs):
    kwargs.setdefault('report_normalization', True)
    return Validator(schema, **kwargs)


def normalize_with_report(document, schema, **kwargs):
    validator = make_validator(schema, **kwargs)
    return validator, validator.normalized(document)


def test_actions_are_recorded_in_execution_order():
    validator, normalized = normalize_with_report(
        combined_document, combined_schema, purge_unknown=True
    )
    assert normalized == {
        'name': '42',
        'amount': 3,
        'role': 'user',
        'settings': {'level': 5, 'theme': 'light'},
        'tags': ['1', 'a'],
    }
    ops = [action.op for action in validator.normalization_report]
    # renames happen first, then purges, defaults, coercions and finally the
    # normalization of nested containers
    assert ops == [
        'rename',
        'purge_unknown',
        'default',
        'coerce',
        'coerce',
        'default',
        'coerce',
        'coerce',
    ]


def test_action_details():
    validator, _ = normalize_with_report(
        combined_document, combined_schema, purge_unknown=True
    )
    report = validator.normalization_report

    rename = report[0]
    assert rename.op == 'rename'
    assert rename.document_path == ('old_name',)
    assert rename.new_path == ('name',)
    assert rename.schema_path == ('old_name', 'rename')
    assert rename.old_value == 42
    assert rename.new_value == 42

    purge = report[1]
    assert purge.op == 'purge_unknown'
    assert purge.document_path == ('junk',)
    assert purge.old_value == 'x'
    assert purge.new_value is MISSING

    default = report[2]
    assert default.op == 'default'
    assert default.document_path == ('role',)
    assert default.schema_path == ('role', 'default')
    assert default.old_value is MISSING
    assert default.new_value == 'user'

    coerce = report[3]
    assert coerce.op == 'coerce'
    assert coerce.document_path == ('amount',)
    assert coerce.schema_path == ('amount', 'coerce')
    assert coerce.old_value == '3'
    assert coerce.new_value == 3


def test_nested_actions_are_locatable():
    validator, _ = normalize_with_report(combined_document, combined_schema)
    report = validator.normalization_report

    nested_default = report.actions[-3]
    assert nested_default.op == 'default'
    assert nested_default.document_path == ('settings', 'theme')
    assert nested_default.schema_path == ('settings', 'schema', 'theme', 'default')

    nested_coerce = report.actions[-2]
    assert nested_coerce.op == 'coerce'
    assert nested_coerce.document_path == ('settings', 'level')
    assert nested_coerce.old_value == '5'
    assert nested_coerce.new_value == 5

    item_coerce = report.actions[-1]
    assert item_coerce.op == 'coerce'
    assert item_coerce.document_path == ('tags', 0)
    assert item_coerce.old_value == 1
    assert item_coerce.new_value == '1'


def test_actions_after_rename_refer_to_original_input():
    validator, _ = normalize_with_report(combined_document, combined_schema)
    report = validator.normalization_report

    # the coercion happens on the renamed field 'name', but relates to the
    # original field 'old_name'
    coerce = next(a for a in report if a.document_path == ('name',))
    assert coerce.op == 'coerce'
    assert coerce.origin_path == ('old_name',)


def test_purged_values_are_distinguished_from_missing_values():
    validator, _ = normalize_with_report(
        combined_document, combined_schema, purge_unknown=True
    )
    report = validator.normalization_report

    purged = [a for a in report if a.op == 'purge_unknown']
    assert len(purged) == 1
    assert purged[0].document_path == ('junk',)
    assert purged[0].old_value == 'x'
    assert purged[0].new_value is MISSING

    # a field that was never provided yields no action at all, while a field
    # that was filled by a default records MISSING as its old value
    assert not any(a.document_path == ('never_provided',) for a in report)
    defaults = [a for a in report if a.op == 'default']
    assert all(a.old_value is MISSING for a in defaults)


def test_failed_coercion_is_not_recorded():
    def failing_coerce(value):
        raise ValueError('cannot coerce')

    schema = {'amount': {'coerce': failing_coerce}, 'other': {'coerce': int}}
    validator, normalized = normalize_with_report(
        {'amount': 'x', 'other': '1'}, schema
    )
    assert normalized is None
    assert errors.COERCION_FAILED in validator.document_error_tree.fetch_errors_from(
        ('amount',)
    )
    # only the successful coercion was recorded
    ops = [(a.op, a.document_path) for a in validator.normalization_report]
    assert ops == [('coerce', ('other',))]


def test_failed_rename_handler_is_not_recorded():
    def failing_handler(value):
        raise ValueError('cannot rename')

    schema = {'field': {'rename_handler': failing_handler}}
    validator, _ = normalize_with_report({'field': 1}, schema)
    assert len(validator.normalization_report) == 0


def test_replay_reproduces_normalized_document():
    validator, normalized = normalize_with_report(
        combined_document, combined_schema, purge_unknown=True
    )
    replayed = validator.normalization_report.replay(deepcopy(combined_document))
    assert replayed == normalized
    # the document passed to replay is not mutated
    assert combined_document['old_name'] == 42
    assert 'name' not in combined_document


def test_replay_with_nested_renames():
    schema = {
        'thing': {
            'type': 'dict',
            'schema': {
                'old': {'rename': 'new'},
                'new': {'coerce': int},
                'extra': {'default_setter': lambda doc: doc['new']},
            },
        }
    }
    document = {'thing': {'old': '2'}}
    validator, normalized = normalize_with_report(document, schema)
    # default setters run before coercion, thus 'extra' is set from the
    # not yet coerced value
    assert normalized == {'thing': {'new': 2, 'extra': '2'}}
    replayed = validator.normalization_report.replay(deepcopy(document))
    assert replayed == normalized


def test_report_is_reset_between_processings():
    validator = make_validator({'amount': {'coerce': int}})
    validator.normalized({'amount': '1'})
    assert len(validator.normalization_report) == 1
    validator.normalized({'amount': '2'})
    assert len(validator.normalization_report) == 1
    assert validator.normalization_report[0].new_value == 2


def test_keysrules_renames_are_recorded_and_replayable():
    schema = {'mapping': {'type': 'dict', 'keysrules': {'coerce': str.upper}}}
    document = {'mapping': {'aa': 1, 'b': 2}}
    validator = make_validator(schema)
    snapshot = deepcopy(document)
    normalized = validator.normalized(document)
    assert normalized == {'mapping': {'AA': 1, 'B': 2}}
    action = validator.normalization_report[0]
    assert action.op == 'rename'
    assert action.document_path == ('mapping', 'aa')
    assert action.new_path == ('mapping', 'AA')
    assert validator.normalization_report.replay(snapshot) == normalized


def test_purge_readonly_is_recorded():
    schema = {'token': {'readonly': True}, 'name': {'type': 'string'}}
    validator = make_validator(schema, purge_readonly=True)
    document = {'token': 'secret', 'name': 'foo'}
    snapshot = deepcopy(document)
    normalized = validator.normalized(document)
    assert normalized == {'name': 'foo'}
    action = validator.normalization_report[0]
    assert action.op == 'purge_readonly'
    assert action.document_path == ('token',)
    assert action.old_value == 'secret'
    assert action.new_value is MISSING
    assert validator.normalization_report.replay(snapshot) == normalized


def test_deeply_nested_actions_and_origin_paths():
    schema = {
        'items': {
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {
                    'sku': {'rename': 'id'},
                    'id': {'coerce': str},
                    'qty': {'default': 1},
                },
            },
        }
    }
    document = {'items': [{'sku': 7}, {'sku': '8', 'qty': 3}]}
    validator = make_validator(schema)
    snapshot = deepcopy(document)
    normalized = validator.normalized(document)
    assert normalized == {'items': [{'id': '7', 'qty': 1}, {'id': '8', 'qty': 3}]}
    coerce = next(a for a in validator.normalization_report if a.op == 'coerce')
    assert coerce.document_path == ('items', 0, 'id')
    assert coerce.origin_path == ('items', 0, 'sku')
    assert validator.normalization_report.replay(snapshot) == normalized


def test_report_is_also_recorded_during_validation():
    validator = make_validator({'amount': {'coerce': int, 'min': 1}})
    assert validator.validate({'amount': '1'})
    assert [a.op for a in validator.normalization_report] == ['coerce']
    assert validator.normalization_report.replay({'amount': '1'}) == {'amount': 1}


def test_disabled_reporting_keeps_results_and_errors():
    schema = {
        'old_name': {'rename': 'name'},
        'name': {'type': 'string'},
        'amount': {'coerce': int, 'max': 10},
        'role': {'default': 'user'},
    }
    document = {'old_name': 'foo', 'amount': '5', 'junk': 1}

    enabled = make_validator(schema, purge_unknown=True)
    assert enabled.validate(document)
    enabled_report = enabled.normalization_report

    disabled = Validator(schema, purge_unknown=True)
    assert disabled.validate(document)
    assert disabled.normalization_report is None
    assert disabled.document == enabled.document
    assert disabled.errors == enabled.errors
    assert disabled.document_error_tree == enabled.document_error_tree

    failing_document = {'amount': 'not a number'}
    assert not enabled.validate(failing_document)
    assert not disabled.validate(failing_document)
    assert disabled.errors == enabled.errors
    assert disabled.document_error_tree == enabled.document_error_tree
    assert enabled_report is not None
