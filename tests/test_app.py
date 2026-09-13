import os
import tempfile

import pytest

import app as cloud_app


@pytest.fixture()
def client(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setitem(cloud_app.app.config, "TESTING", True)
    monkeypatch.setitem(cloud_app.app.config, "DATABASE", db_path)
    cloud_app.init_db()
    with cloud_app.app.test_client() as test_client:
        yield test_client
    os.remove(db_path)


def test_index_is_available(client):
    response = client.get("/")
    assert response.status_code == 200
