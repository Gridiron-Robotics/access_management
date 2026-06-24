# ERP ↔ Cerbos client (`cerbos_erp.py`)

A paste-ready client for the **ERP** — the service that *enforces* access by asking
Cerbos "can this user do this?" on each protected action. (The HRMS *assigns*
roles; the ERP *checks* them. Two things, two homes — see
[`../../policies/ROLES.md`](../../policies/ROLES.md).)

> Written in **Python** (matches your Horilla/Django stack and works in any Python
> service). If your ERP is another language, use the official SDK instead — Go,
> Java, JavaScript, .NET, PHP, Ruby, Rust:
> <https://docs.cerbos.dev/cerbos/latest/api/>. The request shape is identical;
> tell me the language and I'll port this `can()` helper.

## Install

1. Copy `cerbos_erp.py` into your ERP project.
2. `pip install requests`
3. Point it at the PDP: `export CERBOS_PDP_URL=http://access-management:3592`
   (the Kamal/Helm service URL for this repo's deployment).

## Use it

```python
from cerbos_erp import can, principal, resource

p = principal("jane", ["finance_manager", "employee"], department="finance")
inv = resource("finance:invoice", "inv-77", owner="amy", amount=5000, department="finance")

if can(p, "approve", inv):
    ...  # do the approval
else:
    raise PermissionDenied()
```

Hide controls the user can't use:

```python
from cerbos_erp import CerbosERP
cerbos = CerbosERP()
buttons = cerbos.allowed_actions(p, inv, ["view", "approve", "delete"])
# -> {"view", "approve"}
```

## Where do `roles` and `attr` come from?

- **roles** — from your roles store. In your setup that's the HRMS: call its
  principal API, which returns `{id, roles, attr}` ready to use:
  ```python
  import requests
  who = requests.get(f"{HRMS}/api/access/principal/{emp_id}/",
                     headers={"Authorization": f"Api-Key {KEY}"}, timeout=5).json()
  can(who, "approve", inv)
  ```
  (Later, if you adopt SSO, read roles from IdP groups instead — same `can()` call.)
- **principal `attr`** (department, location, line) — about the *user*, from HRMS/IdP.
- **resource `attr`** (owner, amount, status) — about the *object*, from the live
  ERP record at request time. Always send the real value; conditions depend on it.

## Fail closed

`can()` raises if the PDP is unreachable. Catch it and **deny** (don't default to
allow):

```python
try:
    ok = can(p, "approve", inv)
except Exception:
    ok = False   # PDP down -> deny
```

## Django sugar (optional)

```python
from functools import wraps
from django.core.exceptions import PermissionDenied
from cerbos_erp import can

def require(action, build_resource):
    def deco(view):
        @wraps(view)
        def inner(request, *a, **k):
            p = request.cerbos_principal           # set by your auth middleware
            if not can(p, action, build_resource(request, *a, **k)):
                raise PermissionDenied()
            return view(request, *a, **k)
        return inner
    return deco
```

## Keep it honest

The list of valid actions/resources is defined by the policies in `policies/**`.
When you add a module, the only ERP change is calling `can()` with the new
`kind`/`action` — no client changes needed.
