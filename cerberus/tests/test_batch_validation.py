from copy import deepcopy

from cerberus import Validator, errors


def test_batch_accepts_forward_references_and_cycles():
    schema = {
        'id': {'type': 'integer'},
        'parent_id': {'type': 'integer', 'nullable': True},
    }
    documents = [
        {'id': 2, 'parent_id': 1},
        {'id': 1, 'parent_id': 1},
        {'id': 3, 'parent_id': 2},
    ]

    valid, batch_errors = Validator(schema).validated_batch(
        documents, identity_fields='id', references='parent_id'
    )

    assert valid == deepcopy(documents)
    assert batch_errors == []


def test_batch_reports_duplicate_identities_for_every_conflicting_record():
    schema = {'id': {'type': 'integer'}}
    documents = [{'id': 1}, {'id': 2}, {'id': 1}]

    valid, batch_errors = Validator(schema).validated_batch(
        documents, identity_fields='id'
    )

    assert valid == [{'id': 2}]
    assert [error.document_index for error in batch_errors] == [0, 2]
    assert all(error.rule == 'duplicate_identity' for error in batch_errors)
    assert all(error.target == (0, 2) for error in batch_errors)


def test_batch_validates_composite_identities_across_tenants():
    schema = {
        'tenant': {'type': 'string'},
        'id': {'coerce': str},
        'parent': {
            'type': 'dict',
            'nullable': True,
            'schema': {
                'tenant': {'type': 'string'},
                'id': {'coerce': str},
            },
        },
    }
    documents = [
        {'tenant': 'a', 'id': 1, 'parent': None},
        {'tenant': 'a', 'id': 2, 'parent': {'tenant': 'a', 'id': 1}},
        {'tenant': 'b', 'id': 1, 'parent': {'tenant': 'b', 'id': 9}},
        {'tenant': 'a', 'id': 3, 'parent': {'tenant': 'b', 'id': 1}},
    ]

    valid, batch_errors = Validator(schema).validated_batch(
        documents,
        identity_fields=['tenant', 'id'],
        references={'path': 'parent', 'fields': ['tenant', 'id']},
    )

    assert valid == [
        {'tenant': 'a', 'id': '1', 'parent': None},
        {'tenant': 'a', 'id': '2', 'parent': {'tenant': 'a', 'id': '1'}},
        {'tenant': 'a', 'id': '3', 'parent': {'tenant': 'b', 'id': '1'}},
    ]
    assert len(batch_errors) == 1
    assert batch_errors[0].document_index == 2
    assert batch_errors[0].field_path == ('parent',)
    assert batch_errors[0].target == {'tenant': 'b', 'id': '9'}


def test_batch_checks_list_and_nested_references_after_one_bad_record():
    schema = {
        'tenant': {'type': 'string'},
        'id': {'coerce': str},
        'relations': {
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {'target_id': {'coerce': str}},
            },
        },
    }
    documents = [
        {'tenant': 'a', 'id': 1, 'relations': [{'target_id': 'missing'}]},
        {'id': 2, 'relations': [{'target_id': '4'}]},
        {
            'tenant': 'a',
            'id': 3,
            'relations': [{'target_id': 'external'}],
        },
    ]

    valid, batch_errors = Validator(schema).validated_batch(
        documents,
        identity_fields=['tenant', 'id'],
        references={
            'path': 'relations',
            'fields': [{'field': 'id', 'path': 'target_id'}],
            'source_fields': [
                {'field': 'tenant', 'path': 'tenant'},
                {'field': 'id', 'path': 'target_id'},
            ],
        },
        external_ids=[('a', 'external')],
    )

    assert valid == [
        {'tenant': 'a', 'id': '3', 'relations': [{'target_id': 'external'}]}
    ]
    assert [error.document_index for error in batch_errors] == [0, 1, 1]
    assert batch_errors[0].field_path == ('relations', 0)
    assert batch_errors[0].target == {'target_id': 'missing'}
    identity_error = next(error for error in batch_errors if error.rule == 'identity')
    assert identity_error.field_path == ('tenant',)
    reference_errors = [
        error for error in batch_errors if error.rule == 'exists'
    ]
    assert [error.document_index for error in reference_errors] == [0, 1]


def test_batch_does_not_index_invalid_identity_or_share_missing_values():
    schema = {'id': {'type': 'integer'}, 'parent_id': {'type': 'integer'}}
    documents = [
        {'id': 'bad', 'parent_id': 1},
        {'parent_id': 99},
        {'id': 1, 'parent_id': None},
    ]

    valid, batch_errors = Validator(schema).validated_batch(
        documents, identity_fields='id', references='parent_id'
    )

    assert valid == []
    paths = [error.document_path for error in batch_errors]
    assert (0, 'id') in paths
    assert (1, 'id') in paths
    assert (1, 'parent_id') in paths


def test_batch_normalizes_without_mutating_input_and_preserves_order():
    schema = {'id': {'coerce': int}, 'parent_id': {'coerce': int}}
    documents = [{'id': '2', 'parent_id': '1'}, {'id': '1', 'parent_id': '2'}]
    original = deepcopy(documents)

    validator = Validator(schema)
    valid, batch_errors = validator.validated_batch(
        documents, identity_fields='id', references='parent_id'
    )

    assert documents == original
    assert valid == [
        {'id': 2, 'parent_id': 1},
        {'id': 1, 'parent_id': 2},
    ]
    assert batch_errors == []
    assert validator.document is None


def test_validate_batch_reports_boolean_and_supports_external_ids():
    schema = {'id': {'type': 'integer'}, 'parent_id': {'type': 'integer'}}
    documents = [
        {'id': 1, 'parent_id': 99},
        {'id': 2, 'parent_id': 1},
    ]

    validator = Validator(schema)
    assert validator.validate_batch(
        documents,
        identity_fields='id',
        references='parent_id',
        external_ids=[99],
    )
    assert validator.valid_documents == documents


def test_single_document_validation_remains_unchanged():
    schema = {'id': {'coerce': int}}
    validator = Validator(schema)

    assert validator.validate({'id': '1'})
    assert validator.document == {'id': 1}
    assert not validator.validate({'id': 'bad'})
    assert errors.COERCION_FAILED in validator._errors
