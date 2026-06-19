# The hardening loop — explain like I'm 5

This folder turns "I hope it's production-ready" into "a dumb, honest machine
says it's production-ready." You stop trusting any AI's opinion of its own work
and let a set of pass/fail checks be the judge.

## The pieces

| File | What it is | Plain-English job |
|------|-----------|-------------------|
| `verify.sh` | **The judge** | Runs every objective check (build, lint, tests, security scan, **policy tests**, helm, kamal). Prints `GATE: GREEN` or `GATE: RED`. |
| `harden.sh` | **The fixer (inner loop)** | If the judge says RED, asks Claude Code to fix the policies/deploy config, then re-runs. Repeats until green. |
| `review.sh` | **The second opinion** | A separate, adversarial Claude review. Writes `review-findings.json`. |
| `gate.sh` | **The bouncer** | Final verdict: green judge **AND** no unresolved critical/high findings. |
| `DONE.md` | **The finish line** | The checklist that defines "done". |
| `validate_kamal.rb` | helper | Structurally checks the Kamal config when the `kamal` CLI isn't installed. |

## What the loop is and isn't allowed to touch

This repo is a fork of **Cerbos**, a mature, heavily-tested open-source
authorization engine. The loop must **never** edit the engine
(`internal/`, `api/`, `pkg/`, `cmd/`, `private/`, `schema/`, `tools/`,
`go.*`). It only hardens **what is yours**:

- `policies/**` — the ERP access rules and their tests.
- `deploy/kamal/**`, `config/deploy.yml`, `.kamal/**`, `Gemfile` — the deployment.

## Run it step by step

```bash
# 0) one-time: make the scripts executable (already done in the repo)
chmod +x harden/*.sh .kamal/hooks/pre-deploy

# 1) Run the judge by hand. See exactly what's green/red.
bash harden/verify.sh
#    Fast subset while iterating (policies + kamal + helm only):
FAST=1 bash harden/verify.sh
#    Just one thing:
STAGES="policies" bash harden/verify.sh

# 2) Run the fixer loop (COSTS MONEY — caps are intentional, start small).
ROUNDS=4 MAX_TURNS=30 bash harden/harden.sh

# 3) Get a second, adversarial opinion.
bash harden/review.sh

# 4) Ask the bouncer for the final verdict, then YOU read the diff and merge.
bash harden/gate.sh
git diff
```

## Two standing cautions

1. **The loop is only as good as `verify.sh`.** Today it proves the engine
   builds/tests, policies compile and pass their tests, and the deploy config is
   valid. It does **not** yet prove a live PDP answers real auth requests
   correctly end-to-end. Each real bug you hit, **add a gate for it** (see the
   ratchet section in `DONE.md`).
2. **`harden.sh` and `review.sh` bill against your Anthropic account.** Keep
   `ROUNDS`/`MAX_TURNS` small until you trust the loop. Prefer running inside an
   isolated container.

## Tools the full gate wants installed

`go` (required), `golangci-lint`, `gotestsum`, `govulncheck`, `helm`, and
`kamal` (via `bundle install`). Missing tools show as `SKIP` — that coverage is
simply not being checked locally. CI (`.github/workflows/gatekeeper.yml`)
installs them so nothing is skipped on a pull request.
