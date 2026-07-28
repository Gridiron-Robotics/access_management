# `access_management` — the estate contract

What this module promises the rest of the estate, and what it expects back.
Treat it as the API: additive changes bump the minor, breaking changes bump the
major and need coordinated PRs in every consumer.

**Version:** 1.0.0

---

## What this module is

The **policy decision point (PDP)**. It answers *"may this principal do this
action on this resource?"* It does **not** enforce — enforcement happens in the
service that owns the operation. It holds no domain state and mutates nothing.

Two surfaces, two audiences:

| Surface | Port | Audience | Shape |
|---|---|---|---|
| Cerbos PDP | `3592` HTTP / `3593` gRPC | **Enforcing services** — the module about to perform the action | Upstream Cerbos `CheckResources` |
| Contract-A MCP | `8085` | **Agent brain / supervisor** — deciding what to attempt | `GET /tools` + `POST /invoke` |

The split matters. An enforcing service must ask on the write path, every time,
and it wants the raw low-latency API. An agent wants to ask *before* it plans,
so that it can choose a different route or request an approval instead of firing
an action and interpreting a rejection.

---

## Surface 1 — the PDP (enforcing services)

Unchanged upstream Cerbos. Clients:

- Python: `integration/erp/cerbos_erp.py` — `can(principal, action, resource)`
- Django/HRMS: `integration/horilla/cerbos_access/`
- Any language: `POST /api/check/resources`

```python
from integration.erp.cerbos_erp import can, principal, resource

can(
    principal("jane", ["finance_manager"], tenant_id="t-1"),
    "issue",
    resource("commerce:refund", "r-77", tenant_id="t-1", amount=5000),
)
```

**Health:** `GET /_cerbos/health`.

### The rule every caller must follow

**A transport error is a DENY.** `CerbosERP.check` raises rather than returning a
default so the caller cannot accidentally treat "I could not ask" as "yes".
A PDP that is unreachable must never widen access — the failure would be silent
and it would be in the permissive direction.

---

## Surface 2 — Contract-A MCP (the agent brain)

Conforms to the estate gateway contract v1 (`langgraph-agents/INTEGRATIONS.md`).

### `GET /tools?server=access_management`

`200 {"server": "access_management", "tools": [...]}`. A `?server=` naming
anything else returns `{"tools": []}` rather than our catalog — otherwise a
misrouted gateway looks like it works and the caller binds tools it believes
belong to something else.

Requires the bearer: the catalog enumerates every resource kind and action in
the estate's authorization model, so it is not public.

| Tool | `destructiveHint` | Returns |
|---|---|---|
| `check_access` | `false` | `{allowed}` — one action, one resource |
| `allowed_actions` | `false` | `{allowed_actions[]}` — the permitted subset, one round trip |
| `explain_denial` | `false` | `{allowed, reason}` — *why*, so the agent's "I can't because…" is true |

`destructiveHint` is **stated** rather than omitted. "No annotation" and
"annotated non-destructive" are different claims to the approval gate.

### `POST /invoke`

```json
{
  "server": "access_management",
  "tool": "check_access",
  "arguments": {
    "principal": {"id": "amy", "roles": ["support_agent"], "attr": {"tenant_id": "t-1"}},
    "action": "issue",
    "resource": {"kind": "commerce:refund", "id": "r-1",
                 "attr": {"tenant_id": "t-1", "amount": 100}}
  }
}
```

`200 {"tool": "...", "result": {...}}`

### `HEAD /` — liveness

`200`, unauthenticated. It reveals only reachability.

### Status codes

| Code | Meaning |
|---|---|
| `200` | A decision was made (allowed **or** denied — both are normal output) |
| `400` | Malformed JSON, or `tool` absent |
| `401` | Missing / wrong bearer |
| `403` | `X-Tenant-Id` disagrees with `principal.attr.tenant_id` |
| `404` | Unknown tool, or a `server` we do not serve |
| `422` | Bad arguments — no `principal.attr.tenant_id`, no `action`, no `resource.kind` |
| `503` | **The PDP could not be reached.** Not a decision in either direction |

`503` is the load-bearing one. `200 {allowed:false}` on an outage would be a
lie; `200 {allowed:true}` would be a breach. The caller must retry or stop.

---

## Security posture

- **Fail-closed boot.** `ACCESS_MCP_TOKEN` unset → the service **refuses to
  start**. There is no dev-convenience default: this surface is both a map of
  the authorization model and a way to ask questions as somebody else.
- **Constant-time bearer comparison** (`hmac.compare_digest`).
- **Tenant comes from the principal.** `X-Tenant-Id` may only *restate* it;
  a mismatch is `403`, never a silent preference for either side.
- **A missing tenant is refused, not defaulted.** Every commerce and agent
  policy is tenant-scoped, so a principal with no tenant has no legitimate
  access. Defaulting one would be a cross-tenant hole dressed as a convenience.
- **Only `EFFECT_ALLOW` means allow** — including effects a future Cerbos adds.

---

## Consuming this module

### From the agent platform

Registered as a **cross-cutting** server in
`langgraph-agents/specialists/registry.py::CROSS_CUTTING_SERVERS`, so every
specialist can check authorization before acting rather than only the one that
happens to own the resource.

```
GATEWAY_TOKENS={"http://access-management-mcp:8085":"<ACCESS_MCP_TOKEN>"}
```

Discovery is best-effort on the consumer side: if this gateway is unreachable at
factory time the specialist still boots with its own tools. That degradation is
about *tool discovery*, not about decisions — an enforcing service still asks
the PDP directly on its write path and still denies on error.

### From an enforcing module

Use the PDP surface, not this one. See `integration/erp/README.md`.

---

## What this module expects back

**`approved_by_human` must be true only when a human actually approved.**
Several policies (refunds ≥ 10,000, all outbound payments, tax filing, destructive
agent dispatch) treat the role as necessary-but-not-sufficient and additionally
require that flag. This module cannot verify the claim — it reads the attribute
it is handed. The approval record lives in `erp_django_middleware`'s `approvals`
app; see `integration/HITL_APPROVALS.md` for the contract that keeps the flag
honest.

---

## Observability

`service.name = access_management`; the OpenObserve stream has the same name.
A PDP outage is logged at **ERROR**, which is what opens a self-heal incident —
routine denials are not, so real incidents are not buried in them. See
`integration/OBSERVABILITY.md`.
