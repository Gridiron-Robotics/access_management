"""Tests for the Contract-A PDP surface.

The path-to-10 said "tests are ok — raise coverage on the module's own logic".
The module's own logic is exactly this file's subject: the policies are tested
by Cerbos's own test runner, but the code that decides what to ASK the PDP, and
what to do when the PDP does not answer, had no tests at all.

The fail-closed cases matter most. An authorization surface that answers "allow"
because it could not reach the PDP is worse than one that is simply down — the
failure is silent and it errs permissive.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integration.mcp.pdp_contract import (  # noqa: E402
    CONTRACT_SERVER_NAME,
    ContractSurface,
    PdpError,
    build_catalog,
    explain,
)

PRINCIPAL = {"id": "amy", "roles": ["support_agent"], "attr": {"tenant_id": "tenant-a"}}
RESOURCE = {
    "kind": "commerce:refund",
    "id": "r-1",
    "attr": {"tenant_id": "tenant-a", "amount": 100, "approved_by_human": False},
}


def allower(*allowed: str):
    """A stand-in PDP that allows exactly the named actions."""

    def _check(principal, payload, request_id):
        actions = payload[0]["actions"]
        return {
            "results": [
                {"actions": {a: ("EFFECT_ALLOW" if a in allowed else "EFFECT_DENY") for a in actions}}
            ]
        }

    return _check


class TestCatalog:
    def test_advertises_the_three_tools(self):
        names = [t["name"] for t in build_catalog()["tools"]]
        assert names == ["check_access", "allowed_actions", "explain_denial"]

    def test_names_the_server_the_brain_federates_against(self):
        assert build_catalog()["server"] == CONTRACT_SERVER_NAME

    def test_every_tool_carries_a_real_input_schema(self):
        # A tool without a schema is one the agent has to guess at.
        for tool in build_catalog()["tools"]:
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert schema["properties"]
            assert schema["required"]

    def test_destructive_hint_is_stated_not_omitted(self):
        # "No annotation" and "annotated non-destructive" are different claims
        # to the approval gate. The PDP mutates nothing, and says so.
        for tool in build_catalog()["tools"]:
            assert tool["annotations"]["destructiveHint"] is False


class TestDecisions:
    def test_allows_what_the_pdp_allows(self):
        surface = ContractSurface(allower("issue"))
        result = surface.invoke(
            "check_access", {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE}
        )
        assert result == {"allowed": True}

    def test_denies_what_the_pdp_denies(self):
        surface = ContractSurface(allower())
        result = surface.invoke(
            "check_access", {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE}
        )
        assert result == {"allowed": False}

    def test_allowed_actions_returns_only_the_permitted_subset(self):
        surface = ContractSurface(allower("view", "propose"))
        result = surface.invoke(
            "allowed_actions",
            {
                "principal": PRINCIPAL,
                "actions": ["view", "propose", "issue", "reverse"],
                "resource": RESOURCE,
            },
        )
        assert result == {"allowed_actions": ["propose", "view"]}

    def test_allowed_actions_asks_in_one_round_trip(self):
        # Probing each action separately would multiply latency on the agent's
        # planning path, which is the reason this tool exists.
        calls = []

        def _check(principal, payload, request_id):
            calls.append(payload)
            return {"results": [{"actions": {a: "EFFECT_DENY" for a in payload[0]["actions"]}}]}

        ContractSurface(_check).invoke(
            "allowed_actions",
            {"principal": PRINCIPAL, "actions": ["a", "b", "c"], "resource": RESOURCE},
        )
        assert len(calls) == 1


class TestFailsClosed:
    def test_transport_failure_is_a_denial_not_an_allow(self):
        def _boom(*_args, **_kwargs):
            raise ConnectionError("PDP unreachable")

        with pytest.raises(PdpError, match="unavailable"):
            ContractSurface(_boom).invoke(
                "check_access", {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE}
            )

    def test_empty_response_is_a_denial(self):
        # A PDP that returns 200 with no results has not made a decision.
        with pytest.raises(PdpError, match="unavailable"):
            ContractSurface(lambda *a: {"results": []}).invoke(
                "check_access", {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE}
            )

    def test_malformed_response_is_a_denial(self):
        with pytest.raises(PdpError):
            ContractSurface(lambda *a: None).invoke(
                "check_access", {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE}
            )

    def test_an_unrecognised_effect_is_not_an_allow(self):
        # Only EFFECT_ALLOW means allow. Anything else — including a new effect
        # a future Cerbos adds — must not be read as permission.
        surface = ContractSurface(
            lambda *a: {"results": [{"actions": {"issue": "EFFECT_SOMETHING_NEW"}}]}
        )
        result = surface.invoke(
            "check_access", {"principal": PRINCIPAL, "action": "issue", "resource": RESOURCE}
        )
        assert result == {"allowed": False}

    def test_a_principal_with_no_tenant_is_refused_not_defaulted(self):
        # Defaulting a missing tenant is a cross-tenant hole dressed up as a
        # convenience. Every commerce and agent policy is tenant-scoped.
        with pytest.raises(PdpError, match="tenant_id is required"):
            ContractSurface(allower("issue")).invoke(
                "check_access",
                {
                    "principal": {"id": "x", "roles": ["admin"], "attr": {}},
                    "action": "issue",
                    "resource": RESOURCE,
                },
            )

    def test_an_empty_tenant_string_is_also_refused(self):
        with pytest.raises(PdpError, match="tenant_id is required"):
            ContractSurface(allower("issue")).invoke(
                "check_access",
                {
                    "principal": {"id": "x", "roles": ["admin"], "attr": {"tenant_id": ""}},
                    "action": "issue",
                    "resource": RESOURCE,
                },
            )

    def test_unknown_tool_is_refused(self):
        with pytest.raises(PdpError, match="unknown tool"):
            ContractSurface(allower()).invoke("drop_all_policies", {})

    def test_missing_action_is_refused(self):
        with pytest.raises(PdpError, match="'action' is required"):
            ContractSurface(allower()).invoke(
                "check_access", {"principal": PRINCIPAL, "resource": RESOURCE}
            )

    def test_empty_actions_list_is_refused(self):
        with pytest.raises(PdpError, match="non-empty"):
            ContractSurface(allower()).invoke(
                "allowed_actions",
                {"principal": PRINCIPAL, "actions": [], "resource": RESOURCE},
            )

    def test_resource_without_a_kind_is_refused(self):
        with pytest.raises(PdpError, match="resource.kind is required"):
            ContractSurface(allower()).invoke(
                "check_access",
                {
                    "principal": PRINCIPAL,
                    "action": "issue",
                    "resource": {"id": "r", "attr": {"tenant_id": "tenant-a"}},
                },
            )


class TestExplanations:
    """
    An agent that can say WHY it stopped is far more useful than one that says
    "denied" — but only if the reason is true. These pin the categories.
    """

    def test_cross_tenant_is_named_as_such(self):
        reason = explain(
            {"attr": {"tenant_id": "tenant-a"}},
            {"attr": {"tenant_id": "tenant-b"}},
            allowed=False,
        )
        assert "different tenant" in reason

    def test_a_missing_human_approval_says_what_would_unblock_it(self):
        reason = explain(
            {"attr": {"tenant_id": "t"}},
            {"attr": {"tenant_id": "t", "approved_by_human": False}},
            allowed=False,
        )
        assert "human approval" in reason
        assert "approval gate" in reason

    def test_a_bare_approval_flag_is_distinguished_from_no_approval(self):
        # Not the same message: the caller BELIEVES it has an approval, so
        # "route it through the approval gate" would send them to redo something
        # they think they already did. The real fault is upstream — the
        # enforcing service forwarded the flag without resolving the record.
        reason = explain(
            {"attr": {"tenant_id": "t"}},
            {"attr": {"tenant_id": "t", "approved_by_human": True, "approval_ref": ""}},
            allowed=False,
        )
        assert "approval_ref" in reason
        assert "bare flag" in reason

    def test_a_named_approval_is_not_blamed_for_the_denial(self):
        # With a real ref, the approval is not the problem — do not send the
        # caller to fix something that is already correct.
        reason = explain(
            {"attr": {"tenant_id": "t"}},
            {"attr": {"tenant_id": "t", "approved_by_human": True, "approval_ref": "appr-1"}},
            allowed=False,
        )
        assert "approval_ref" not in reason

    def test_an_over_band_amount_points_at_the_band(self):
        reason = explain(
            {"attr": {"tenant_id": "t"}},
            {"attr": {"tenant_id": "t", "amount": 99999}},
            allowed=False,
        )
        assert "authority band" in reason

    def test_a_plain_role_failure_says_so(self):
        reason = explain(
            {"attr": {"tenant_id": "t"}}, {"attr": {"tenant_id": "t"}}, allowed=False
        )
        assert "roles do not permit" in reason

    def test_an_allow_is_not_dressed_up_as_a_denial(self):
        assert explain({"attr": {}}, {"attr": {}}, allowed=True) == "allowed"

    def test_explain_denial_returns_both_the_decision_and_the_reason(self):
        surface = ContractSurface(allower())
        result = surface.invoke(
            "explain_denial",
            {
                "principal": PRINCIPAL,
                "action": "issue",
                "resource": {
                    "kind": "commerce:refund",
                    "id": "r",
                    "attr": {"tenant_id": "tenant-b"},
                },
            },
        )
        assert result["allowed"] is False
        assert "different tenant" in result["reason"]
