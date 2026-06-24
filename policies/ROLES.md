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

**Derived roles** (computed by Cerbos, never assigned directly — defined in
`_common/derived_roles.yaml`):

| Derived role | Applies when | Used by |
|--------------|--------------|---------|
| `owner` | `resource.attr.owner == principal.id` (and has `employee`) | finance, hr, sales, purchasing |
| `same_department` | `resource.attr.department == principal.attr.department` | available for future rules |

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
