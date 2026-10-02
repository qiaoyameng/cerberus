# -*- coding: utf-8 -*-

from copy import deepcopy

from cerberus import Validator, errors


def make_schema(**overrides):
    schema = {
        'tenant': {'type': 'string', 'required': True},
        'id': {'type': 'integer', 'required': True, 'coerce': int},
        'parent_id': {'type': 'integer', 'coerce': int},
        'parent': {
            'type': 'dict',
            'schema': {
                'tenant': {'type': 'string'},
                'id': {'type': 'integer', 'coerce': int},
            },
        },
        'children': {
            'type': 'list',
            'schema': {'type': 'integer', 'coerce': int},
        },
        'children_refs': {
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {'id': {'type': 'integer', 'coerce': int}},
            },
        },
        'meta': {
            'type': 'dict',
            'schema': {'parent_id': {'type': 'integer', 'coerce': int}},
        },
        'groups': {
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {'parent_id': {'type': 'integer', 'coerce': int}},
            },
        },
    }
    schema.update(overrides)
    return schema


def errors_by_path(batch_errors):
    return {
        error.document_path: error
        for error in batch_errors
        if not error.is_group_error
    }


def test_batch_validates_forward_references_and_cycles():
    records = [
        {'tenant': 'acme', 'id': '1', 'parent_id': '2'},
        {'tenant': 'acme', 'id': '2', 'parent_id': '3'},
        {'tenant': 'acme', 'id': '3', 'parent_id': '1'},
    ]
    original = deepcopy(records)
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records,
        identity=('tenant', 'id'),
        references=('parent_id',),
    )

    assert batch_errors == []
    assert [record['id'] for record in valid] == [1, 2, 3]
    assert records == original
    assert valid[0]['parent_id'] == 2


def test_batch_reports_missing_reference_with_index_path_and_target():
    records = [
        {'tenant': 'acme', 'id': 1, 'parent_id': 2},
        {'tenant': 'acme', 'id': 3},
    ]
    validator = Validator(make_schema())

    _, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent_id',)
    )

    assert len(batch_errors) == 1
    error = batch_errors[0]
    assert error.document_path == (0, 'parent_id')
    assert error.code == errors.MISSING_REFERENCE.code
    assert error.rule == 'missing_reference'
    assert error.value == 2
    assert error.info == (2,)


def test_batch_composite_identity_is_tenant_scoped():
    records = [
        {'tenant': 'a', 'id': 1, 'parent': {'tenant': 'b', 'id': 2}},
        {'tenant': 'a', 'id': 2, 'parent_id': 2},
        {'tenant': 'b', 'id': 2},
    ]
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent',)
    )

    assert batch_errors == []
    assert valid[0]['parent']['id'] == 2


def test_batch_scalar_reference_inherits_remaining_identity_components():
    records = [
        {'tenant': 'a', 'id': 1, 'parent_id': 2},
        {'tenant': 'a', 'id': 2},
        {'tenant': 'b', 'id': 2, 'parent_id': 1},
        {'tenant': 'b', 'id': 1},
    ]
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent_id',)
    )

    assert batch_errors == []
    assert len(valid) == 4
    assert valid[2]['tenant'] == 'b'


def test_batch_reference_lists_and_nested_paths():
    records = [
        {
            'tenant': 'a',
            'id': 1,
            'children': ['2', 9],
            'children_refs': [{'id': '2'}, {'id': 9}],
            'meta': {'parent_id': '2'},
            'groups': [
                {'parent_id': '2'},
                {'parent_id': 8},
            ],
        },
        {'tenant': 'a', 'id': 2},
    ]
    validator = Validator(make_schema())

    _, batch_errors = validator.validated_many(
        records,
        identity=('tenant', 'id'),
        references=(
            'children',
            'children_refs',
            'meta.parent_id',
            'groups.parent_id',
        ),
    )

    by_path = errors_by_path(batch_errors)
    expected_paths = {
        (0, 'children', 1),
        (0, 'children_refs', 1),
        (0, 'groups', 1, 'parent_id'),
    }
    assert set(by_path) == expected_paths
    assert (0, 'meta', 'parent_id') not in by_path
    for error_path in expected_paths:
        assert by_path[error_path].code == errors.MISSING_REFERENCE.code


def test_batch_invalid_list_item_does_not_skip_other_reference_checks():
    records = [
        {'tenant': 'a', 'id': 1, 'children': ['bad', '2']},
        {'tenant': 'a', 'id': 2},
        {'tenant': 'a', 'id': 3, 'parent_id': 99},
    ]
    schema = make_schema(
        children={'type': 'list', 'schema': {'type': 'integer', 'coerce': int}}
    )
    validator = Validator(schema)

    _, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('children', 'parent_id')
    )
    by_path = errors_by_path(batch_errors)

    assert (0, 'children', 0) in by_path
    assert by_path[(0, 'children', 0)].rule == 'coerce'
    assert (0, 'children', 1) not in by_path
    assert (2, 'parent_id') in by_path
    assert by_path[(2, 'parent_id')].code == errors.MISSING_REFERENCE.code


