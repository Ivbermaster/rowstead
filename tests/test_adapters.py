import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters import ADAPTERS, AdapterError
from app.adapters.base import check_response, retry_after_seconds
from demo.main import app


@pytest.mark.parametrize("value", ["https://evil.example", "../secret", "", "a?url=b", "x" * 65])
def test_invalid_identifiers_cannot_control_url(value):
    with pytest.raises(AdapterError) as error:
        ADAPTERS["registry_demo"].validate_row({"identifier": value})
    assert error.value.kind == "invalid"


def test_browser_rejects_nonfinite_and_out_of_range_parameters():
    for key, value in (
        ("quantity", "NaN"),
        ("discount", "101"),
        ("unit_price", "Infinity"),
        ("quantity", "0"),
    ):
        with pytest.raises(AdapterError):
            ADAPTERS["browser_demo"].validate_row({"identifier": "BF-1", key: value})


@pytest.mark.parametrize(
    "status,kind",
    [
        (404, "missing"),
        (429, "transient"),
        (500, "transient"),
        (401, "login_required"),
        (403, "blocked"),
        (302, "blocked"),
        (400, "permanent"),
    ],
)
def test_http_failure_classification(status, kind):
    with pytest.raises(AdapterError) as error:
        check_response(status, "2")
    assert error.value.kind == kind


def test_retry_after_clamps_and_handles_invalid_input():
    assert retry_after_seconds("-2") == 0
    assert retry_after_seconds("999999") == 3600
    assert retry_after_seconds("no date") is None


def test_demo_registry_is_deterministic_and_retry_cases_are_stateless():
    with TestClient(app) as client:
        first = client.get("/api/registry/BF-0001")
        assert first.status_code == 200
        assert first.json() == client.get("/api/registry/BF-0001").json()
        assert len(first.json()) == 7
        assert client.get("/api/registry/RATE-ONCE").status_code == 429
        assert (
            client.get("/api/registry/RATE-ONCE", headers={"X-Batchflow-Attempt": "2"}).status_code
            == 200
        )
        assert client.get("/api/registry/ERROR-ONCE").status_code == 500
        assert client.get("/api/registry/MISSING").status_code == 404
        assert client.get("/calculator?identifier=LOGIN").status_code == 401


def test_registry_adapter_real_http_contract(monkeypatch):
    original_client = httpx.Client
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "identifier": "BF-1",
                "company_name": "Example",
                "country": "Poland",
                "industry": "Software",
                "employees": 5,
                "active": True,
                "risk_score": 2,
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = ADAPTERS["registry_demo"].execute({"identifier": "BF-1"}, {"_attempt": 2})
    assert result["employees"] == 5
    assert seen[0].headers["X-Batchflow-Attempt"] == "2"
    assert seen[0].url.path == "/api/registry/BF-1"


def test_user_config_cannot_override_source():
    with pytest.raises(AdapterError) as error:
        ADAPTERS["registry_demo"].validate_config({"base_url": "http://169.254.169.254"})
    assert error.value.code == "custom_source_disabled"
