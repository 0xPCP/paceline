from app.routes import main as main_routes


def test_health_endpoint_returns_minimal_status(client):
    response = client.get('/health')

    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok'}


def test_health_endpoint_does_not_expose_database_errors(client, monkeypatch):
    def fail_execute(*args, **kwargs):
        raise RuntimeError('postgresql://user:secret@example.com/paceline')

    monkeypatch.setattr(main_routes.db.session, 'execute', fail_execute)

    response = client.get('/health')

    assert response.status_code == 503
    assert response.get_json() == {'status': 'error'}
    assert b'secret' not in response.data
    assert b'postgresql://' not in response.data
