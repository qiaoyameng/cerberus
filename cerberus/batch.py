from __future__ import absolute_import

from collections import defaultdict
from copy import deepcopy

from cerberus import errors
from cerberus.platform import Hashable, Mapping, Sequence, _str_type


class BatchValidationResult(tuple):
    """A tuple of ``(valid_documents, errors)`` with named accessors."""

    __slots__ = ()

    def __new__(cls, valid, errors):
        return super(BatchValidationResult, cls).__new__(cls, (valid, errors))

    @property
    def valid(self):
        return self[0]

    @property
    def errors(self):
        return self[1]


class _IdentityKey(tuple):
    __slots__ = ()

    def __new__(cls, values):
        if not isinstance(values, tuple):
            values = (values,)
        tagged = tuple((type(value), value) for value in values)
        return super(_IdentityKey, cls).__new__(cls, tagged)

    def __repr__(self):
        return repr(tuple(value for _, value in self))


def _as_path(path):
    if isinstance(path, _str_type):
        return tuple(part for part in path.split('.') if part != '')
    if isinstance(path, Hashable) and not isinstance(path, Sequence):
        return (path,)
    if isinstance(path, Sequence):
        result = ()
        for part in path:
            if not isinstance(part, Hashable):
                return None
            result += (part,)
        return result
    return None


def _hashable(value):
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _normalize_identity(identity):
    if identity is None:
        return ()
    if isinstance(identity, Mapping) and 'fields' in identity:
        fields = identity['fields']
    else:
        fields = identity
    if isinstance(fields, _str_type) or not isinstance(fields, Sequence):
        fields = (fields,)

    result = ()
    for field in fields:
        path = _as_path(field)
        if path is None:
            raise TypeError('Identity fields must be hashable paths.')
        result += (path,)
    return result


def _normalize_references(references):
    if references is None:
        return ()
    if isinstance(references, Mapping) and 'path' not in references:
        raw_declarations = []
        for source, options in references.items():
            if isinstance(options, Mapping):
                raw_declarations.append((source, options))
            else:
                raw_declarations.append((source, {'fields': options}))
        raw_declarations = tuple(raw_declarations)
    elif isinstance(references, _str_type) or not isinstance(references, Sequence):
        raw_declarations = (references,)
    else:
        raw_declarations = tuple(references)

    result = ()
    for raw in raw_declarations:
        if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[1], Mapping):
            path, options = raw
        elif isinstance(raw, Mapping) and ('path' in raw or 'field' in raw):
            path = raw.get('path', raw.get('field'))
            options = raw
        else:
            path = raw
            options = {}

        source_path = _as_path(path)
        if source_path is None:
            raise TypeError('Reference paths must be hashable paths.')

        result += (
            {
                'path': source_path,
                'multiple': options.get('multiple'),
                'fields': _normalize_reference_fields(
                    options.get('fields', options.get('target'))
                ),
                'external_ids': tuple(
                    options.get('external_ids', options.get('external', ()))
                ),
            },
        )
    return result


def _normalize_reference_fields(fields):
    if fields is None:
        return None
    if isinstance(fields, _str_type) or isinstance(fields, Mapping):
        return fields
    if isinstance(fields, Sequence):
        return tuple(fields)
    return fields


def _lookup_path(document, path):
    current = document
    for part in path:
        if isinstance(current, Mapping):
            if part not in current:
                return None, False
            current = current[part]
        elif (
            isinstance(current, Sequence)
            and not isinstance(current, _str_type)
            and isinstance(part, int)
            and 0 <= part < len(current)
        ):
            current = current[part]
        else:
            return None, False
    return current, True


def _identity_from_value(
    value,
    identity_paths,
    fields=None,
    source_document=None,
):
    if len(identity_paths) == 1 and (
        fields is None or not isinstance(fields, Mapping)
    ):
        if value is None or not _hashable(value):
            return None
        if isinstance(value, Mapping):
            path = _reference_component_paths(identity_paths, fields)[0]
            component, found = _lookup_component(
                value, source_document, path, identity_paths[0]
            )
            if not found or component is None or not _hashable(component):
                return None
            value = component
        return _IdentityKey((value,))

    if isinstance(value, Mapping):
        values = ()
        value_paths = _reference_component_paths(identity_paths, fields)
        for identity_path, component_path in zip(identity_paths, value_paths):
            component, found = _lookup_component(
                value, source_document, component_path, identity_path
            )
            if not found or component is None or not _hashable(component):
                return None
            values += (component,)
        return _IdentityKey(values)

    if isinstance(value, Sequence) and not isinstance(value, _str_type):
        values = tuple(value)
        if len(values) != len(identity_paths):
            return None
        if any(component is None or not _hashable(component) for component in values):
            return None
        return _IdentityKey(values)

    if source_document is not None and _hashable(value):
        values = ()
        for identity_index, identity_path in enumerate(identity_paths):
            if identity_index == len(identity_paths) - 1:
                values += (value,)
                continue
            component, found = _lookup_path(source_document, identity_path)
            if not found or component is None or not _hashable(component):
                return None
            values += (component,)
        return _IdentityKey(values)

    return None


