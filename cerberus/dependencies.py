from __future__ import absolute_import

from cerberus import errors
from cerberus.errors import ErrorList, ValidationError
from cerberus.platform import Mapping, _str_type


ALL_KEYS = ('all', '$all')
ANY_KEYS = ('any', '$any')
NOT_KEYS = ('not', '$not')
FIELD_KEYS = ('field', '$field')
EQUAL_KEYS = ('eq', '$eq', 'equals', '$equals', 'value', '$value')


def _canonical_key(node, keys):
    for key in keys:
        if key in node:
            return key
    return None


def is_expression_node(node):
    if isinstance(node, _str_type):
        return True
    if not isinstance(node, Mapping):
        return False
    return any(
        _canonical_key(node, keys) is not None
        for keys in (ALL_KEYS, ANY_KEYS, NOT_KEYS, FIELD_KEYS)
    )


def is_expression(node):
    if not isinstance(node, Mapping):
        return is_expression_node(node)

    if any(key in node for key in FIELD_KEYS if key.startswith('$')):
        return True

    if any(
        _canonical_key(node, keys) is not None
        for keys in (ALL_KEYS, ANY_KEYS, NOT_KEYS)
    ):
        return True

    return False


def validate_expression(node, report, path=()):
    if isinstance(node, _str_type):
        if not node:
            report(path, 'Dependency field path must not be empty.')
        return

    if not isinstance(node, Mapping):
        report(path, 'Dependency expression must be a mapping or a field path.')
        return

    if not node:
        report(path, 'Dependency expression must not be empty.')
        return

    operators = (
        ('all', ALL_KEYS, 'list'),
        ('any', ANY_KEYS, 'list'),
        ('not', NOT_KEYS, 'expression'),
        ('field', FIELD_KEYS, 'path'),
    )
    present_operators = []

    for name, keys, operand_type in operators:
        present_operators.extend(key for key in keys if key in node)

    if not present_operators:
        report(path, 'Invalid dependency expression operator.')
        return

    if len(present_operators) > 1:
        report(
            path,
            'Dependency expression must contain exactly one operator, '
            'got: {}.'.format(', '.join(present_operators)),
        )

    for name, keys, operand_type in operators:
        key = _canonical_key(node, keys)
        if key is None:
            continue

        if operand_type == 'list':
            operands = node[key]
            if not isinstance(operands, list):
                report(path + (key,), 'Operator operand must be a list.')
            elif not operands:
                report(path + (key,), 'Operator must not be empty.')
            else:
                for index, operand in enumerate(operands):
                    validate_expression(operand, report, path + (key, index))
        elif operand_type == 'expression':
            operand = node[key]
            if not is_expression_node(operand) or isinstance(operand, list):
                report(path + (key,), 'Operator operand must be one expression.')
            else:
                validate_expression(operand, report, path + (key,))
        else:
            field_path = node[key]
            if not isinstance(field_path, _str_type) or not field_path:
                report(path + (key,), 'Field path must be a non-empty string.')

            equal_keys = [
                equal_key for equal_key in EQUAL_KEYS if equal_key in node
            ]
            if len(equal_keys) > 1:
                report(path + (equal_keys[1],), 'Only one value match is allowed.')

    recognized_keys = set()
    for _, keys, _ in operators:
        recognized_keys.update(key for key in keys if key in node)
    if _canonical_key(node, FIELD_KEYS) is not None:
        recognized_keys.update(key for key in EQUAL_KEYS if key in node)

    for key in set(node) - recognized_keys:
        report(path + (key,), 'Invalid dependency expression key.')


class DependencyExpressionEvaluator(object):
    def __init__(self, validator, field, expression):
        self.validator = validator
        self.field = field
        self.expression = expression
        self.document_path = validator.document_path + (field,)
        self.schema_path = validator.schema_path + (field, 'dependencies')

    def evaluate(self):
        return self._evaluate(self.expression, ())

    def _evaluate(self, node, path):
        if isinstance(node, _str_type):
            return self._evaluate_field(node, None, path)

        all_key = _canonical_key(node, ALL_KEYS)
        any_key = _canonical_key(node, ANY_KEYS)
        not_key = _canonical_key(node, NOT_KEYS)
        field_key = _canonical_key(node, FIELD_KEYS)

        if all_key is not None:
            return self._evaluate_composition(all_key, node[all_key], path, True)
        if any_key is not None:
            return self._evaluate_composition(any_key, node[any_key], path, False)
        if not_key is not None:
            return self._evaluate_not(not_key, node[not_key], path)
        return self._evaluate_field_match(node, field_key, path)

    def _evaluate_composition(self, operator, operands, path, require_all):
        failures = ErrorList()

        for index, operand in enumerate(operands):
            result = self._evaluate(operand, path + (operator, index))
            if require_all:
                if not result.success:
                    failures.append(result.error)
                    return self._group_error(
                        operator, path, {operator: operands}, failures
                    )
            elif result.success:
                return Result(True, None)
            else:
                failures.append(result.error)

        if require_all:
            return Result(True, None)
        return self._group_error(operator, path, {operator: operands}, failures)

    def _evaluate_not(self, not_key, operand, path):
        result = self._evaluate(operand, path + (not_key,))
        if result.success:
            return self._group_error(not_key, path, operand, ErrorList())
        return Result(True, None)

    def _evaluate_field_match(self, node, field_key, path):
        equal_key = _canonical_key(node, EQUAL_KEYS)
        expected = node[equal_key] if equal_key is not None else None
        field_path_crumb = (field_key, 'eq') if equal_key is not None else (field_key,)
        return self._evaluate_field(
            node[field_key],
            expected,
            path + field_path_crumb,
            equal_key is not None,
        )

    def _evaluate_field(self, field_path, expected, path, match_value=False):
        wanted_field, actual = self._lookup_field(field_path)

        if wanted_field is None:
            return Result(
                False,
                self._leaf_error(
                    path, errors.DEPENDENCIES_FIELD, field_path, None, (field_path,)
                ),
            )

        if match_value and actual != expected:
            return Result(
                False,
                self._leaf_error(
                    path, errors.DEPENDENCIES_FIELD_VALUE, expected, actual, (actual,)
                ),
            )

        return Result(True, None)

    def _leaf_error(self, path, code, constraint, value, info):
        return ValidationError(
            self.document_path,
            self.schema_path + path,
            code.code,
            code.rule,
            constraint,
            value,
            info,
        )

    def _group_error(self, operator, path, constraint, children):
        error = ValidationError(
            self.document_path,
            self.schema_path + path + (operator,),
            errors.DEPENDENCIES_EXPRESSION.code,
            errors.DEPENDENCIES_EXPRESSION.rule,
            constraint,
            None,
            (ErrorList(children),),
        )
        return Result(False, error)

    def _lookup_field(self, path):
        if path.startswith('^'):
            path = path[1:]
            if path.startswith('^'):
                context = self.validator.document
            else:
                context = self.validator.root_document
        else:
            context = self.validator.document

        parts = path.split('.')
        for part in parts:
            if not isinstance(context, Mapping) or part not in context:
                return None, None
            context = context[part]

        return parts[-1], context


class Result(object):
    def __init__(self, success, error):
        self.success = success
        self.error = error