def test_batch_reports_every_duplicate_identity():
    records = [
        {'tenant': 'a', 'id': 1},
        {'tenant': 'a', 'id': '1'},
        {'tenant': 'a', 'id': '1'},
        {'tenant': 'b', 'id': 1},
    ]
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id')
    )
    duplicate_errors = [
        error for error in batch_errors if error.code == errors.DUPLICATE_IDENTITY.code
    ]

    assert [error.document_path for error in duplicate_errors] == [
        (0,),
        (1,),
        (2,),
    ]
    for error in duplicate_errors:
        assert error.info[0] == (0, 1, 2)
    assert [record['id'] for record in valid] == [1]


def test_batch_invalid_identity_record_is_not_indexed():
    records = [
        {'tenant': 'a', 'id': 'bad', 'parent_id': 2},
        {'tenant': 'a', 'id': 2, 'parent_id': 3},
    ]
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent_id',)
    )
    by_path = errors_by_path(batch_errors)

    assert valid == []
    assert (0, 'id') in by_path
    assert (1, 'parent_id') in by_path
    assert by_path[(1, 'parent_id')].code == errors.MISSING_REFERENCE.code


def test_batch_unhashable_identity_record_is_not_indexed():
    records = [
        {'tenant': 'a', 'id': [1], 'parent_id': 3},
        {'tenant': 'a', 'id': 2},
    ]
    schema = make_schema()
    del schema['id']
    validator = Validator(schema, allow_unknown=True)

    valid, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent_id',)
    )
    by_path = errors_by_path(batch_errors)

    assert valid == [{'tenant': 'a', 'id': 2}]
    assert by_path[(0, 'id')].code == errors.INVALID_IDENTITY.code
    assert by_path[(0, 'parent_id')].code == errors.MISSING_REFERENCE.code


def test_batch_missing_identity_components_are_not_shared():
    records = [
        {'tenant': 'a', 'id': 1, 'parent_id': 2},
        {'id': 2},
        {'tenant': 'a', 'id': 3, 'parent_id': 2},
    ]
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent_id',)
    )
    by_path = errors_by_path(batch_errors)

    assert valid == []
    assert (0, 'parent_id') in by_path
    assert (2, 'parent_id') in by_path
    assert (1, 'tenant') in by_path


def test_batch_external_ids_can_be_allowed_globally_or_per_reference():
    records = [
        {'tenant': 'a', 'id': 1, 'parent_id': 99},
        {'tenant': 'a', 'id': 2, 'meta': {'parent_id': 88}},
        {'tenant': 'a', 'id': 3, 'parent': {'tenant': 'ext', 'id': 77}},
    ]
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records,
        identity=('tenant', 'id'),
        references=(
            {'path': 'parent_id', 'external_ids': (('a', 99),)},
            {'path': 'meta.parent_id', 'external_ids': (('a', 88),)},
            'parent',
        ),
        external_ids=(('ext', 77),),
    )

    assert batch_errors == []
    assert len(valid) == 3


def test_batch_identity_distinguishes_normalized_types():
    schema = {'id': {'type': ['integer', 'boolean']}}
    validator = Validator(schema)

    valid, batch_errors = validator.validated_many(
        [{'id': 1}, {'id': True}], identity='id'
    )

    assert batch_errors == []
    assert valid == [{'id': 1}, {'id': True}]


def test_batch_does_not_mutate_input_container_or_values():
    records = [
        {'tenant': 'a', 'id': '1', 'children': ['2']},
        {'tenant': 'a', 'id': '2'},
    ]
    original = deepcopy(records)
    original_container_type = type(records)
    original_children = records[0]['children']
    validator = Validator(make_schema())

    valid, _ = validator.validated_many(
        list(records), identity=('tenant', 'id'), references=('children',)
    )

    assert type(valid[0]['children']) is list
    assert records == original
    assert type(records) is original_container_type
    assert records[0]['children'] is original_children


def test_single_document_validate_remains_unchanged():
    validator = Validator({'id': {'type': 'integer', 'coerce': int}})

    assert validator.validate({'id': '1'})
    assert validator.document == {'id': 1}
    assert validator.validated({'id': '2'}) == {'id': 2}
    assert not validator.validate({'id': 'bad'})


def test_batch_continues_reference_checks_after_malformed_record():
    records = [
        'not a document',
        {'tenant': 'a', 'id': 1, 'parent_id': 'missing'},
        {'tenant': 'a', 'id': 2},
    ]
    validator = Validator(make_schema())

    valid, batch_errors = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent_id',)
    )
    by_path = errors_by_path(batch_errors)

    assert valid == [{'tenant': 'a', 'id': 2}]
    assert (0,) in by_path
    assert (1, 'parent_id') in by_path


def test_batch_returns_results_in_input_order():
    records = [
        {'tenant': 'a', 'id': 1, 'parent_id': 2},
        {'tenant': 'a', 'id': 'bad'},
        {'tenant': 'a', 'id': 2},
    ]
    validator = Validator(make_schema())

    valid, _ = validator.validated_many(
        records, identity=('tenant', 'id'), references=('parent_id',)
    )

    assert [record['id'] for record in valid] == [1, 2]
