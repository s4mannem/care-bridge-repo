from fastapi.testclient import TestClient

from carebridge.config import Settings
from carebridge.main import create_app


def test_healthz(client: TestClient):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.headers["x-request-id"]


def test_request_id_is_echoed(client: TestClient):
    res = client.get("/healthz", headers={"X-Request-Id": "abc123"})
    assert res.headers["x-request-id"] == "abc123"


def test_readyz_reports_config(client: TestClient):
    body = client.get("/readyz").json()
    assert body["status"] == "ready"
    assert body["checks"] == {"bigquery_configured": True, "agent_engine": "stub"}


def test_readyz_not_ready_without_bigquery():
    app = create_app(Settings(_env_file=None, env="test", bq_project=None))
    res = TestClient(app).get("/readyz")
    assert res.status_code == 503


def test_plan_unknown_county_uses_error_shape(client: TestClient):
    res = client.post("/v1/plan", json={"county_fips": "06085"}, headers={"X-Request-Id": "r1"})
    assert res.status_code == 404
    assert res.json()["error"] == {"code": "county_not_available", "message": res.json()["error"]["message"],
                                   "request_id": "r1"}


def test_tracts_validates_fips(client: TestClient):
    assert client.get("/v1/tracts/06085").status_code == 404
    assert client.get("/v1/tracts/abc").json()["error"]["code"] == "invalid_request"


def test_cors_allows_flutter_dev_origin(client: TestClient):
    res = client.options("/v1/plan", headers={"Origin": "http://localhost:53211",
                                              "Access-Control-Request-Method": "POST"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:53211"
