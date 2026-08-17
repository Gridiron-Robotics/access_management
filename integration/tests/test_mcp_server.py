"""HTTP-level tests for the Contract-A service.

Two things are load-bearing here and neither is visible from the policy files:
the service must refuse to start without a token, and a PDP it cannot reach must
produce an ERROR log — because that is what opens a self-heal incident. An
authorization service that cannot decide is an incident, not a routine 4xx.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integration.mcp.server import (  # noqa: E402
    SERVICE_NAME,
    build_default_app,
    create_app,
)

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

PRINCIPAL = {"id": "amy", "roles": ["support_agent"], "attr": {"tenant_id": "tenant-a"}}
RESOURCE = {
    "kind": "commerce:refund",
    "id": "r-1",
    "attr": {"tenant_id": "tenant-a", "amount": 100},
}


def allowing_checker(*allowed: str):
    def _check(principal, payload, request_id):
        actions = payload[0]["actions"]
        return {
            "results": [
                {"actions": {a: ("EFFECT_ALLOW" if a in allowed else "EFFECT_DENY") for a in actions}}
            ]
        }

    return _check


@pytest.fixture
def client():
    return TestClient(create_app(checker=allowing_checker("issue"), token=TOKEN))


class TestBootPosture:
    def test_refuses_to_start_without_a_token(self, monkeypatch):
        """
        This surface answers "who may do what" for the whole estate. Started
        unauthenticated it is both a map of the authorization model and a way to
        ask questions as somebody else, so there is no dev-convenience default.
        """
        monkeypatch.delenv("ACCESS_MCP_TOKEN", raising=False)

        with pytest.raises(RuntimeError, match="will not start unauthenticated"):
            create_app(checker=allowing_checker())

    def test_starts_when_a_token_is_configured(self, monkeypatch):
        monkeypatch.setenv("ACCESS_MCP_TOKEN", "configured")
        assert create_app(checker=allowing_checker()) is not None

    def test_the_container_entrypoint_also_refuses(self, monkeypatch):
        """
        The Dockerfile runs `uvicorn --factory ...:build_default_app`, so this
        function is the container's only boot guard. A previous shape exported
        `app = None` when the token was unset, which uvicorn reported as "not
        callable" — sending whoever is on call after an import bug instead of a
        missing secret.
        """
        monkeypatch.delenv("ACCESS_MCP_TOKEN", raising=False)

        with pytest.raises(RuntimeError, match="will not start unauthenticated"):
            build_default_app()

    def test_the_container_entrypoint_builds_when_configured(self, monkeypatch):
        monkeypatch.setenv("ACCESS_MCP_TOKEN", "configured")
        assert build_default_app() is not None


class TestAuthentication:
    def test_catalog_requires_a_token(self, client):
        # The catalog enumerates every resource kind and action in the estate's
        # authorization model. It is not public.
        assert client.get("/tools").status_code == 401

    def test_invoke_requires_a_token(self, client):
        response = client.post(
            "/invoke",
            json={"tool": "check_access", "arguments": {}},
        )
        assert response.status_code == 401

    def test_a_wrong_token_is_refused(self, client):
        response = client.get("/tools", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_a_bare_token_without_the_bearer_scheme_is_refused(self, client):
        assert client.get("/tools", headers={"Authorization": TOKEN}).status_code == 401

    def test_liveness_is_open_because_it_reveals_only_reachability(self, client):
        assert client.head("/").status_code == 200

    @pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
    def test_the_framework_docs_endpoints_are_not_served(self, client, path):
        """
        FastAPI mounts /docs, /redoc and /openapi.json unauthenticated by
        default. That contradicts the reason GET /tools is gated: the schema
        names the service and enumerates its routes to anyone who can reach the
        port, which is the first half of the map we refuse to hand out. HEAD /
        is the only open route on this surface — it reveals reachability and
        nothing else.
        """
        response = client.get(path)
        assert response.status_code == 404, (
            f"{path} is being served; an unauthenticated caller can read the schema of "
            "the estate's authorization surface"
        )


class TestContractShape:
    def test_tools_lists_the_catalog(self, client):
        body = client.get("/tools", headers=AUTH).json()
        assert body["server"] == "access_management"
        assert {t["name"] for t in body["tools"]} == {
            "check_access",
            "allowed_actions",
            "explain_denial",
        }

    def test_invoke_returns_the_decision(self, client):
        response = client.post(
            "/invoke",
            headers=AUTH,
            json={
                "server": "access_management",
                "tool": "check_access",
                "arguments": {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE},
            },
        )
        assert response.status_code == 200
        assert response.json()["result"] == {"allowed": True}

    def test_the_catalog_answers_a_server_scoped_discovery(self, client):
        # The estate contract is `GET /tools?server=<name>`.
        body = client.get("/tools?server=access_management", headers=AUTH).json()
        assert len(body["tools"]) == 3

    def test_the_catalog_is_empty_for_a_different_server(self, client):
        # Answering with our catalog regardless of what was asked for would make
        # a misrouted gateway look like it works, and the caller would bind
        # tools it believes belong to something else.
        body = client.get("/tools?server=inventree", headers=AUTH).json()
        assert body["tools"] == []

    def test_a_request_for_another_server_is_404(self, client):
        response = client.post(
            "/invoke",
            headers=AUTH,
            json={"server": "inventree", "tool": "check_access", "arguments": {}},
        )
        assert response.status_code == 404

    def test_an_unknown_tool_is_404(self, client):
        response = client.post(
            "/invoke",
            headers=AUTH,
            json={"tool": "delete_everything", "arguments": {}},
        )
        assert response.status_code == 404

    def test_a_malformed_argument_object_is_422(self, client):
        response = client.post(
            "/invoke",
            headers=AUTH,
            json={"tool": "check_access", "arguments": ["not", "an", "object"]},
        )
        assert response.status_code == 422

    def test_a_principal_with_no_tenant_is_422_not_a_decision(self, client):
        response = client.post(
            "/invoke",
            headers=AUTH,
            json={
                "tool": "check_access",
                "arguments": {
                    "principal": {"id": "x", "roles": ["admin"], "attr": {}},
                    "action": "issue",
                    "resource": RESOURCE,
                },
            },
        )
        assert response.status_code == 422
        assert "tenant_id" in response.json()["error"]


class TestTenantHeader:
    """
    The platform sets `X-Tenant-Id` on tenant-scoped invocations. The estate
    rule is that it may only RESTATE the principal's tenant — a header is
    spoofable, the principal is what the policies are written against.
    """

    def test_a_matching_header_is_accepted(self, client):
        response = client.post(
            "/invoke",
            headers={**AUTH, "X-Tenant-Id": "tenant-a"},
            json={
                "tool": "check_access",
                "arguments": {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE},
            },
        )
        assert response.status_code == 200
        assert response.json()["result"] == {"allowed": True}

    def test_a_mismatched_header_is_403_not_a_silent_preference(self, client):
        # If we quietly preferred either side, a caller who can set the header
        # could ask questions as another tenant, or a compromised principal
        # could hide behind a benign header.
        response = client.post(
            "/invoke",
            headers={**AUTH, "X-Tenant-Id": "tenant-b"},
            json={
                "tool": "check_access",
                "arguments": {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE},
            },
        )
        assert response.status_code == 403
        assert "allowed" not in response.json()

    def test_no_header_leaves_the_principal_authoritative(self, client):
        response = client.post(
            "/invoke",
            headers=AUTH,
            json={
                "tool": "check_access",
                "arguments": {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE},
            },
        )
        assert response.status_code == 200


class TestSelfHealRail:
    def test_an_unreachable_pdp_is_503_and_never_an_allow(self, caplog):
        """
        The important half is the status code: a PDP that cannot be reached must
        not resolve to a decision in either direction. 503 says "ask again";
        200 with allowed:false would be a lie, and 200 with allowed:true would
        be a breach.
        """

        def _boom(*_args, **_kwargs):
            raise ConnectionError("PDP unreachable")

        client = TestClient(create_app(checker=_boom, token=TOKEN))

        with caplog.at_level(logging.ERROR, logger=SERVICE_NAME):
            response = client.post(
                "/invoke",
                headers=AUTH,
                json={
                    "tool": "check_access",
                    "arguments": {
                        "principal": PRINCIPAL,
                        "action": "issue",
                        "resource": RESOURCE,
                    },
                },
            )

        assert response.status_code == 503
        assert "allowed" not in response.json()

    def test_an_unreachable_pdp_emits_an_ERROR_record(self, caplog):
        """
        The estate alert fires on `level = error` in this module's OpenObserve
        stream. If the failure is logged at WARNING, or not logged, the loop
        never runs and an authorization outage is invisible until someone
        notices requests failing.
        """

        def _boom(*_args, **_kwargs):
            raise ConnectionError("PDP unreachable")

        client = TestClient(create_app(checker=_boom, token=TOKEN))

        with caplog.at_level(logging.ERROR, logger=SERVICE_NAME):
            client.post(
                "/invoke",
                headers=AUTH,
                json={
                    "tool": "check_access",
                    "arguments": {
                        "principal": PRINCIPAL,
                        "action": "issue",
                        "resource": RESOURCE,
                    },
                },
            )

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "an unreachable PDP must raise an ERROR record"
        assert any("unavailable" in r.getMessage() for r in errors)

    def test_a_routine_denial_does_NOT_raise_an_incident(self, client, caplog):
        # Denials are the normal output of an authorization service. Logging
        # them at ERROR would bury the real incidents in noise.
        with caplog.at_level(logging.ERROR, logger=SERVICE_NAME):
            response = client.post(
                "/invoke",
                headers=AUTH,
                json={
                    "tool": "check_access",
                    "arguments": {
                        "principal": PRINCIPAL,
                        "action": "reverse",
                        "resource": RESOURCE,
                    },
                },
            )

        assert response.status_code == 200
        assert response.json()["result"] == {"allowed": False}
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
