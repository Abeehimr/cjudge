from fastapi.testclient import TestClient

from cjudge.api import app


def test_health_and_private_docs() -> None:
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
