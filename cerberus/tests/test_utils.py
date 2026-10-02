from cerberus.utils import compare_paths_lt, mapping_hash


def test_compare_paths():
    lesser = ('a_dict', 'keysrules')
    greater = ('a_dict', 'valuesrules')
    assert compare_paths_lt(lesser, greater)

    lesser += ('type',)
    greater += ('regex',)
    assert compare_paths_lt(lesser, greater)


def test_mapping_hash_with_nested_sequences():
    mapping_hash(
        {
            'dependencies': {
                'all': [['field']],
            }
        }
    )
