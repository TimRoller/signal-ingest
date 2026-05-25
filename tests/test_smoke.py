from fastapi.testclient import TestClient

from services.ingest_api.main import app as ingest_app
from services.mcp_server.main import app as mcp_app


def test_ingest_api_health() -> None:
    client = TestClient(ingest_app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_mcp_server_health() -> None:
    client = TestClient(mcp_app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
