"""The gateway policy decides the request the middleware ACTUALLY sends.

`policies/agent/mcp_tool.yaml` (`agent:mcp_tool`) was written against a request
no live caller sends: lowercase roles, `principal.attr.tenant_id`,
`tool_scopes`, `server`/`tool`. The ERP middleware's PEP sends kind `mcp_tool`,
upper-case gateway scopes, the token's `tenants`, the tool name as the resource
id and `module`. `policies/agent/gateway_dispatch.yaml` decides that shape.

The contract is ONE literal file, `integration/contracts/mcp_dispatch_request.json`,
copied byte for byte into erp_django_middleware's
`django_middleware/tests/unit/mcp_gateway/fixtures/`. The middleware asserts its
builder emits each example's `request`; this file asserts the Cerbos fixtures
are that request and that the policy suite decides each one as `expected`. A
change to either side's shape without the other fails CI on that side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from integration.horilla.cerbos_access import catalog  # noqa: E402

CONTRACT = ROOT / "integration" / "contracts" / "mcp_dispatch_request.json"
AGENT = ROOT / "policies" / "agent"
POLICY = AGENT / "gateway_dispatch.yaml"
SUITE = AGENT / "gateway_dispatch_test.yaml"


def _contract():
    return json.loads(CONTRACT.read_text())["examples"]


def _yaml(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _policy():
    (doc,) = _yaml(POLICY)
    return doc["resourcePolicy"]


def _policy_roles():
    return {r for rule in _policy()["rules"] for r in rule.get("roles", [])}


def test_contract_examples_exist_and_cover_allow_and_deny():
    examples = _contract()
    assert len(examples) >= 4
    effects = {e["expected"]["dispatch"] for e in examples}
    assert effects == {"EFFECT_ALLOW", "EFFECT_DENY"}


def test_policy_serves_the_kind_the_middleware_sends():
    kinds = {r["resource"]["kind"] for e in _contract() for r in e["request"]["resources"]}
    assert kinds == {_policy()["resource"]} == {"mcp_tool"}


def test_cerbos_fixtures_are_the_contract_requests():
    (principals,) = _yaml(AGENT / "testdata" / "principals.yaml")
    (resources,) = _yaml(AGENT / "testdata" / "resources.yaml")
    for e in _contract():
        name = e["name"]
        assert principals["principals"][name] == e["request"]["principal"], name
        (res,) = e["request"]["resources"]
        assert resources["resources"][name] == res["resource"], name


def test_policy_suite_decides_each_contract_example_as_expected():
    (suite,) = _yaml(SUITE)
    for e in _contract():
        name = e["name"]
        (res,) = e["request"]["resources"]
        cases = [
            exp["actions"]
            for t in suite["tests"]
            if t["input"]["principals"] == [name] and t["input"]["resources"] == [name]
            for exp in t["expected"]
            if exp["principal"] == name and exp["resource"] == name
        ]
        assert cases, f"no policy test decides contract example {name}"
        for actions in cases:
            assert {a: actions[a] for a in res["actions"]} == e["expected"], name


def test_gateway_roles_are_the_upper_case_scopes_of_catalog_roles():
    roles = _policy_roles()
    # Every catalog token role reaches the gateway as its upper-cased name
    # (erp_django_middleware foundation_auth/keycloak.py scopes_from_claims).
    for key in catalog.token_realm_roles():
        assert key.upper() in roles, key
    assert {"ADMIN", "STAFF"} <= roles
    # Lowercase role names never arrive from the middleware; one here would be
    # a rule that can never match.
    assert all(r == "*" or r == r.upper() for r in roles), roles


def test_staff_is_in_the_catalog_but_not_assignable_or_synced():
    assert "staff" in catalog.all_role_keys()
    assert "staff" in catalog.non_assignable_role_keys()
    assert "staff" not in catalog.token_realm_roles()
    assert catalog.valid_roles(["staff", "ops"]) == ["ops"]
