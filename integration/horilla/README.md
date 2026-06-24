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
