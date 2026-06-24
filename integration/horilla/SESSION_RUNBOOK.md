# Horilla session runbook — land `cerbos_access` as a real PR

This session is scoped to `access_management`, so it can't push to the Horilla
repo. Run the steps below in **a Claude Code session pointed at your Horilla
repo** (or do them by hand). The app is already built and waiting at
`access_management/integration/horilla/cerbos_access/`.

Total time: ~10 minutes.

---

## Paste this as the session's task

> Install the `cerbos_access` Django app into this Horilla project and open a PR.
> Source the app from the `access_management` repo at
> `integration/horilla/cerbos_access/`. Do the wiring in
> `integration/horilla/settings_snippet.py`. Specifically:
> 1. Copy the `cerbos_access/` package into the project root (next to `employee/`).
> 2. Edit `horilla/settings.py`: add `"cerbos_access"` to `INSTALLED_APPS` and set
>    `CERBOS_PDP_URL` from env (default `http://localhost:3592`).
> 3. Edit `horilla/horilla_apps.py`: append `"cerbos_access"` to `SIDEBARS`.
> 4. Edit `horilla/urls.py`: add `path("", include("cerbos_access.urls"))`.
> 5. Run `python manage.py makemigrations cerbos_access && python manage.py migrate`.
> 6. Run `python manage.py check` and fix any issues without touching unrelated code.
> 7. Commit on a new branch and open a PR titled
>    "Add Cerbos access-management page (cerbos_access)".
> Do not modify unrelated Horilla code. Keep the role list in `cerbos_access/
> catalog.py` matching `access_management/integration/role-catalog.yaml`.

---

## The exact edits (reference)

`horilla/settings.py` — after the `INSTALLED_APPS` list:
```python
INSTALLED_APPS += ["cerbos_access"]
CERBOS_PDP_URL = env("CERBOS_PDP_URL", default="http://localhost:3592")
```

`horilla/horilla_apps.py` — append to `SIDEBARS`:
```python
SIDEBARS.append("cerbos_access")
```

`horilla/urls.py` — add to `urlpatterns`:
```python
from django.urls import include, path
urlpatterns += [path("", include("cerbos_access.urls"))]
```

## Migrate & grant access

```bash
python manage.py makemigrations cerbos_access
python manage.py migrate
```
Then grant the permission `cerbos_access.manage_employeeaccess` to the admin
group (Django admin → Groups, or Horilla user groups). The sidebar menu is hidden
from anyone without it.

## Validate before opening the PR

```bash
python manage.py check                          # system checks pass
python manage.py makemigrations --check --dry-run cerbos_access   # no missing migrations
```
Then click through: **Access Management → Employee Access** → pick an employee →
**Edit access** → tick roles → **Save** → **Preview access** (needs the PDP
reachable at `CERBOS_PDP_URL`).

## Two ways the admin can manage assignments

Both ship in the app — pick what suits you (see the UI note in the chat):
- **Django admin** — zero setup beyond install; `EmployeeAccess` is registered.
- **The Horilla page** — the sidebar menu item with checkboxes + live preview.

## Don't forget the ERP side

Enforcement lives in the ERP, not Horilla. Wire
`access_management/integration/erp/cerbos_erp.py` into the ERP so it calls
`can(...)` — the HRMS only *assigns* roles; the ERP *checks* them.
