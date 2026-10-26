# Role & attribute contract

This is the **integration contract** between your ERP (+ HRMS, + future SSO) and
the Cerbos access layer. Cerbos stores no users; your systems supply *who the
user is* on every request, and these policies decide *what they may do*.

> **Two things, two homes.** The **rules** (role → allowed actions) live in this
> repo as YAML. The **assignments** (which user has which role, and their org
> attributes) come from your systems and are sent in each request. This document
> is the agreed shape of what gets sent.

---

## 1. Who supplies what

```
            ROLES (finance_manager, accountant, ...)        ATTRIBUTES (department, location, ...)
                         │                                              │
   ┌─────────────────────┴───────────────┐          ┌──────────────────┴──────────────────┐
   │  Today: your custom ERP (a user→     │          │  HRMS: department, manager,          │
   │  roles table / admin screen)         │          │  job_title, employment_status        │
   │  Later: IdP/SSO groups (e.g.         │          │  Ops/ERP: warehouse location,        │
   │  Keycloak, Okta, Entra) — same       │          │  production line, team               │
   │  contract, different source          │          │                                      │
   └─────────────────────┬───────────────┘          └──────────────────┬──────────────────┘
                         └──────────────► ERP backend builds request ◄──┘
                                                    │
                                                    ▼
                                       Cerbos PDP  →  ALLOW / DENY
```

