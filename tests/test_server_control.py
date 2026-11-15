import os

from fastapi.testclient import TestClient

from yourturn import __version__
from yourturn.app import create_app


def test_health_identifies_manual_server(tmp_path):
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"app": "your-turn", "version": __version__, "pid": os.getpid(), "instance": None}
    assert client.post("/api/shutdown").status_code == 404


def test_managed_shutdown_needs_private_token_and_loopback(tmp_path):
    stopped = []
    app = create_app(tmp_path, instance_id="owned-instance", shutdown_token="private-control-token",
                     request_shutdown=lambda: stopped.append(True))
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))
    health = client.get("/api/health")
    assert health.json()["instance"] == "owned-instance"
    assert "private-control-token" not in health.text
    assert client.post("/api/shutdown").status_code == 403
    assert client.post("/api/shutdown", headers={"X-Your-Turn-Token": "wrong"}).status_code == 403
    assert client.post("/api/shutdown", headers={b"X-Your-Turn-Token": b"\xff"}).status_code == 403
    remote = TestClient(app, base_url="http://127.0.0.1", client=("192.168.1.2", 12345))
    assert remote.post("/api/shutdown", headers={"X-Your-Turn-Token": "private-control-token"}).status_code == 403
    assert stopped == []
    assert client.post("/api/shutdown", headers={"X-Your-Turn-Token": "private-control-token"}).status_code == 204
    assert stopped == [True]
