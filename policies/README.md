# ERP access policies

This folder is **your** authorization rules — who can do what in each ERP module.
It is the part of this repo that you own and change. The Cerbos engine (the rest
of the repo) reads these files and answers "can user X do action Y on resource Z?"

> **Integrating with your ERP / HRMS / SSO?** See **[ROLES.md](ROLES.md)** — the
> role catalog, the attribute contract (what comes from HRMS vs IdP vs the ERP),
> and the exact request your backend sends.

## How access works (the 4 ideas)

- **Principal** = a user, carrying **roles** (`accountant`, `warehouse_clerk`,
  `admin`) and optional attributes (`department`, `location`, `line`).
- **Resource** = a thing you protect, named `<module>:<kind>`, e.g.
  `finance:invoice`, with attributes (`owner`, `amount`, `department`).
- **Action** = what they want to do: `view`, `create`, `approve`, `delete`, ...
- **Policy** = a YAML file that says "for this resource, these roles can do these
  actions" — optionally only *if* a condition holds (that's RBAC turning into ABAC).

## What's here

```
policies/
├── _common/derived_roles.yaml   # shared "computed" roles (owner, same_department)
├── finance/invoice.yaml         # + invoice_test.yaml
├── inventory/item.yaml          # + item_test.yaml
├── hr/employee.yaml             # + employee_test.yaml
├── sales/lead.yaml              # + lead_test.yaml
├── purchasing/purchase_order.yaml
└── manufacturing/work_order.yaml
```

Each module has a **policy** and a **`*_test.yaml`** suite. The tests are the
safety net: `cerbos compile policies/` runs them and fails if any rule is wrong.

## Add a new module/feature in 3 steps

1. **Create the policy** `policies/<module>/<thing>.yaml`:

   ```yaml
   apiVersion: api.cerbos.dev/v1
   resourcePolicy:
     resource: "projects:task"      # <module>:<kind>
     version: "default"
     importDerivedRoles:
       - common_erp_roles
     rules:
       - actions: ["view", "create"]
         effect: EFFECT_ALLOW
         roles: ["project_member"]
       - actions: ["delete"]
         effect: EFFECT_ALLOW
         roles: ["project_manager"]
       - actions: ["*"]
         effect: EFFECT_ALLOW
         roles: ["admin"]
   ```

2. **Create the test** `policies/<module>/<thing>_test.yaml` — and always include
   at least one **DENY** case (proving people *can't* do what they shouldn't):

   ```yaml
   name: Project task policy tests
   principals:
     member_mia: { id: mia, roles: ["project_member"] }
   resources:
     task1: { id: t1, kind: "projects:task" }
   tests:
     - name: Member can create but not delete
       input: { principals: [member_mia], resources: [task1], actions: [create, delete] }
       expected:
         - principal: member_mia
           resource: task1
           actions: { create: EFFECT_ALLOW, delete: EFFECT_DENY }
   ```

3. **Verify** — this must pass before you commit:

   ```bash
   STAGES="policies" bash harden/verify.sh
   # or directly:
   go run ./cmd/cerbos compile policies/
   ```

## Assigning roles to real users

Cerbos decides; it does not store users. Your application (or its identity
provider) decides each user's `roles` and passes them in the authorization
request. Cerbos then evaluates these policies. See
<https://docs.cerbos.dev/cerbos/latest/api/> for the `CheckResources` request.

## Going deeper

- Derived roles: <https://docs.cerbos.dev/cerbos/latest/policies/derived_roles.html>
- Principal policies (per-user overrides): <https://docs.cerbos.dev/cerbos/latest/policies/principal_policies.html>
- Conditions / CEL expressions: <https://docs.cerbos.dev/cerbos/latest/policies/conditions.html>
