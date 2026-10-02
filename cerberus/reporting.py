from copy import deepcopy

from cerberus.platform import Mapping


class _Unset(object):
    def __repr__(self):
        return '<UNSET>'

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


class _Purged(object):
    def __repr__(self):
        return '<PURGED>'

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


UNSET = _Unset()
PURGED = _Purged()


class NormalizationChange(dict):
    def __init__(
        self,
        op,
        path,
        schema_path,
        old=UNSET,
        new=UNSET,
        original_path=None,
        new_path=None,
        target='value',
    ):
        super(NormalizationChange, self).__init__(
            op=op,
            path=tuple(path),
            original_path=tuple(original_path if original_path is not None else path),
            schema_path=tuple(schema_path),
            old=old,
            new=new,
        )
        if new_path is not None:
            self['new_path'] = tuple(new_path)
        if target != 'value':
            self['target'] = target

    def __getattr__(self, name):
        return self.get(name)


class NormalizationReport(object):
    UNSET = UNSET
    PURGED = PURGED

    def __init__(self, changes=None):
        self.changes = []
        self._renames = {}
        for change in changes or ():
            self.append(change)

    def __iter__(self):
        return iter(self.changes)

    def __len__(self):
        return len(self.changes)

    def __getitem__(self, index):
        return self.changes[index]

    @property
    def actions(self):
        return self.changes

    def append(self, change):
        if not isinstance(change, NormalizationChange):
            change = NormalizationChange(**change)
        self.changes.append(change)
        if change.get('new_path') is not None:
            self._renames[change['new_path']] = change['path']
        return change

    def record(self, op, path, schema_path, old=UNSET, new=UNSET, **kwargs):
        current_path = tuple(path)
        original_path = kwargs.pop('original_path', None)
        if original_path is None:
            original_path = self.original_path(current_path)
        change = NormalizationChange(
            op,
            current_path,
            schema_path,
            old=old,
            new=new,
            original_path=original_path,
            **kwargs
        )
        return self.append(change)

    def original_path(self, path):
        path = tuple(path)
        candidates = [
            destination
            for destination in self._renames
            if self._is_prefix(destination, path)
        ]
        if not candidates:
            return path
        destination = max(candidates, key=len)
        source = self._renames[destination]
        return source + path[len(destination) :]

    @staticmethod
    def _is_prefix(prefix, path):
        return path[: len(prefix)] == prefix

    def replay(self, document):
        result = deepcopy(document)
        for change_index, change in enumerate(self.changes):
            self._replay_change(result, change, change_index)
        return result

    def _replay_change(self, document, change, change_index):
        replay_path = tuple(change['path'])
        ancestors = self._ancestors(document, replay_path[:-1])
        parent = ancestors[-1] if ancestors else document
        key = replay_path[-1]
        if not isinstance(parent, Mapping) and isinstance(key, int):
            key = self._current_index(parent, key, replay_path, change_index)
        if change['op'] == 'purge':
            if isinstance(parent, Mapping):
                del parent[key]
            else:
                replacement = type(parent)(
                    value for index, value in enumerate(parent) if index != key
                )
                self._replace_at(document, replay_path[:-1], replacement)
            return

        if change['op'] == 'rename' or change.get('target') == 'key':
            value = parent[key]
            if not change.get('keep_source'):
                if isinstance(parent, Mapping):
                    del parent[key]
                else:
                    replacement = type(parent)(
                        value
                        for index, value in enumerate(parent)
                        if index != key
                    )
                    self._replace_at(document, replay_path[:-1], replacement)
                    ancestors = self._ancestors(document, replay_path[:-1])
                    parent = ancestors[-1] if ancestors else document
            value = parent[key] if change.get('keep_source') else value
            destination_ancestors = self._ancestors(
                document, change['new_path'][:-1]
            )
            destination_parent = (
                destination_ancestors[-1]
                if destination_ancestors
                else document
            )
            destination_parent[change['new_path'][-1]] = value
            return

        if isinstance(parent, Mapping):
            parent[key] = change['new']
        else:
            replacement = type(parent)(
                change['new'] if index == key else value
                for index, value in enumerate(parent)
            )
            self._replace_at(document, replay_path[:-1], replacement)

    def _ancestors(self, document, path):
        target = document
        ancestors = []
        for crumb in path:
            target = target[crumb]
            ancestors.append(target)
        return ancestors

    def _replace_at(self, document, path, replacement):
        if not path:
            raise TypeError('Cannot replace the document itself')
        parent = self._navigate_target(document, path[:-1])
        key = path[-1]
        if not isinstance(parent, Mapping):
            parent_replacement = type(parent)(
                replacement if index == key else value
                for index, value in enumerate(parent)
            )
            if path[:-1]:
                self._replace_at(document, path[:-1], parent_replacement)
            return
        parent[key] = replacement

    def _navigate_target(self, document, path):
        target = document
        for crumb in path:
            target = target[crumb]
        return target

    def _current_index(self, parent, original_index, original_path, change_index):
        deleted_before = 0
        parent_path = tuple(original_path[:-1])
        for change in self.changes[:change_index]:
            if change.op != 'purge':
                continue
            path = change.path
            if (
                tuple(path[:-1]) == parent_path
                and isinstance(path[-1], int)
                and path[-1] < original_index
            ):
                deleted_before += 1
        current_index = original_index - deleted_before
        return max(0, min(current_index, len(parent) - 1))
