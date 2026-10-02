from fastapi.testclient import TestClient

from luxion import __version__


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "luxion-backend"
    assert body["database"] == "ok"
    assert body["version"] == __version__


def test_version_endpoint(client: TestClient) -> None:
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json()["version"] == __version__


def test_unknown_route_is_404(client: TestClient) -> None:
    assert client.get("/api/does-not-exist").status_code == 404
