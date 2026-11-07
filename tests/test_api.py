from fastapi.testclient import TestClient
from dependency_atlas.api import app
from .test_zip import zip_bytes

client = TestClient(app)


def test_health():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['version'] == '1.0.0'


def test_home_renders_dashboard():
    response = client.get('/')
    assert response.status_code == 200
    assert 'DependencyAtlas' in response.text
    assert 'URL.createObjectURL' in response.text


def test_demo_has_cycle():
    r = client.get('/api/demo')
    assert r.status_code == 200
    assert r.json()['summary']['cycles_found'] == 1


def test_zip_upload_and_report():
    response = client.post('/api/analyze', files={'file': ('code.zip', zip_bytes({'foo.py':'import bar','bar.py':''}), 'application/zip')})
    assert response.status_code == 200
    r = response.json()
    assert r['summary']['total_edges'] == 1
    assert r['edges'] == [{'source':'foo', 'target':'bar'}]


def test_bad_file_type():
    response = client.post('/api/analyze', files={'file': ('code.csv', b'a,b', 'text/csv')})
    assert response.status_code == 400


def test_bad_zip():
    response = client.post('/api/analyze', files={'file': ('code.zip', b'INVALID', 'application/zip')})
    assert response.status_code == 400


def test_rejects_traversal():
    response = client.post('/api/analyze', files={'file': ('code.zip', zip_bytes({'../bad.py':'x=1'}), 'application/zip')})
    assert response.status_code == 400


def test_download_is_json_not_server_side_file():
    response = client.get('/api/demo')
    assert response.headers['content-type'].startswith('application/json')
    assert 'modules' in response.json()
