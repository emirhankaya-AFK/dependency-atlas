from io import BytesIO
import stat
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

import pytest

from dependency_atlas.scanner import ScanError, analyze_zip, sources_from_zip, MAX_ZIP_BYTES, MAX_SOURCE_BYTES


def zip_bytes(mapping):
    buff = BytesIO()
    with ZipFile(buff, 'w', compression=ZIP_DEFLATED) as archive:
        for k, v in mapping.items():
            archive.writestr(k, v)
    return buff.getvalue()


def test_normal_zip():
    data = zip_bytes({'pkg/__init__.py': '', 'pkg/a.py': 'from . import b', 'pkg/b.py': ''})
    report = analyze_zip(data)
    assert report['summary']['total_modules'] == 3


def test_repo_root_removed_when_single_root():
    data = zip_bytes({'my-repo/pkg/__init__.py': '', 'my-repo/pkg/a.py': 'from pkg import b', 'my-repo/pkg/b.py': ''})
    r = analyze_zip(data, 'my-repo.zip')
    assert ('pkg.a', 'pkg.b') in {(e['source'], e['target']) for e in r['edges']}


def test_broken_zip_rejected():
    with pytest.raises(ScanError, match='Invalid ZIP'):
        analyze_zip(b'unrelated bytes')


def test_upload_filename_must_be_zip():
    with pytest.raises(ScanError, match='zip'):
        analyze_zip(zip_bytes({'a.py': ''}), 'a.tar')


def test_zip_with_no_python():
    with pytest.raises(ScanError, match='no Python'):
        sources_from_zip(zip_bytes({'hello.txt': 'x'}))


def test_traversal_rejected():
    with pytest.raises(ScanError, match='Unsafe'):
        sources_from_zip(zip_bytes({'../steal.py': 'pass'}))


def test_windows_traversal_rejected():
    with pytest.raises(ScanError, match='Unsafe'):
        sources_from_zip(zip_bytes({r'x\..\steal.py': 'pass'}))


def test_nested_traversal_rejected():
    with pytest.raises(ScanError, match='Unsafe'):
        sources_from_zip(zip_bytes({'prefix/../../escape.txt': 'hello', 'a.py': ''}))


def test_unsafe_entries_checked_even_if_not_python():
    with pytest.raises(ScanError, match='Unsafe'):
        sources_from_zip(zip_bytes({'../../README.md': 'data', 'a.py': ''}))


def test_zip_symlink_rejected():
    buf = BytesIO()
    info = ZipInfo('link.py')
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(buf, 'w') as archive:
        archive.writestr(info, 'target.py')
    with pytest.raises(ScanError, match='symlink'):
        sources_from_zip(buf.getvalue())


def test_duplicate_zip_paths_rejected():
    buf = BytesIO()
    with ZipFile(buf, 'w') as archive:
        archive.writestr('same.py', '')
        archive.writestr('same.py', 'x=1')
    with pytest.raises(ScanError, match='Duplicate'):
        sources_from_zip(buf.getvalue())


def test_oversized_source_rejected():
    with pytest.raises(ScanError, match='size limit'):
        sources_from_zip(zip_bytes({'big.py': 'a' * (MAX_SOURCE_BYTES + 1)}))


def test_oversized_zip_rejected():
    with pytest.raises(ScanError, match='upload limit'):
        sources_from_zip(b'x' * (MAX_ZIP_BYTES + 1))


def test_invalid_utf8_reported():
    r = analyze_zip(zip_bytes({'bad.py': b'\xff\xfe'}))
    assert r['summary']['parse_errors'] == 1


def test_pep263_encoding():
    r = analyze_zip(zip_bytes({'latin.py': '# coding: latin-1\nname = "caf\xe9"\n'.encode('latin-1')}))
    assert r['summary']['parse_errors'] == 0


def test_namespace_package_without_init_keeps_prefix():
    r = analyze_zip(zip_bytes({'pkg/a.py': 'import pkg.b', 'pkg/b.py': ''}), 'project.zip')
    assert ('pkg.a', 'pkg.b') in {(e['source'], e['target']) for e in r['edges']}