**Important:** *principal* attributes (about the user) come from HRMS/IdP/ERP.
*resource* attributes (about the thing being accessed — an invoice's `amount`,
a record's `owner`) come from **the ERP business object itself** at request time,
not from HR.

### Your stack (custom ERP + HRMS, no IdP yet)

- **Roles → start in the ERP.** A simple `user_id → [roles]` table with an admin
  screen is enough to begin. This is the only place an admin "assigns access."
- **Attributes → from the HRMS.** Sync (or fetch at login) `department`,
  `manager`, `job_title`, `employment_status`; the ERP/ops system supplies
  operational attributes like warehouse `location` and production `line`.
- **When you add SSO** (recommended: **Keycloak** — open-source, self-hostable,
  pins cleanly like the rest of this stack; or Okta/Entra), move role storage to
  IdP **groups**. The request below does not change — only where the ERP reads
  roles from changes.

---

## 2. Role catalog

Base roles your systems must be able to assign. `admin` is powerful (full
access) — grant sparingly. `employee` is the baseline every staff member gets;
the derived roles below build on it.

| Role | Module | Can (summary) |
|------|--------|---------------|
| `employee` | all | baseline; enables `owner` / `same_department` derived roles |
| `admin` | all | everything (`actions: ["*"]`) — keep this list short |
| `accountant` | finance | view/create invoices |
| `finance_manager` | finance | approve invoices **< $10,000** |
| `warehouse_clerk` | inventory | view; create/adjust **in own location** |
| `warehouse_manager` | inventory | + transfer/delete anywhere |
| `hr_specialist` | hr | view/edit employee records |
| `hr_manager` | hr | + terminate |
| `sales_rep` | sales | view/create; update **own** leads |
| `sales_manager` | sales | + reassign/update any lead |
| `buyer` | purchasing | view/create; submit **own** POs |
| `purchasing_manager` | purchasing | approve POs **≤ $25,000** |
| `operator` | manufacturing | view; start/complete **on own line** |
| `supervisor` | manufacturing | + start/complete any line, cancel |
| `ops` (token) | operations | view/create purchase orders (not approve; submit **own**); view stock; MCP dispatch like staff, destructive tools only with a recorded approval; **not** gateway administration |
| `hr` (token) | hr | view/edit employee records (not terminate); MCP dispatch as `ops` |
| `warehouse` (token) | inventory | view stock, adjust **in own location**; view tenant orders/shipments; MCP dispatch as `ops`; **no finance** |
| `external_auditor` (token) | external | **read-only, NOT staff**: dispatch of the five `audit_prep` read tools in its own tenant; nothing else, no write of any kind — even combined with any other role |
| `ml_lead` (token) | model_governance | first approver of every AI model change; files changes and emergency rollbacks; never approves their own |
| `controller` (token) | model_governance | second approver of domain-wide / material model changes; confirms the SOX-significant agent list |
| `cfo_designate` (token) | model_governance | third approver of material model changes (base model, global, SOX-significant agent) |
| `oncall_lead` (token) | model_governance | approves an emergency model rollback (1h SLA); a rollback is never automatic |

(token) = **token role** (`keycloak_realm_role: true` in the catalog): also a realm
role of the same name in Keycloak realm `erp`, which the ERP middleware reads
as the scope `OPS` / `HR` / `WAREHOUSE` / `EXTERNAL_AUDITOR`. The middleware
defines these realm roles (`keycloak/import/erp-realm.json`); **this repo
assigns them** — see "Token roles" below.

`external_auditor` is for people outside the company. An employee whose only
assigned roles are external does **not** get the `employee` baseline
(`cerbos_access/principal.py`), so no ownership rule can open a write to them.

**Derived roles** (computed by Cerbos, never assigned directly — defined in
`_common/derived_roles.yaml`):

| Derived role | Applies when | Used by |
|--------------|--------------|---------|
| `owner` | `resource.attr.owner == principal.id` (and has `employee`) | finance, hr, sales, purchasing |
| `same_department` | `resource.attr.department == principal.attr.department` | available for future rules |

---

### How these roles reach the MCP gateway policy

The ERP middleware's PEP does not send catalog keys. It sends the token's
realm roles as **gateway scopes**: upper-cased, `-` as `_`, with `erp-admin`
-> `ADMIN` (`scopes_from_claims` in erp_django_middleware). So `ops` -> `OPS`,
`external_auditor` -> `EXTERNAL_AUDITOR`, `staff` -> `STAFF`. Its request is
kind `mcp_tool`: `resource.id` is the tool name, `resource.attr` has
`tenant_id`, `module`, `destructive`, `approved`/`approval_ref` (no `approved`
key when there is no approval), and `principal.attr.tenants` is the verified
token's tenant groups. `policies/agent/gateway_dispatch.yaml` decides exactly
that, requiring the resource's tenant to be IN `tenants`. One literal example
(`integration/contracts/mcp_dispatch_request.json`) is asserted on both sides,
so a drift in either fails CI.

`staff` is in the catalog because the policies grant it, but it is **not
assigned on the access page**: every user in realm `erp` holds it through the
realm's default role — an external auditor's account included.

**Holding `external_auditor` confines a principal to the five audit reads,
whatever else it holds** (inherited `staff`, `employee`, even `admin` — an
admin must not hold the role at all). Enforced on both sides: the middleware's
`scopes_from_claims` reduces such a token to `EXTERNAL_AUDITOR` alone and its
allowlist refuses everything else; `gateway_dispatch.yaml` and `mcp_tool.yaml`
carry a DENY for any non-allowlisted or destructive tool (and for
administer/list/describe) when the role is present. The DENY is written with
`roles: ["*"]` and an `in request.principal.roles` test, because Cerbos
evaluates each role separately and a DENY scoped to the auditor role alone
would leave a staff ALLOW standing.

### Token roles: assigning them puts them in the Keycloak token

Assigning a token role on the access page is the only supported way to grant
it. On every save of an `EmployeeAccess` record the Horilla app pushes the
change to Keycloak after the transaction commits
(`integration/horilla/cerbos_access/keycloak_sync.py`); a full reconcile is
`python manage.py sync_keycloak_roles [--dry-run]`.

- **Scope of the sync:** only catalog roles marked `keycloak_realm_role: true`.
  Any other realm role a user holds is never added or removed. Holders of a
  token role that the page does not know (service accounts, hand grants) are
  reported by the reconcile and left unchanged.
- **Matching:** employee → Keycloak user by **email** (exact, exactly one
  match). No match or several are reported; users are never created.
- **Config (env):** `KEYCLOAK_ADMIN_URL`, `KEYCLOAK_ADMIN_REALM` (default `erp`),
  `KEYCLOAK_ADMIN_CLIENT_ID`, `KEYCLOAK_ADMIN_CLIENT_SECRET` — a service account
  holding only `realm-management` `manage-users` and `view-realm`. Unset: the
  save is a logged no-op, the command exits non-zero.
- **Failure:** a Keycloak error on save is logged and the record stays saved —
  the next reconcile repairs the token. On the command it exits non-zero.
- Removing a role takes effect in new tokens; an access token already issued
  keeps it until it expires (30 minutes in realm `erp`).

---

## 3. Attribute contract

### Principal attributes (about the user — from HRMS/IdP/ERP)

| Attribute | Type | Meaning | Source |
|-----------|------|---------|--------|
| `department` | string | user's department | **HRMS** |
| `location` | string | warehouse the user works in | ERP/Ops |
| `line` | string | production line the user is assigned to | ERP/Ops |

> `manager`, `job_title`, `employment_status` aren't used by the current rules
> but are good to pass — you'll want them as you add manager-approval or
> "active-employee-only" conditions.

### Resource attributes (about the object — from the ERP record)

| Resource (`kind`) | Attributes the rules read |
|-------------------|---------------------------|
| `finance:invoice` | `owner`, `amount`, `department` |
| `inventory:item` | `location` |
| `hr:employee_record` | `owner`, `department` |
| `sales:lead` | `owner` |
| `purchasing:purchase_order` | `owner`, `amount` |
| `manufacturing:work_order` | `line` |

---

## 4. The request your ERP backend makes

For every access check, the ERP assembles the principal (roles + attrs it looked
up) and the resource (attrs from the business object), and calls Cerbos:

```bash
curl --silent "http://<cerbos-host>:3592/api/check/resources" -d @- <<'JSON'
{
  "requestId": "req-001",
  "principal": {
    "id": "jane",
    "roles": ["finance_manager", "employee"],
    "attr": { "department": "finance" }
  },
  "resources": [
    {
      "actions": ["approve"],
      "resource": {
        "kind": "finance:invoice",
        "id": "inv-77",
        "attr": { "owner": "amy", "amount": 5000, "department": "finance" }
      }
    }
  ]
}
JSON
# -> results[0].actions.approve == "EFFECT_ALLOW"
```

Use a client **SDK** instead of raw HTTP where you can — Go, Java, JavaScript,
.NET, PHP, Python, Ruby, Rust: <https://docs.cerbos.dev/cerbos/latest/api/>.

**SSO/JWT option:** once you have an IdP issuing JWTs, the ERP can forward the
token and policies can read claims via `request.aux_data.jwt.*`. The simplest and
most portable path, though, is what's shown above: the ERP puts roles + attrs in
`principal`. Keep that as the contract; treat JWT as an optimization.

---

## 5. Rules of thumb

- **Least privilege.** Assign the narrowest role that works; reserve `admin`.
- **Revoke on access change, not employment change.** Roles are about
  permissions — pulling a role should be instant and independent of HR status.
- **Resource attrs come from the live object.** Always send the record's real
  `amount`/`owner`/status, not a cached guess — conditions depend on them.
- **Add a module → update this catalog.** New role or attribute? Add it here and
  to the policy + its `*_test.yaml`, then `STAGES="policies" bash harden/verify.sh`.