def _lookup_component(
    reference_value, source_document, component_path, identity_path
):
    component, found = _lookup_path(reference_value, component_path)
    if found:
        return component, True
    if source_document is not None:
        component, found = _lookup_path(source_document, component_path)
        if found:
            return component, True
        component, found = _lookup_path(source_document, identity_path)
        if found:
            return component, True
    return None, False


def _reference_component_paths(identity_paths, fields):
    if fields is None:
        return identity_paths
    if isinstance(fields, Mapping):
        result = ()
        for identity_path in identity_paths:
            field = identity_path[-1]
            relative_path = fields.get(field, fields.get(identity_path, field))
            path = _as_path(relative_path)
            if path is None:
                raise TypeError('Reference component paths must be hashable.')
            result += (path,)
        return result
    if isinstance(fields, _str_type) or not isinstance(fields, Sequence):
        fields = (fields,)
    result = ()
    for field in fields:
        path = _as_path(field)
        if path is None:
            raise TypeError('Reference component paths must be hashable.')
        result += (path,)
    if len(result) == 1 and len(identity_paths) > 1:
        result = identity_paths[:-1] + result
    if len(result) != len(identity_paths):
        raise TypeError('Reference fields must match the number of identity fields.')
    return result


def _external_identities(values, identity_paths, fields=None):
    result = set()
    for value in values:
        key = (
            _identity_from_value(value, identity_paths, fields)
            if identity_paths
            else None
        )
        if key is None:
            raise TypeError('External identities must match the declared identity.')
        result.add(key)
    return result


def _path_is_error_path(error_paths, path):
    return any(
        error_path[: len(path)] == path or path[: len(error_path)] == error_path
        for error_path in error_paths
        if error_path
    )


def _record_error_paths(errors, index):
    prefix = (index,)
    result = ()
    for error in errors:
        if error.document_path[: len(prefix)] != prefix:
            continue
        for error_path in _leaf_document_paths(error):
            result += (error_path[len(prefix):],)
    return result


def _leaf_document_paths(error):
    child_errors = error.child_errors
    if child_errors:
        result = ()
        for child_error in child_errors:
            result += _leaf_document_paths(child_error)
        return result
    return (error.document_path,)


def _iter_reference_locations(document, path, multiple, error_paths):
    if not path:
        yield (), document, False
        return

    locations = [((), document)]
    for part in path:
        next_locations = []
        for location_path, value in locations:
            if isinstance(value, Mapping) and part in value:
                next_locations.append((location_path + (part,), value[part]))
            elif (
                isinstance(value, Sequence)
                and not isinstance(value, _str_type)
                and isinstance(part, int)
                and 0 <= part < len(value)
            ):
                next_locations.append((location_path + (part,), value[part]))
            elif isinstance(value, Sequence) and not isinstance(value, _str_type):
                for item_index, item in enumerate(value):
                    if isinstance(item, Mapping) and part in item:
                        next_locations.append(
                            (location_path + (item_index, part), item[part])
                        )
        locations = next_locations

    for location_path, value in locations:
        if value is None:
            continue
        if _path_is_error_path(error_paths, location_path):
            continue
        if multiple is None:
            effective_multiple = isinstance(value, list)
        else:
            effective_multiple = multiple

        if effective_multiple:
            if not isinstance(value, Sequence) or isinstance(value, _str_type):
                yield location_path, value, True
                continue
            for item_index, item in enumerate(value):
                if item is None:
                    continue
                item_path = location_path + (item_index,)
                if _path_is_error_path(error_paths, item_path):
                    continue
                yield item_path, item, False
        else:
            yield location_path, value, False


def _add_error(validator, index, path, definition, constraint, value, *info):
    rule = definition.rule
    schema_path = (path[-1], rule) if path and rule else ((rule,) if rule else ())
    error = errors.ValidationError(
        (index,) + path,
        schema_path,
        definition.code,
        rule,
        constraint,
        value,
        info,
    )
    validator._error([error])


