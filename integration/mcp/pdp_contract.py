"""Contract-A MCP surface for the policy decision point.

WHY THIS EXISTS
---------------
The agent brain federates tools over `GET /tools` + `POST /invoke`. Before this,
the only way to reach these policies was the raw Cerbos `CheckResources` HTTP
API, so the brain could not *ask* whether an action was permitted — it could
only try it and see what the enforcing service did. That is a meaningful
difference: an agent that can check first can pick a different plan, propose a
human approval, or explain why it stopped, instead of firing an action and
handling a rejection.

Three tools, all read-only:

  check_access        may this principal do this action on this resource?
  allowed_actions     which of these actions may they do?  (one round trip)
  explain_denial      the same question, but returns WHY — which is what makes
                      an agent's "I can't do that because…" accurate rather
                      than invented.

Nothing here mutates. The PDP is a decision point; it does not enforce, and it
holds no state to change. So `destructiveHint` is false on every tool — and it
is stated explicitly rather than omitted, because "no annotation" and "annotated
non-destructive" are different claims to the approval gate.

FAIL-CLOSED
-----------
A transport error, a timeout, an unparseable response, or a principal with no
tenant all resolve to DENY. An authorization surface that answers "allow" when
it cannot reach the PDP is worse than one that is down: the failure is invisible
and it is in the permissive direction.
"""

from __future__ import annotations

import os
from typing import Any, Callable

CONTRACT_SERVER_NAME = "access_management"

# Every principal must carry these. They are not optional and they are not
# defaulted: the commerce and agent policies are all tenant-scoped, so a
# principal with no tenant is a principal with no legitimate access.
REQUIRED_PRINCIPAL_ATTRS = ("tenant_id",)


class PdpError(Exception):
    """The decision could not be obtained. Callers must treat this as DENY."""


def _tool(name: str, description: str, schema: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": schema,
        # Read-only. Stated, not omitted — see the module docstring.
        "annotations": {"destructiveHint": False},
    }


_PRINCIPAL_SCHEMA = {
    "type": "object",
    "description": "Who is asking. Roles come from the HRMS role catalog.",
    "properties": {
        "id": {"type": "string"},
        "roles": {"type": "array", "items": {"type": "string"}},
        "attr": {
            "type": "object",
            "description": (
                "Must include tenant_id. Include channels / distributors / "
                "tool_scopes where the relevant role needs them."
            ),
        },
    },
    "required": ["id", "roles", "attr"],
}

_RESOURCE_SCHEMA = {
    "type": "object",
    "description": "What is being acted on, e.g. kind 'commerce:refund'.",
    "properties": {
        "kind": {"type": "string"},
        "id": {"type": "string"},
        "attr": {
            "type": "object",
            "description": (
                "Must include tenant_id, plus whatever the policy's conditions "
                "read — amount, method, channel, distributor, approved_by_human."
            ),
        },
    },
    "required": ["kind", "id", "attr"],
}


TOOLS: list[dict] = [
    _tool(
        "check_access",
        "Decide whether a principal may perform ONE action on ONE resource. "
        "Returns {allowed: bool}. Denies on any error — never assume allow.",
        {
            "type": "object",
            "properties": {
                "principal": _PRINCIPAL_SCHEMA,
                "action": {"type": "string", "description": "e.g. 'issue', 'dispatch'"},
                "resource": _RESOURCE_SCHEMA,
            },
            "required": ["principal", "action", "resource"],
        },
    ),
    _tool(
        "allowed_actions",
        "Given several candidate actions, return the subset the principal may "
        "perform on the resource. Use this to plan, rather than probing each "
        "action in turn.",
        {
            "type": "object",
            "properties": {
                "principal": _PRINCIPAL_SCHEMA,
                "actions": {"type": "array", "items": {"type": "string"}},
                "resource": _RESOURCE_SCHEMA,
            },
            "required": ["principal", "actions", "resource"],
        },
    ),
    _tool(
        "explain_denial",
        "Why was this denied? Returns the decision plus the reason category — "
        "wrong tenant, missing role, an amount over the band, or a required "
        "human approval that has not been recorded. Use it to tell a person "
        "what would unblock them instead of guessing.",
        {
            "type": "object",
            "properties": {
                "principal": _PRINCIPAL_SCHEMA,
                "action": {"type": "string"},
                "resource": _RESOURCE_SCHEMA,
            },
            "required": ["principal", "action", "resource"],
        },
    ),
]


