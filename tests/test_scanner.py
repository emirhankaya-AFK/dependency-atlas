import pytest
from dependency_atlas.scanner import ScanError, analyze_sources, valid_path, _relative_base


def report(files):
    return analyze_sources(files, "suite")


def links(r):
    return {(x['source'], x['target']) for x in r['edges']}


def test_absolute_import():
    r = report({'pkg/__init__.py': '', 'pkg/a.py': 'import pkg.b\n', 'pkg/b.py': 'x=1'})
    assert ('pkg.a', 'pkg.b') in links(r)
    assert r['summary']['total_modules'] == 3


def test_from_import_module():
    r = report({'pkg/__init__.py': '', 'pkg/a.py': 'from pkg import b', 'pkg/b.py': 'x=1'})
    assert ('pkg.a', 'pkg.b') in links(r)


def test_from_import_attribute_falls_back_to_module():
    r = report({'pkg/__init__.py': '', 'pkg/a.py': 'from pkg.b import function', 'pkg/b.py': 'def function(): pass'})
    assert ('pkg.a', 'pkg.b') in links(r)


def test_relative_sibling_import():
    r = report({'pkg/__init__.py': '', 'pkg/a.py': 'from .b import work', 'pkg/b.py': 'def work(): pass'})
    assert ('pkg.a', 'pkg.b') in links(r)


def test_relative_parent_import():
    r = report({'pkg/__init__.py': '', 'pkg/x.py': '', 'pkg/sub/__init__.py': '', 'pkg/sub/a.py': 'from .. import x'})
    assert ('pkg.sub.a', 'pkg.x') in links(r)


def test_relative_package_init():
    r = report({'pkg/__init__.py': 'from . import util', 'pkg/util.py': 'x=1'})
    assert ('pkg', 'pkg.util') in links(r)


def test_relative_import_exceeds_root_error():
    r = report({'pkg/a.py': 'from ...other import value'})
    assert r['summary']['parse_errors'] == 1
    assert 'Relative import' in r['errors'][0]['reason']


def test_external_and_stdlib_grouped():
    r = report({'a.py': 'import os\nimport json.decoder\nfrom fastapi import FastAPI'})
    assert r['externals'] == ['fastapi', 'json', 'os']
    assert r['summary']['total_edges'] == 0


def test_cycle_two_modules():
    r = report({'a.py': 'import b', 'b.py': 'import a'})
    assert r['cycles'] == [['a', 'b']]
    assert all(n['in_cycle'] for n in r['modules'])


def test_self_loop():
    r = report({'a.py': 'import a'})
    assert r['cycles'] == [['a']]


def test_chain_is_not_cycle():
    r = report({'a.py': 'import b', 'b.py': 'import c', 'c.py': ''})
    assert r['cycles'] == []
    assert r['summary']['health_score'] == 100


def test_multiple_cycles_are_grouped_as_scc():
    r = report({'a.py': 'import b', 'b.py': 'import a', 'c.py': 'import d', 'd.py': 'import c'})
    assert r['cycles'] == [['a', 'b'], ['c', 'd']]


def test_deduplicate_edges():
    r = report({'a.py': 'import b\nfrom b import item\nimport b', 'b.py': 'item=2'})
    assert r['summary']['total_edges'] == 1


def test_stats_and_heuristic_score():
    r = report({'a.py': 'import b\ndef f(x):\n if x: return 1\n return 2', 'b.py': ''})
    by_name = {m['module']: m for m in r['modules']}
    assert by_name['a']['fan_out'] == 1
    assert by_name['b']['fan_in'] == 1
    assert by_name['a']['functions'] == 1
    assert by_name['a']['complexity'] == 2


def test_src_layout():
    r = report({'src/pkg/__init__.py': '', 'src/pkg/a.py': 'from pkg import b', 'src/pkg/b.py': '', 'tests/test_a.py': ''})
    assert ('pkg.a', 'pkg.b') in links(r)
    assert 'tests.test_a' in [m['module'] for m in r['modules']]


def test_syntax_error_reported_not_executed():
    r = report({'good.py': 'import bad', 'bad.py': 'def foo('})
    assert r['summary']['parse_errors'] == 1
    assert ('good', 'bad') in links(r)


def test_untrusted_code_is_never_executed(tmp_path):
    marker = tmp_path / 'hacked.txt'
    r = report({'evil.py': f'open({str(marker)!r}, "w").write("HACKED")'})
    assert r['summary']['total_modules'] == 1
    assert not marker.exists()


def test_no_sources_rejected():
    with pytest.raises(ScanError):
        report({})


@pytest.mark.parametrize('bad', ['/abs.py', '../escape.py', 'src/../escape.py', r'C:\foo.py', 'x.txt', 'src//../evil.py', 'bad\0.py'])
def test_bad_paths_rejected(bad):
    with pytest.raises(ScanError):
        valid_path(bad)


def test_ignored_folders():
    r = report({'pkg/a.py': '', '.venv/lib/b.py': 'import pkg.a'})
    assert r['summary']['total_modules'] == 1


def test_name_stable_order():
    a = report({'b.py': 'import a', 'a.py': ''})
    b = report({'a.py': '', 'b.py': 'import a'})
    assert a == b


def test_zero_length_file_is_valid():
    assert report({'empty.py': ''})['summary']['total_modules'] == 1


def test_invalid_syntax_nul_diagnostic():
    r = report({'bad.py': '\0'})
    assert r['summary']['parse_errors'] == 1
