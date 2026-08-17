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
- [ ] **helm** — `helm lint deploy/charts/cerbos` passes, AND the MCP-enabled render
      actually ships the Contract-A Service/port with the bearer arriving only by
      `secretKeyRef`, AND enabling it without `mcp.existingSecret` fails at render.
- [ ] **kamal** — `kamal config` (or the structural validator) passes; Kamal pinned to 2.11.0.
- [ ] **deploy** — the Kamal pre-deploy hook actually blocks an unfilled
      `config/deploy.yml`, and actually lets a filled one through.
- [ ] **compose** — `docker-compose.mcp.yml` refuses to render without
      `ACCESS_MCP_TOKEN` and still names the service/port the agent platform binds.

> A gate only proves what it actually runs. If `verify.sh` reports SKIP for any
> stage, that coverage is missing — install the tool or rely on CI.

### Known blocker: `vuln` is RED, and the fix is outside this repo's charter

Install `govulncheck` (`bash harden/setup.sh vuln`) and the stage goes RED, not
green — it was only ever SKIPPING because the tool was absent, which is the
"SKIP quietly becomes never" failure the gate warns about. Measured with
`govulncheck v1.1.4` against the toolchain in `go.mod`:

> **11 vulnerabilities the code actually calls** — 9 in the Go standard library
> (`net/url`, `html/template`, `crypto/tls` ×2, `net/http` ×2, `encoding/xml`,
> `encoding/asn1`, `os`), fixed in **go1.26.5/1.26.6** versus the pinned
> `toolchain go1.26.4`; plus **GO-2026-6061** in `google.golang.org/grpc@v1.81.1`
> → v1.82.1, and **GO-2026-5970** in `golang.org/x/text@v0.38.0` → v0.39.0.
>
> GO-2026-6061 is the one to look at first: it is in gRPC's **xDS RBAC
> authorization engine and HTTP/2 transport server**, on a service whose entire
> job is authorization over gRPC.

Every one of these is fixed by editing `go.mod` (the `toolchain` directive, the
`grpc` require, the `x/text` require) — which **golden rule 1 puts off-limits**.
So this does not get patched here. Raise it with whoever owns the fork's
upstream sync: rebase onto a Cerbos release built on go1.26.6 with grpc ≥1.82.1,
then re-run `STAGES=vuln bash harden/verify.sh`. Do **not** close this box by
adding an ignore list — that converts a real finding back into a silent SKIP.

## Deploy-readiness

- [ ] Cerbos image tag is pinned in `deploy/kamal/Dockerfile` (no `:latest`).
- [ ] `config/deploy.yml` placeholders (`<-- CHANGE`) are filled for the target.
- [ ] No real secrets are committed; `.kamal/secrets` only interpolates env vars.
- [ ] TLS is terminated at the edge (`proxy.ssl: true`) for any public host.
- [ ] Admin API and playground are disabled in `deploy/kamal/conf.yaml`.
- [ ] `docker build -f deploy/kamal/Dockerfile .` succeeds (run `STAGES=docker verify.sh`).
- [ ] The pre-deploy hook (`.kamal/hooks/pre-deploy`) blocks deploys on bad policies.
- [ ] Every guard above is **executed by a stage**, not merely present in a file.
      A guard nothing runs is a comment: five deletions of these guards once left
      the gate GREEN. `harden/check_deploy_guards.sh` is what closed that.

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
