# DONE — Acceptance checklist (the finish line)

You can't loop toward "perfect" if nothing defines perfect. This is the
definition of done for `access_management`. The loop is finished when every box
below is true. `harden/gate.sh` enforces the automated ones.

## Objective gate (`bash harden/verify.sh` is GREEN)

- [ ] **compile** — `go build ./...` succeeds.
- [ ] **lint** — `golangci-lint` passes with the repo config.
- [ ] **test** — the Go test suite passes (`-tags=tests,integration`).
- [ ] **vuln** — `govulncheck` reports no known vulnerabilities.
- [ ] **policies** — `cerbos compile policies/` compiles AND all policy tests pass.
- [ ] **helm** — `helm lint deploy/charts/cerbos` passes.
- [ ] **kamal** — `kamal config` (or the structural validator) passes; Kamal pinned to 2.11.0.

> A gate only proves what it actually runs. If `verify.sh` reports SKIP for any
> stage, that coverage is missing — install the tool or rely on CI.

## Deploy-readiness

- [ ] Cerbos image tag is pinned in `deploy/kamal/Dockerfile` (no `:latest`).
- [ ] `config/deploy.yml` placeholders (`<-- CHANGE`) are filled for the target.
- [ ] No real secrets are committed; `.kamal/secrets` only interpolates env vars.
- [ ] TLS is terminated at the edge (`proxy.ssl: true`) for any public host.
- [ ] Admin API and playground are disabled in `deploy/kamal/conf.yaml`.
- [ ] `docker build -f deploy/kamal/Dockerfile .` succeeds (run `STAGES=docker verify.sh`).
- [ ] The pre-deploy hook (`.kamal/hooks/pre-deploy`) blocks deploys on bad policies.

## Access-policy quality

- [ ] Every ERP module you expose has a resource policy under `policies/<module>/`.
- [ ] Every policy has a `*_test.yaml` suite that asserts **DENY** cases, not only ALLOW.
- [ ] No unintended `actions: ["*"]` / allow-all rule (admin-only is intentional).
- [ ] Conditions (amount caps, ownership, location) have explicit deny tests.

## Review & sign-off

- [ ] `harden/review.sh` run; no unresolved **critical/high** items in `review-findings.json`.
- [ ] `harden/gate.sh` prints **MERGE VERDICT: ELIGIBLE**.
- [ ] A human (you) read the diff and clicked merge.

## Ratchet

Each real bug you hit, **add a gate for it** so it can never come back:
a new policy test, a new `verify.sh` stage, or a new checklist line here.
