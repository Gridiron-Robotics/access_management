# HRMS access-assignment page — build spec

How to build the "set this employee's access" page in the HRMS, and how it plugs
into the Cerbos access layer. Pairs with [`policies/ROLES.md`](../policies/ROLES.md)
(the request contract) and [`role-catalog.yaml`](role-catalog.yaml) (the menu data).

## The golden rule: assign ROLES, not policies

- You do **not** create a policy per employee. Policies are shared rules
  (role → allowed actions), authored once and centrally.
- Per employee, the admin assigns **roles**; the systems supply **attributes**.
  Cerbos combines roles + rules at request time to decide ALLOW/DENY.
- Why: one rule per role scales to any number of people and keeps access
  auditable and least-privilege. One policy per person does neither.

## What the page shows (per employee)

1. **Read-only org info** pulled from the HRMS: department, location/line,
   manager, employment status.
2. **The access menu**: a checklist of assignable roles, grouped by module,
   rendered from `role-catalog.yaml` (`modules[].roles[]`, plus `baseline_roles`
   and `global_roles`). The admin ticks the roles this employee should have.
3. *(Optional)* **Effective-access preview**: show what the employee can actually
   do with the ticked roles, computed by asking Cerbos (see below).

## What the page stores

- Only the assignment: `{ user_id, roles: ["accountant", "employee", ...] }` in
  your roles store (an HRMS/ERP table). This is the source of truth for "who has
  which role" until/unless you move it to an IdP.
- **Do not store attributes here** — `department`, `location`, etc. live in the
  HRMS and are read at request time.

## How it feeds Cerbos (runtime)

On each access check, the backend:
1. loads the employee's **roles** from the roles store,
2. loads the employee's **attributes** from the HRMS,
3. calls Cerbos `CheckResources` with both (exact request in `policies/ROLES.md`).

The HRMS page itself does **not** call Cerbos to *save* anything — Cerbos is
stateless. The page just records role assignments your backend later sends.

## Keeping the menu in sync

The menu = `role-catalog.yaml`. The rule behind each role = `policies/**` (and,
if adopted, the Cerbos Hub UI). When you add a module/role: update the policy,
its `*_test.yaml`, and this catalog together, then run
`STAGES="policies" bash harden/verify.sh`.

## (Optional) Effective-access preview

To show an admin the effect of the roles they're assigning:
- **Per action**: call `CheckResources` for a representative set of actions per
  module and render the `EFFECT_ALLOW` results ("Jane can: view, create invoices").
- **Per record set**: use `PlanResources` to get a filter for "which invoices can
  Jane approve?" — handy if you also want to show scoped lists.

## Where the RULES are managed (not here)

This page only **assigns roles**. The meaning of each role is governed by the
policies in `policies/**` (git-ops, gated by `harden/`) and optionally authored
in the **Cerbos Hub** web console. Editing rules stays a reviewed change — never
something the HRMS page does directly.
