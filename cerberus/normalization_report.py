"""
This module implements an optional report that records the changes applied to a
document during normalization. The report can be used to audit which fields were
renamed, purged, defaulted or coerced, and to replay the recorded actions on a
copy of the original document.
"""

from __future__ import absolute_import

from copy import deepcopy


class _MissingType(object):
    """Sentinel type marking the absence of a value in a recorded action."""

    def __repr__(self):
        return 'MISSING'

    def __bool__(self):
        return False

    __nonzero__ = __bool__


MISSING = _MissingType()
"""
Sentinel that marks the absent side of a recorded action: the ``old_value`` of a
field that was not provided (e.g. filled by a ``default``) or the ``new_value``
of a field that was purged.
"""


class NormalizationAction(object):
    """
    A single change that was applied to a document during normalization.

    Attributes:

    ``op``
        The kind of change: ``'rename'``, ``'purge_unknown'``,
        ``'purge_readonly'``, ``'default'`` or ``'coerce'``.
    ``document_path``
        The path of the affected field within the document at the moment the
        change was applied. For renames this is the path *before* the rename.
    ``schema_path``
        The path of the rule within the schema that caused the change.
    ``origin_path``
        The path at which the affected field can be found in the *original*
        document, i.e. prior renames are taken into account.
    ``old_value``
        The value before the change, or :data:`MISSING` if the field was not
        present in the document.
    ``new_value``
        The value after the change, or :data:`MISSING` if the field was
        removed.
    ``new_path``
        For renames only: the path of the field after the rename, otherwise
        :obj:`None`.
    """

    __slots__ = (
        'op',
        'document_path',
        'schema_path',
        'origin_path',
        'old_value',
        'new_value',
        'new_path',
    )

    def __init__(
        self,
        op,
        document_path,
        schema_path,
        origin_path,
        old_value=MISSING,
        new_value=MISSING,
        new_path=None,
    ):
        self.op = op
        self.document_path = tuple(document_path)
        self.schema_path = tuple(schema_path)
        self.origin_path = tuple(origin_path)
        self.old_value = old_value
        self.new_value = new_value
        self.new_path = tuple(new_path) if new_path is not None else None

    def __eq__(self, other):
        if not isinstance(other, NormalizationAction):
            return NotImplemented
        return all(
            getattr(self, attr) == getattr(other, attr) for attr in self.__slots__
        )

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __repr__(self):
        return (
            '{0.__class__.__name__}(op={0.op!r}, '
            'document_path={0.document_path!r}, schema_path={0.schema_path!r}, '
            'origin_path={0.origin_path!r}, old_value={0.old_value!r}, '
            'new_value={0.new_value!r}, new_path={0.new_path!r})'
        ).format(self)


class NormalizationReport(object):
    """
    An ordered collection of :class:`NormalizationAction` instances that were
    recorded while a document was normalized.

    The report is self-contained: :meth:`replay` applies the recorded actions
    to a copy of the original document and thereby reproduces the normalized
    document without needing a schema or validator.
    """

    def __init__(self):
        self.actions = []
        """ The recorded actions in the order they were applied.
            Type: :class:`list` of :class:`NormalizationAction` """

    def __iter__(self):
        return iter(self.actions)

    def __len__(self):
        return len(self.actions)

    def __getitem__(self, index):
        return self.actions[index]

    def __eq__(self, other):
        if not isinstance(other, NormalizationReport):
            return NotImplemented
        return self.actions == other.actions

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __repr__(self):
        return '{0.__class__.__name__}({0.actions!r})'.format(self)

    def record(
        self,
        op,
        document_path,
        schema_path,
        old_value=MISSING,
        new_value=MISSING,
        new_path=None,
    ):
        """
        Appends an action to the report. The ``origin_path`` is derived from
        the renames that were recorded so far.
        """
        action = NormalizationAction(
            op=op,
            document_path=document_path,
            schema_path=schema_path,
            origin_path=self._origin_path(document_path),
            old_value=old_value,
            new_value=new_value,
            new_path=new_path,
        )
        self.actions.append(action)
        return action

    def _origin_path(self, document_path):
        """Maps a path in the current document back to the original document
        by reverting the renames recorded so far, most recent first."""
        origin = tuple(document_path)
        for action in reversed(self.actions):
            if action.op != 'rename':
                continue
            new_path = action.new_path
            if origin[: len(new_path)] == new_path:
                origin = action.document_path + origin[len(new_path) :]
        return origin

    def replay(self, document):
        """
        Applies the recorded actions to a copy of ``document`` and returns the
        result. Replaying the report on the document that was originally
        normalized yields the normalized document.
        """
        result = deepcopy(document)
        for action in self.actions:
            container, key = _resolve_container(result, action.document_path)
            if action.op == 'rename':
                container[action.new_path[-1]] = container.pop(key)
            elif action.op in ('purge_unknown', 'purge_readonly'):
                container.pop(key, None)
            else:  # 'default', 'coerce'
                container[key] = deepcopy(action.new_value)
        return result


def _resolve_container(document, path):
    """Returns the container holding the last crumb of ``path`` and that
    crumb. Integer crumbs index sequences, all others index mappings."""
    container = document
    for crumb in path[:-1]:
        container = container[crumb]
    return container, path[-1]
