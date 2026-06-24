# CLAUDE.md — rules for working in this repo

## What this repo is

`access_management` is a fork of **Cerbos**, a mature, heavily-tested open-source
authorization engine (Go). We use it as the access-management layer for our ERP:
it decides who can use which module/feature. The Cerbos engine is **upstream
code** — it is not ours to rewrite.

## Golden rules

1. **Never modify the upstream engine.** Off-limits: `internal/`, `api/`, `pkg/`,
   `cmd/`, `private/`, `schema/`, `tools/`, `go.mod`, `go.sum`, `go.work`,
   `.goreleaser.yml`, `.golangci.yaml`. Changing these diverges us from upstream
   and breaks a well-tested codebase. If something there seems wrong, raise it —
   don't patch it.
2. **Our work lives in:**
   - `policies/**` — ERP access rules + their `*_test.yaml` tests.
   - `deploy/kamal/**`, `config/deploy.yml`, `.kamal/**`, `Gemfile` — deployment.
   - `harden/**` — the review/test/gate loop.
   - `integration/**` — HRMS/ERP integration contract (role catalog + assignment page spec).
3. **Pin every version. Never use `latest`.** The Cerbos image tag in
   `deploy/kamal/Dockerfile` is pinned; Kamal is pinned to **2.11.0** in
   `Gemfile`; Go deps are pinned in `go.mod`/`go.sum`; npm wrappers pin exact
   versions. If you add a dependency, pin it to an exact version.
4. **Never weaken a check to go green.** Don't delete a failing test, broaden a
   policy to allow-all, or relax a security setting to pass the gate. Fix the
   real cause.

## The loop (how we decide something is done)

```bash
bash harden/verify.sh      # the objective gate (build, lint, test, vuln, policies, helm, kamal)
ROUNDS=4 MAX_TURNS=30 bash harden/harden.sh   # inner fix loop (costs money)
bash harden/review.sh      # adversarial second opinion -> review-findings.json
bash harden/gate.sh        # final verdict; a human still clicks merge
```

The finish line is defined in `harden/DONE.md`. The objective gate is the only
thing allowed to declare victory.

## Working on policies

Model each ERP module as a resource `<module>:<kind>`, each feature as an action,
and grant `roles`/`derivedRoles`. **Every policy needs a `*_test.yaml` with DENY
cases, not just ALLOW.** Validate with:

```bash
STAGES="policies" bash harden/verify.sh
```

See `policies/README.md` for the step-by-step.

## Deployment

Two supported paths, both kept valid by the gate:

- **Kamal 2.11.0** (plain Docker hosts): `config/deploy.yml` + `deploy/kamal/`.
  Deploy with `bundle exec kamal deploy`.
- **Helm** (Kubernetes): the chart in `deploy/charts/cerbos`.

Both run the same pinned Cerbos image with our `policies/` baked in.
