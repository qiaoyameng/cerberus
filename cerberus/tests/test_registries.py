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


def test_frozen_validator_keeps_snapshot_when_registry_changes():
    rules_set_registry.add('frozen_rule', {'type': 'integer'})
    validator = Validator.frozen({'foo': 'frozen_rule'})
    rules_set_registry.add('frozen_rule', {'type': 'string'})
    assert_success({'foo': 1}, validator=validator)
    assert_fail({'foo': 'one'}, validator=validator)

    refrozen_validator = Validator.frozen({'foo': 'frozen_rule'})
    assert_success({'foo': 'one'}, validator=refrozen_validator)
    assert_fail({'foo': 1}, validator=refrozen_validator)


def test_frozen_validator_unaffected_by_registry_removal():
    rules_set_registry.add('removed_rule', {'type': 'integer'})
    validator = Validator.frozen({'foo': 'removed_rule'})
    rules_set_registry.remove('removed_rule')
    assert_success({'foo': 1}, validator=validator)
    assert_fail({'foo': 'one'}, validator=validator)


def test_frozen_validator_with_recursive_schema_and_mutating_callback():
    tree_v1 = {
        'value': {'type': 'integer', 'min': 0, 'check_with': 'mutate_tree'},
        'children': {
            'type': 'list',
            'schema': {'type': 'dict', 'schema': 'mutating_tree'},
        },
    }
    tree_v2 = {
        'value': {'type': 'integer', 'min': 100, 'check_with': 'mutate_tree'},
        'children': {
            'type': 'list',
            'schema': {'type': 'dict', 'schema': 'mutating_tree'},
        },
    }

    class TreeValidator(Validator):
        def _check_with_mutate_tree(self, field, value):
            # replaces the registered schema while a validation is running
            schema_registry.add('mutating_tree', tree_v2)

    schema_registry.add('mutating_tree', tree_v1)
    document = {'value': 5, 'children': [{'value': 7, 'children': []}]}

    frozen_validator = TreeValidator.frozen('mutating_tree')
    # the registry is mutated by the callback during this validation, still
    # the nested fields are validated against the frozen version
    assert_success(document, validator=frozen_validator)
    # and so is the next validation of the same instance
    assert_success(document, validator=frozen_validator)

    # a newly built instance sees the updated registry
    refrozen_validator = TreeValidator.frozen('mutating_tree')
    assert_fail(document, validator=refrozen_validator)

    # a plain validator keeps the dynamic semantics
    assert_fail(document, validator=TreeValidator('mutating_tree'))


def test_frozen_validator_reports_all_schema_errors_at_once():
    schema = {
        'a': 'missing_rules_set',
        'b': {'schema': 'missing_schema'},
        'c': {'no_such_rule': True},
    }
    with pytest.raises(SchemaError) as exc_info:
        Validator.frozen(schema)
    errors = exc_info.value.args[0]
    assert set(errors) == {'a', 'b', 'c'}
    assert 'missing_schema not found' in str(errors['b'])


def test_failed_freeze_leaves_no_valid_schemas_cache_residue():
    schema = {'a': {'type': 'integer'}, 'b': {'no_such_rule': True}}
    valid_schemas = Validator._valid_schemas.copy()
    with pytest.raises(SchemaError):
        Validator.frozen(schema)
    assert Validator._valid_schemas == valid_schemas


def test_frozen_validator_with_custom_registries_as_sources():
    from cerberus.schema import RulesSetRegistry

    source_registry = RulesSetRegistry({'freezable_rule': {'type': 'integer'}})
    validator = Validator.frozen(
        {'foo': 'freezable_rule'}, rules_set_registry=source_registry
    )
    source_registry.add('freezable_rule', {'type': 'string'})
    assert_success({'foo': 1}, validator=validator)
    assert_fail({'foo': 'one'}, validator=validator)
