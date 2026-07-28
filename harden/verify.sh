#!/usr/bin/env bash
# verify.sh — the single objective gate ("the judge") for access_management.
#
# It runs deterministic pass/fail checks. Nothing here trusts an AI's opinion:
# a stage is GREEN only if the underlying tool exits 0.
#
# Usage:
#   bash harden/verify.sh                          # full gate (default)
#   FAST=1 bash harden/verify.sh                   # quick deploy-readiness subset
#   STAGES="policies kamal" bash harden/verify.sh  # run only these stages
#
# Stages: compile lint test vuln policies integration helm kamal docker
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

if [[ -t 1 ]]; then
  RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLD=$'\033[1m'; RST=$'\033[0m'
else
  RED=""; GRN=""; YLW=""; BLD=""; RST=""
fi
have() { command -v "$1" >/dev/null 2>&1; }

PASS=(); FAIL=(); SKIP=()
run_stage() {  # <name> <fn...>
  local name="$1"; shift
  printf '\n%s== %s ==%s\n' "$BLD" "$name" "$RST"
  local rc=0
  "$@" || rc=$?
  case "$rc" in
    0) PASS+=("$name"); printf '%s[PASS]%s %s\n' "$GRN" "$RST" "$name" ;;
    2) SKIP+=("$name"); printf '%s[SKIP]%s %s (required tool not installed)\n' "$YLW" "$RST" "$name" ;;
    *) FAIL+=("$name"); printf '%s[FAIL]%s %s (exit %s)\n' "$RED" "$RST" "$name" "$rc" ;;
  esac
}

export CGO_ENABLED="${CGO_ENABLED:-0}"

# ---- stages (return 0 pass, 1 fail, 2 skip) ------------------------------
stage_compile()  { have go || return 2; go build ./...; }
stage_lint()     {
  have golangci-lint || return 2
  # A golangci-lint built against an older Go than go.mod targets cannot load
  # the config at all — it never lints a line. That is an uninstalled tool
  # wearing a failure's clothes, so report it as SKIP: a FAIL here would say
  # "the code is bad" when nothing was examined, and a green would be worse.
  local out rc=0
  out="$(golangci-lint run --config=.golangci.yaml 2>&1)" || rc=$?
  printf '%s\n' "$out"
  if [[ $rc -ne 0 ]] && grep -q "used to build golangci-lint is lower than the targeted Go version" <<<"$out"; then
    printf 'golangci-lint is older than go.mod targets — nothing was linted.\n'
    return 2
  fi
  return $rc
}
stage_test()     {
  have go || return 2
  # Upstream's cerbosctl suites spin up containers via testcontainers. Without a
  # Docker daemon they cannot run — again SKIP, not FAIL.
  if ! docker info >/dev/null 2>&1; then
    printf 'no Docker daemon: upstream testcontainers suites cannot run.\n'
    return 2
  fi
  if have gotestsum; then gotestsum -- -tags=tests,integration -count=1 ./...
  else go test -tags=tests,integration -count=1 ./...; fi
}
stage_vuln()     { have govulncheck || return 2; govulncheck ./...; }
stage_policies() { have go || return 2; go run ./cmd/cerbos compile policies/; }
# The Python integration layer (Contract-A MCP surface + PDP client) is ours,
# not upstream. Its fail-closed behaviour — refuse to boot without a token,
# deny when the PDP is unreachable, refuse a principal with no tenant — is only
# provable by running these tests, so the judge runs them.
stage_integration() {
  have python3 || return 2
  python3 -c 'import fastapi, pytest' >/dev/null 2>&1 || return 2
  python3 -m pytest integration/tests -q
}
stage_helm()     { have helm || return 2; helm lint deploy/charts/cerbos; }
stage_kamal()    {
  if have kamal; then kamal config
  elif have bundle && [[ -f Gemfile ]] && bundle exec kamal version >/dev/null 2>&1; then bundle exec kamal config
  elif have ruby; then ruby harden/validate_kamal.rb
  else return 2; fi
}
stage_docker()   { have docker || return 2; docker build -f deploy/kamal/Dockerfile -t access-management:verify .; }

# ---- select & run --------------------------------------------------------
if [[ "${FAST:-0}" == "1" ]]; then
  STAGES="${STAGES:-policies integration kamal helm}"
else
  STAGES="${STAGES:-compile lint test vuln policies integration helm kamal}"
fi

for s in $STAGES; do
  case "$s" in
    compile)  run_stage compile  stage_compile  ;;
    lint)     run_stage lint     stage_lint     ;;
    test)     run_stage test     stage_test     ;;
    vuln)     run_stage vuln     stage_vuln     ;;
    policies) run_stage policies stage_policies ;;
    integration) run_stage integration stage_integration ;;
    helm)     run_stage helm     stage_helm     ;;
    kamal)    run_stage kamal    stage_kamal    ;;
    docker)   run_stage docker   stage_docker   ;;
    # A stage name the judge does not recognise is a FAILURE, not a notice.
    # Silently continuing means a typo in STAGES quietly drops a check while
    # the run still reports GREEN — the exact shape of a gate that lies.
    *) printf '%sUnknown stage: %s%s\n' "$RED" "$s" "$RST"; FAIL+=("unknown-stage:$s") ;;
  esac
done

# ---- summary -------------------------------------------------------------
printf '\n%s===== SUMMARY =====%s\n' "$BLD" "$RST"
printf '%sPASS%s: %s\n' "$GRN" "$RST" "${PASS[*]:-none}"
printf '%sSKIP%s: %s\n' "$YLW" "$RST" "${SKIP[*]:-none}"
printf '%sFAIL%s: %s\n' "$RED" "$RST" "${FAIL[*]:-none}"

if [[ "${#SKIP[@]}" -gt 0 ]]; then
  printf '\n%sWARNING:%s %d stage(s) skipped (tools not installed). A gate only proves\n' "$YLW" "$RST" "${#SKIP[@]}"
  printf 'what it actually ran — install the tools or run in CI for full coverage.\n'
fi

if [[ "${#FAIL[@]}" -gt 0 ]]; then
  printf '\n%sGATE: RED%s\n' "$RED" "$RST"
  exit 1
fi
printf '\n%sGATE: GREEN%s\n' "$GRN" "$RST"
exit 0
