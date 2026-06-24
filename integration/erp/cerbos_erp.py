"""Drop-in Cerbos client for the ERP backend — the service that ENFORCES access.

Headline:  can(principal, action, resource) -> bool

No SDK dependency (talks to the PDP's HTTP API); swap in an official SDK later if
you prefer. Framework-agnostic — works in Django, FastAPI, Flask, or plain Python.

Config:  CERBOS_PDP_URL env var (default http://localhost:3592).
Install:  pip install requests
"""
from __future__ import annotations

import os

import requests

DEFAULT_URL = os.environ.get("CERBOS_PDP_URL", "http://localhost:3592")


class CerbosERP:
    """Thin wrapper over the Cerbos CheckResources API."""

    def __init__(self, pdp_url: str | None = None, timeout: float = 5.0):
        self.base = (pdp_url or DEFAULT_URL).rstrip("/")
        self.timeout = timeout

    def check(self, principal: dict, resources: list[dict], request_id: str = "erp") -> dict:
        """Raw CheckResources. `resources` items: {"actions": [...],
        "resource": {"kind","id","attr"}}. Raises on transport/HTTP error so the
        caller can fail closed (deny on error)."""
        payload = {"requestId": request_id, "principal": principal, "resources": resources}
        resp = requests.post(f"{self.base}/api/check/resources", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def can(self, principal: dict, action: str, resource: dict, request_id: str = "erp") -> bool:
        """Can this principal perform `action` on `resource`?
        principal = {"id","roles","attr"};  resource = {"kind","id","attr"}.
        Returns True only on EFFECT_ALLOW."""
        data = self.check(principal, [{"actions": [action], "resource": resource}], request_id)
        results = data.get("results", [])
        return bool(results) and results[0].get("actions", {}).get(action) == "EFFECT_ALLOW"

    def allowed_actions(self, principal: dict, resource: dict, actions: list[str]) -> set[str]:
        """The subset of `actions` the principal may perform on `resource`
        (handy for hiding buttons the user can't use)."""
        data = self.check(principal, [{"actions": actions, "resource": resource}])
        results = data.get("results", [])
        if not results:
            return set()
        return {a for a, eff in results[0].get("actions", {}).items() if eff == "EFFECT_ALLOW"}


# --- ergonomic builders (match policies/ROLES.md) ---------------------------

def principal(id: str, roles: list[str], **attr) -> dict:
    """principal("jane", ["finance_manager", "employee"], department="finance")"""
    return {"id": str(id), "roles": list(roles), "attr": attr}


def resource(kind: str, id: str, **attr) -> dict:
    """resource("finance:invoice", "inv-77", owner="amy", amount=5000)"""
    return {"kind": kind, "id": str(id), "attr": attr}


# --- module-level convenience using the default PDP URL ---------------------

_default: CerbosERP | None = None


def _client() -> CerbosERP:
    global _default
    if _default is None:
        _default = CerbosERP()
    return _default


def can(principal: dict, action: str, resource: dict) -> bool:
    """Shortcut: can(principal(...), "approve", resource(...))."""
    return _client().can(principal, action, resource)


if __name__ == "__main__":  # tiny smoke test against a running PDP
    p = principal("jane", ["finance_manager", "employee"], department="finance")
    r = resource("finance:invoice", "inv-77", owner="amy", amount=5000, department="finance")
    print("approve ->", can(p, "approve", r))
