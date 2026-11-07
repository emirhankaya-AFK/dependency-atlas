import json
from pathlib import Path

from dependency_atlas.cli import main


def test_analyze_json_stdout(tmp_path, capsys):
    (tmp_path/'a.py').write_text('')
    assert main(['analyze', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['summary']['total_modules'] == 1


def test_check_cycles_return_code(tmp_path):
    (tmp_path/'a.py').write_text('import b')
    (tmp_path/'b.py').write_text('import a')
    assert main(['check', str(tmp_path)]) == 2
    assert main(['analyze', str(tmp_path), '--fail-on-cycles']) == 2


def test_check_parse_errors(tmp_path):
    (tmp_path/'a.py').write_text('def f(')
    assert main(['check', str(tmp_path)]) == 2


def test_json_export_without_overwriting(tmp_path):
    src = tmp_path / 'project'
    src.mkdir()
    (src/'a.py').write_text('x=1')
    destination = tmp_path/'report.json'
    assert main(['analyze', str(src), '-o', str(destination)]) == 0
    before = destination.read_text()
    assert main(['analyze', str(src), '-o', str(destination)]) == 1
    assert destination.read_text() == before


def test_missing_directory_error(capsys):
    assert main(['check', '/nonexistent-dependencyatlas-directory']) == 1
    assert 'error:' in capsys.readouterr().err


def test_symlinks_skipped(tmp_path):
    inner = tmp_path / 'inside.py'
    inner.write_text('')
    link = tmp_path / 'link.py'
    link.symlink_to(inner)
    assert main(['check', str(tmp_path)]) == 0
