# -*- coding: utf-8 -*-

import pytest

from cerberus import schema_registry, rules_set_registry, SchemaError, Validator
from cerberus.tests import (
    assert_fail,
    assert_normalized,
    assert_schema_error,
    assert_success,
)


def test_schema_registry_simple():
    schema_registry.add('foo', {'bar': {'type': 'string'}})
    schema = {'a': {'schema': 'foo'}, 'b': {'schema': 'foo'}}
    document = {'a': {'bar': 'a'}, 'b': {'bar': 'b'}}
    assert_success(document, schema)


def test_top_level_reference():
    schema_registry.add('peng', {'foo': {'type': 'integer'}})
    document = {'foo': 42}
    assert_success(document, 'peng')


def test_rules_set_simple():
    rules_set_registry.add('foo', {'type': 'integer'})
    assert_success({'bar': 1}, {'bar': 'foo'})
    assert_fail({'bar': 'one'}, {'bar': 'foo'})


def test_allow_unknown_as_reference():
    rules_set_registry.add('foo', {'type': 'number'})
    v = Validator(allow_unknown='foo')
    assert_success({0: 1}, {}, v)
    assert_fail({0: 'one'}, {}, v)


def test_recursion():
    rules_set_registry.add('self', {'type': 'dict', 'allow_unknown': 'self'})
    v = Validator(allow_unknown='self')
    assert_success({0: {1: {2: {}}}}, {}, v)


def test_references_remain_unresolved(validator):
    rules_set_registry.extend(
        (('boolean', {'type': 'boolean'}), ('booleans', {'valuesrules': 'boolean'}))
    )
    validator.schema = {'foo': 'booleans'}
    assert 'booleans' == validator.schema['foo']
    assert 'boolean' == rules_set_registry._storage['booleans']['valuesrules']


def test_rules_registry_with_anyof_type():
    rules_set_registry.add('string_or_integer', {'anyof_type': ['string', 'integer']})
    schema = {'soi': 'string_or_integer'}
    assert_success({'soi': 'hello'}, schema)


def test_schema_registry_with_anyof_type():
    schema_registry.add('soi_id', {'id': {'anyof_type': ['string', 'integer']}})
    schema = {'soi': {'schema': 'soi_id'}}
    assert_success({'soi': {'id': 'hello'}}, schema)


def test_normalization_with_rules_set():
    # https://github.com/pyeve/cerberus/issues/283
    rules_set_registry.add('foo', {'default': 42})
    assert_normalized({}, {'bar': 42}, {'bar': 'foo'})
    rules_set_registry.add('foo', {'default_setter': lambda _: 42})
    assert_normalized({}, {'bar': 42}, {'bar': 'foo'})
    rules_set_registry.add('foo', {'type': 'integer', 'nullable': True})
    assert_success({'bar': None}, {'bar': 'foo'})


def test_rules_set_with_dict_field():
    document = {'a_dict': {'foo': 1}}
    schema = {'a_dict': {'type': 'dict', 'schema': {'foo': 'rule'}}}

    # the schema's not yet added to the valid ones, so test the faulty first
    rules_set_registry.add('rule', {'tüpe': 'integer'})
    assert_schema_error(document, schema)

    rules_set_registry.add('rule', {'type': 'integer'})
    assert_success(document, schema)


#
# frozen validators
#

TREE_SCHEMA_V1 = {
    'name': {'type': 'string', 'check_with': 'mutate_tree_schema'},
    'children': {'type': 'list', 'schema': {'type': 'dict', 'schema': 'tree_node'}},
}
TREE_SCHEMA_V2 = {
    'name': {'type': 'integer'},
    'children': {'type': 'list', 'schema': {'type': 'dict', 'schema': 'tree_node'}},
}
TREE_DOCUMENT = {'name': 'a', 'children': [{'name': 'b', 'children': []}]}


class TreeSchemaMutator(Validator):
    """Replaces the ``tree_node`` schema definition when a ``name`` field is
    validated."""

    def _check_with_mutate_tree_schema(self, field, value):
        schema_registry.add('tree_node', TREE_SCHEMA_V2)


def test_frozen_validator_keeps_snapshot_while_registry_is_mutated():
    schema_registry.add('tree_node', TREE_SCHEMA_V1)
    frozen_validator = TreeSchemaMutator.frozen('tree_node')

    # a dynamic validator resolves references lazily and thus picks up the
    # mutated definition within the very same validation
    assert_fail(TREE_DOCUMENT, validator=TreeSchemaMutator('tree_node'))

    # the frozen instance keeps the rules that were current when it was
    # built, both in the validation that mutates the registry and in
    # subsequent validations
    assert_success(TREE_DOCUMENT, validator=frozen_validator)
    assert_success(TREE_DOCUMENT, validator=frozen_validator)

    # a newly frozen instance sees the updated definition
    assert_fail(TREE_DOCUMENT, validator=TreeSchemaMutator.frozen('tree_node'))


def test_frozen_validator_reports_all_problems_at_once():
    schema_registry.add('frozen_inner', {'x': 'missing_ruleset'})
    schema = {
        'a': 'missing_field_ruleset',
        'b': {'schema': 'missing_schema'},
        'c': {'schema': 'frozen_inner'},
        'd': {'type': 'no_such_type'},
    }
    with pytest.raises(SchemaError) as excinfo:
        Validator.frozen(schema)
    message = str(excinfo.value)
    for name in (
        'missing_field_ruleset',
        'missing_schema',
        'missing_ruleset',
        'no_such_type',
    ):
        assert name in message


def test_frozen_validator_failed_build_leaves_no_cache_residue():
    schema_registry.add('frozen_valid_inner', {'x': {'type': 'integer'}})
    schema = {
        'good': {'schema': 'frozen_valid_inner'},
        'bad': {'type': 'definitely_not_a_type'},
    }
    valid_schemas_before = Validator._valid_schemas.copy()
    with pytest.raises(SchemaError):
        Validator.frozen(schema)
    assert Validator._valid_schemas == valid_schemas_before


def test_frozen_validator_with_recursive_rules_set():
    rules_set_registry.add(
        'frozen_self', {'type': 'dict', 'allow_unknown': 'frozen_self'}
    )
    validator = Validator.frozen(allow_unknown='frozen_self')
    assert_success({0: {1: {2: {}}}}, {}, validator)

    # later changes to the source registry don't affect the frozen instance
    rules_set_registry.remove('frozen_self')
    assert_success({0: {1: {2: {}}}}, {}, validator)
    rules_set_registry.add('frozen_self', {'type': 'integer'})
    assert_success({0: {1: {2: {}}}}, {}, validator)


def test_frozen_validator_not_affected_by_definition_mutation():
    rules_set_registry.add('frozen_mutable', {'type': 'integer'})
    validator = Validator.frozen({'a': 'frozen_mutable'})
    assert validator.schema_registry is not schema_registry
    assert validator.rules_set_registry is not rules_set_registry

    rules_set_registry.all()['frozen_mutable']['type'] = 'string'
    assert_success({'a': 1}, validator=validator)
    assert_fail({'a': 'one'}, validator=validator)