def build_catalog() -> dict:
    """The `GET /tools` payload."""
    return {"server": CONTRACT_SERVER_NAME, "tools": TOOLS}


def _validate_principal(principal: Any) -> dict:
    if not isinstance(principal, dict):
        raise PdpError("principal must be an object")

    attrs = principal.get("attr") or {}
    for required in REQUIRED_PRINCIPAL_ATTRS:
        if not attrs.get(required):
            # Not "assume a default tenant" — that would be a cross-tenant hole
            # dressed up as a convenience.
            raise PdpError(f"principal.attr.{required} is required")

    return principal


def _validate_resource(resource: Any) -> dict:
    if not isinstance(resource, dict):
        raise PdpError("resource must be an object")
    if not resource.get("kind"):
        raise PdpError("resource.kind is required")
    return resource


def explain(principal: dict, resource: dict, allowed: bool) -> str:
    """
    Categorise a decision so an agent can say something true about it.

    Deliberately coarse. The PDP knows which rule matched but exposing that
    would leak the policy's internal structure to any caller; these categories
    are what a person actually needs in order to act.
    """
    if allowed:
        return "allowed"

    p_attr = principal.get("attr") or {}
    r_attr = resource.get("attr") or {}

    if p_attr.get("tenant_id") != r_attr.get("tenant_id"):
        return "denied: resource belongs to a different tenant"

    if r_attr.get("approved_by_human") is False or r_attr.get("approved") is False:
        return (
            "denied: this action requires a recorded human approval "
            "(route it through the approval gate, then retry)"
        )

    if "amount" in r_attr or "order_total" in r_attr or "cost" in r_attr:
        return (
            "denied: the value exceeds this principal's authority band "
            "(a higher role, or a human approval, is required)"
        )

    return "denied: this principal's roles do not permit this action"


class ContractSurface:
    """
    Dispatches the three tools against a Cerbos client.

    The client is injected rather than constructed so the decision logic here
    can be tested without a running PDP — the fail-closed behaviour is the part
    that matters most and it is the hardest to exercise against a live service.
    """

    def __init__(self, checker: Callable[[dict, list[dict], str], dict]):
        self._check = checker

    def _decide(self, principal: dict, actions: list[str], resource: dict) -> dict[str, bool]:
        payload = [{"actions": list(actions), "resource": resource}]

        try:
            data = self._check(principal, payload, "mcp")
        except Exception as exc:  # noqa: BLE001 - every failure is a denial
            raise PdpError(f"policy decision unavailable: {exc}") from exc

        results = (data or {}).get("results") or []
        if not results:
            raise PdpError("policy decision unavailable: empty response")

        decisions = results[0].get("actions") or {}
        return {action: decisions.get(action) == "EFFECT_ALLOW" for action in actions}

    def invoke(self, tool: str, arguments: dict) -> dict:
        if tool not in {t["name"] for t in TOOLS}:
            raise PdpError(f"unknown tool: {tool}")

        principal = _validate_principal(arguments.get("principal"))
        resource = _validate_resource(arguments.get("resource"))

        if tool == "allowed_actions":
            actions = arguments.get("actions")
            if not isinstance(actions, list) or not actions:
                raise PdpError("'actions' must be a non-empty array")
            decided = self._decide(principal, actions, resource)
            return {"allowed_actions": sorted(a for a, ok in decided.items() if ok)}

        action = arguments.get("action")
        if not isinstance(action, str) or not action:
            raise PdpError("'action' is required")

        allowed = self._decide(principal, [action], resource)[action]

        if tool == "check_access":
            return {"allowed": allowed}

        return {"allowed": allowed, "reason": explain(principal, resource, allowed)}
