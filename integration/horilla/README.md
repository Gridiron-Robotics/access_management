# Horilla ↔ Cerbos integration (`cerbos_access`)

A self-contained Django app that adds the **"set each employee's access" page** to
your Horilla HRMS and connects it to the Cerbos access layer in this repo.

It gives you:
- A sidebar menu **Access Management → Employee Access**.
- A per-employee page to tick **roles** (grouped by module, from the catalog).
- A **principal API** your ERP calls to get a user's `{id, roles, attr}`.
- A **Preview access** button that asks the Cerbos PDP what the employee can do.

> **Reminder — assign roles, not policies.** This page assigns *roles* to people.
> The *rules* (what each role can do) live in `policies/**` / Cerbos Hub. See
> [`../README.md`](README.md) and [`../../policies/ROLES.md`](../../policies/ROLES.md).

## What gets stored where

| Thing | Where |
|------|------|
| Which roles an employee has | `EmployeeAccess` model (Horilla DB) — set on this page |
| Employee attributes (department, …) | Horilla's existing `EmployeeWorkInformation` |
| The rules (role → actions) | `policies/**` in access_management (+ optional Cerbos Hub) |
| The yes/no decision | Cerbos PDP at request time |
| Token roles (`ops`, `hr`, `warehouse`, `external_auditor`) in the user's Keycloak token | Keycloak realm `erp` role mappings — written by this app from `EmployeeAccess`, never by hand |

## Install (in your Horilla project)

1. **Copy the app** `cerbos_access/` into your Horilla project root (next to
   `employee/`, `base/`).
2. **Register it** — edits to three files (see `settings_snippet.py` for exact lines):
   - `horilla/settings.py`: `INSTALLED_APPS += ["cerbos_access"]` and set `CERBOS_PDP_URL`.
   - `horilla/horilla_apps.py`: `SIDEBARS.append("cerbos_access")` (so the menu shows).
   - `horilla/urls.py`: `path("", include("cerbos_access.urls"))`.
3. **Migrate**:
   ```bash
   python manage.py makemigrations cerbos_access
   python manage.py migrate
   ```
4. **Grant the permission** `cerbos_access.manage_employeeaccess` to whichever
   group/admin should manage access (Django admin → Groups, or Horilla's user
   groups). The menu is hidden from users without it.

## Use it

Open **Access Management → Employee Access**, search an employee, click **Edit
access**, tick roles, **Save**. Hit **Preview access** to see (via Cerbos) what
those roles allow.

## Token roles reach Keycloak (realm `erp`)

The ERP middleware authorizes from the Keycloak token, so the catalog roles
marked `keycloak_realm_role: true` (today `ops`, `hr`, `warehouse`,
`external_auditor`) must be realm roles on the user. This app makes that so;
nobody assigns them in Keycloak by hand any more.

- **On save** (`signals.py`): after the transaction commits, the employee's
  token roles are pushed to Keycloak — missing ones added, revoked ones
  removed. Opening the edit page (which creates an empty record) pushes
  nothing. Deleting the record revokes the token roles.
- **Full reconcile** (`management/commands/sync_keycloak_roles.py`):
  ```bash
  python manage.py sync_keycloak_roles --dry-run   # print the diff, change nothing
  python manage.py sync_keycloak_roles             # apply
  python manage.py sync_keycloak_roles --employee 42
  ```
  Run it once with `--dry-run` when you first configure the sync: anyone who
  was granted one of these roles by hand in Keycloak and has no matching
  assignment here would lose it. Schedule it (e.g. nightly) as the repair path.
- **Only token roles are touched.** Every other realm role a user holds
  (`manager`, `finance`, default roles, ...) is never added or removed. A user
  who holds a token role but matches no employee (a service account, say) is
  reported and left alone.
- **Matching is by email.** `Employee.email` must equal the Keycloak user's
  email (exact; exactly one user). Horilla stores no Keycloak user id, and the
  Horilla username is not guaranteed to be the Keycloak username. No match or
  several matches are reported; Keycloak users are never created.
- **Configuration** — environment of the Horilla process (see
  `settings_snippet.py`):

  | Variable | Value |
  |---|---|
  | `KEYCLOAK_ADMIN_URL` | Keycloak base URL, e.g. `https://sso.example.com` |
  | `KEYCLOAK_ADMIN_REALM` | `erp` (the default) |
  | `KEYCLOAK_ADMIN_CLIENT_ID` | a confidential client in that realm with a service account |
  | `KEYCLOAK_ADMIN_CLIENT_SECRET` | its secret — from your secret store, never committed |

  Give the service account **only** the `realm-management` client roles
  `manage-users` and `view-realm`. If the URL, client id or secret is unset the
  sync is off: each save logs a warning and does nothing, and the command exits
  non-zero. The secret and the access token are never logged.
- **When Keycloak fails:** on save the error is logged and the access record
  **stays saved** — the token is out of date until the next reconcile repairs
  it. The command exits non-zero on any Keycloak error (after processing the
  rest). A token role missing from the realm is reported as such; create it
  per `keycloak/DEPLOYMENT.md` in `erp_django_middleware`.
- A removal applies to newly issued tokens; an access token already issued
  keeps the role until it expires (30 minutes in realm `erp`).

## How your ERP consumes assignments

The ERP doesn't read Horilla's DB directly — it calls the principal API, then
sends that principal to Cerbos:

```bash
# 1) Get the principal from Horilla (service-to-service, API key auth)
curl -H "Authorization: Api-Key <KEY>" \
     https://hrms.example.com/api/access/principal/42/
# -> {"id":"jane","roles":["finance_manager","employee"],"attr":{"department":"finance"}}

# 2) Send it to Cerbos with the resource (see policies/ROLES.md for the full call)
```

Create the API key in Django admin (**API Keys**, from `rest_framework_api_key`,
already installed in your Horilla). Treat it like any other secret.

## Keep it in sync

The role list here mirrors `integration/role-catalog.yaml` and the policies. When
you add a module/role: update the policy + its `*_test.yaml`, the catalog, and
`cerbos_access/catalog.py`, then run `STAGES="policies" bash harden/verify.sh`.

## Status

This app is **syntax-checked but not yet run against your Horilla database** (it
needs the full Horilla runtime). Install it on a branch, run the migration, and
click through before relying on it. It follows Horilla's own conventions
(sidebar.py, `@login_required`/`@permission_required`, HTMX, `index.html`).

The Keycloak sync's logic (`keycloak_sync.py`, Django-free) is unit-tested
against a faked Keycloak admin REST API in
`integration/tests/test_keycloak_sync.py`. The Django glue (`signals.py`, the
management command) was smoke-run once on Django 4.2.16 with a stand-in
`employee.Employee` model and a faked Keycloak (save after commit, no push on a
rolled-back save or an empty create, revoke on delete, dry-run, unconfigured
exit code); not against a real Horilla or a live Keycloak.