def validate_records(
    parent_validator,
    documents,
    schema=None,
    identity=None,
    references=None,
    external_ids=None,
    update=False,
    normalize=True,
):
    if not isinstance(documents, Sequence) or isinstance(documents, _str_type):
        raise TypeError('Batch documents must be provided as a sequence.')

    identity_paths = _normalize_identity(identity)
    reference_declarations = _normalize_references(references)
    allowed_external_ids = _external_identities(external_ids or (), identity_paths)

    parent_validator._errors = errors.ErrorList()
    parent_validator.document_error_tree = errors.DocumentErrorTree()
    parent_validator.schema_error_tree = errors.SchemaErrorTree()
    parent_validator.error_handler.start(parent_validator)

    normalized_documents = []
    valid_after_schema = []
    identities = defaultdict(list)

    for index, original in enumerate(documents):
        document = deepcopy(original)
        child_kwargs = {} if schema is None else {'schema': schema}
        record_validator = parent_validator._get_child_validator(
            document_crumb=(index,), **child_kwargs
        )
        if not isinstance(document, Mapping):
            record_valid = False
            normalized = None
            _add_error(
                parent_validator,
                index,
                (),
                errors.CUSTOM,
                None,
                original,
                'record is not a document, must be a dict',
            )
        else:
            record_valid = record_validator.validate(
                document, schema=None, update=update, normalize=normalize
            )
            normalized = record_validator.document
            parent_validator._error(record_validator._errors)

        normalized_documents.append(normalized)
        valid_after_schema.append(record_valid)

        if not isinstance(normalized, Mapping):
            continue

        error_paths = _record_error_paths(parent_validator._errors, index)
        key = None
        if identity_paths:
            identity_values = ()
            identity_available = True
            for identity_path in identity_paths:
                identity_value, identity_found = _lookup_path(
                    normalized, identity_path
                )
                if (
                    not identity_found
                    or identity_value is None
                    or _path_is_error_path(error_paths, identity_path)
                ):
                    identity_available = False
                    break
                if not _hashable(identity_value):
                    _add_error(
                        parent_validator,
                        index,
                        identity_path,
                        errors.INVALID_IDENTITY,
                        identity_path,
                        identity_value,
                    )
                    identity_available = False
                    break
                identity_values += (identity_value,)
            if identity_available:
                key = _IdentityKey(identity_values)
                identities[key].append(index)

    for key, indexes in identities.items():
        if len(indexes) > 1:
            for index in indexes:
                _add_error(
                    parent_validator,
                    index,
                    (),
                    errors.DUPLICATE_IDENTITY,
                    tuple(identity_paths),
                    key,
                    tuple(indexes),
                )

    for declaration in reference_declarations:
        allowed = set(allowed_external_ids)
        allowed.update(
            _external_identities(
                declaration['external_ids'],
                identity_paths,
                declaration.get('fields'),
            )
        )
        path = declaration['path']

        for index, document in enumerate(normalized_documents):
            if not isinstance(document, Mapping):
                continue
            error_paths = _record_error_paths(parent_validator._errors, index)
            for error_path, value, malformed in _iter_reference_locations(
                document, path, declaration['multiple'], error_paths
            ):
                if malformed:
                    _add_error(
                        parent_validator,
                        index,
                        error_path,
                        errors.INVALID_REFERENCE,
                        path,
                        value,
                    )
                    continue

                key = (
                    _identity_from_value(
                        value,
                        identity_paths,
                        declaration.get('fields'),
                        document,
                    )
                    if identity_paths
                    else None
                )
                if key is None:
                    _add_error(
                        parent_validator,
                        index,
                        error_path,
                        errors.INVALID_REFERENCE,
                        path,
                        value,
                    )
                elif key not in identities and key not in allowed:
                    _add_error(
                        parent_validator,
                        index,
                        error_path,
                        errors.MISSING_REFERENCE,
                        path,
                        value,
                        value,
                    )

    parent_validator._errors.sort()
    parent_validator.document_error_tree = errors.DocumentErrorTree(
        parent_validator._errors
    )
    parent_validator.schema_error_tree = errors.SchemaErrorTree(
        parent_validator._errors
    )
    parent_validator.error_handler.end(parent_validator)

    valid_indexes = []
    for index, record_valid in enumerate(valid_after_schema):
        prefix = (index,)
        has_error = any(
            error.document_path[: len(prefix)] == prefix
            for error in parent_validator._errors
        )
        if record_valid and not has_error:
            valid_indexes.append(index)

    valid_documents = [normalized_documents[index] for index in valid_indexes]
    parent_validator.document = deepcopy(documents)
    return BatchValidationResult(valid_documents, parent_validator._errors)
