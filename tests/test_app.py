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


def test_database_totals_count_each_record_once(client):
    client.post("/api/register", json={"email": "counts@example.test", "password": "test-password"})
    database_id = client.post("/api/databases", json={"name": "Inventory"}).get_json()["id"]
    for name, values in [("Stock", ["A", "B"]), ("Sales", ["C"]), ("Returns", [])]:
        table = client.post("/api/tables", json={
            "database_id": database_id, "name": name, "columns": [{"name": "item"}],
        }).get_json()
        for value in values:
            client.post("/api/records", json={"table_id": table["id"], "data": {"item": value}})

    database, = client.get("/api/databases").get_json()
    assert (database["table_count"], database["record_count"]) == (3, 3)
