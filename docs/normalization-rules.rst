Normalization Rules
===================

Normalization rules are applied to fields, also in ``schema`` for mappings, as
well when defined as a bulk operation by ``schema`` (for sequences),
``allow_unknown``, ``keysrules`` and ``valuesrules``.  Normalization rules
in definitions for testing variants like with ``anyof`` are not processed.

The normalizations are applied as given in this document for each level in the
mapping, traversing depth-first.

Renaming Of Fields
------------------
You can define a field to be renamed before any further processing.

.. doctest::

   >>> v = Validator({'foo': {'rename': 'bar'}})
   >>> v.normalized({'foo': 0})
   {'bar': 0}

To let a callable rename a field or arbitrary fields, you can define a handler
for renaming. If the constraint is a string, it points to a
:doc:`custom method <customize>`. If the constraint is an iterable, the value
is processed through that chain.

.. doctest::

   >>> v = Validator({}, allow_unknown={'rename_handler': int})
   >>> v.normalized({'0': 'foo'})
   {0: 'foo'}

.. doctest::

   >>> even_digits = lambda x: '0' + x if len(x) % 2 else x
   >>> v = Validator({}, allow_unknown={'rename_handler': [str, even_digits]})
   >>> v.normalized({1: 'foo'})
   {'01': 'foo'}


.. versionadded:: 1.0

.. _purging-unknown-fields:

Purging Unknown Fields
----------------------
After renaming, unknown fields will be purged if the
:attr:`~cerberus.Validator.purge_unknown` property of a
:class:`~cerberus.Validator` instance is ``True``; it defaults to ``False``.
You can set the property per keyword-argument upon initialization or as rule for
subdocuments like ``allow_unknown`` (see :ref:`allowing-the-unknown`). The default is
``False``.
If a subdocument includes an ``allow_unknown`` rule then unknown fields
will not be purged on that subdocument.

.. doctest::

   >>> v = Validator({'foo': {'type': 'string'}}, purge_unknown=True)
   >>> v.normalized({'bar': 'foo'})
   {}

.. versionadded:: 1.0

.. _default-values:

Default Values
--------------
You can set default values for missing fields in the document by using the ``default`` rule.

.. doctest::

   >>> v.schema = {'amount': {'type': 'integer'}, 'kind': {'type': 'string', 'default': 'purchase'}}
   >>> v.normalized({'amount': 1}) == {'amount': 1, 'kind': 'purchase'}
   True

   >>> v.normalized({'amount': 1, 'kind': None}) == {'amount': 1, 'kind': 'purchase'}
   True

   >>> v.normalized({'amount': 1, 'kind': 'other'}) == {'amount': 1, 'kind': 'other'}
   True

You can also define a default setter callable to set the default value
dynamically. The callable gets called with the current (sub)document as the
only argument. Callables can even depend on one another, but normalizing will
fail if there is a unresolvable/circular dependency. If the constraint is a
string, it points to a :doc:`custom method <customize>`.

.. doctest::

   >>> v.schema = {'a': {'type': 'integer'}, 'b': {'type': 'integer', 'default_setter': lambda doc: doc['a'] + 1}}
   >>> v.normalized({'a': 1}) == {'a': 1, 'b': 2}
   True

   >>> v.schema = {'a': {'type': 'integer', 'default_setter': lambda doc: doc['not_there']}}
   >>> v.normalized({})
   >>> v.errors
   {'a': ["default value for 'a' cannot be set: Circular dependencies of default setters."]}

You can even use both ``default`` and :ref:`readonly` on the same field. This
will create a field that cannot be assigned a value manually but it will be
automatically supplied with a default value by Cerberus. Of course the same
applies for ``default_setter``.

.. versionchanged:: 1.0.2
   Can be used in conjunction with :ref:`readonly`.

.. versionadded:: 1.0

.. _type-coercion:

Value Coercion
--------------
Coercion allows you to apply a callable (given as object or the name of a
:ref:`custom coercion method <custom-coercer>`) to a value before the document
is validated. The return value of the callable replaces the new value in the
document. This can be used to convert values or sanitize data before it is
validated.  If the constraint is an iterable of callables and names, the value
is processed through that chain of coercers.

.. doctest::

   >>> v.schema = {'amount': {'type': 'integer'}}
   >>> v.validate({'amount': '1'})
   False

   >>> v.schema = {'amount': {'type': 'integer', 'coerce': int}}
   >>> v.validate({'amount': '1'})
   True
   >>> v.document
   {'amount': 1}

   >>> to_bool = lambda v: v.lower() in ('true', '1')
   >>> v.schema = {'flag': {'type': 'boolean', 'coerce': (str, to_bool)}}
   >>> v.validate({'flag': 'true'})
   True
   >>> v.document
   {'flag': True}

.. versionadded:: 0.9

.. _normalization-report:

Reporting Normalization Changes
-------------------------------
To audit which changes normalization applied to a document, initialize a
validator with ``report_normalization=True``. The changes are then recorded
in execution order in
:attr:`~cerberus.Validator.normalization_report` as
:class:`~cerberus.normalization_report.NormalizationAction` instances that
each hold the kind of change (``rename``, ``purge_unknown``,
``purge_readonly``, ``default`` or ``coerce``), the affected field's path in
the document, the causing rule's path in the schema and the values before and
after the change. The ``origin_path`` of an action refers to the field's path
in the original document, regardless of preceding renames. A value that was
purged records the removed value, while a field that was not provided at all
is marked with the :data:`~cerberus.MISSING` sentinel. Changes that failed
(e.g. a coercion that raised an exception) are not recorded.

The report is self-contained and can be replayed on a copy of the original
document to reproduce the normalized result:

.. doctest::

   >>> schema = {'foo': {'rename': 'bar'}, 'bar': {'coerce': str},
   ...           'kind': {'default': 'purchase'}}
   >>> v = Validator(schema, report_normalization=True)
   >>> document = {'foo': 0}
   >>> v.normalized(document)
   {'bar': '0', 'kind': 'purchase'}
   >>> for action in v.normalization_report:
   ...     print(action.op, action.document_path)
   rename ('foo',)
   default ('kind',)
   coerce ('bar',)
   >>> v.normalization_report.replay(document)
   {'bar': '0', 'kind': 'purchase'}

.. versionadded:: 1.4
