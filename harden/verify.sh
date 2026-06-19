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
# Stages: compile lint test vuln policies helm kamal docker
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
stage_lint()     { have golangci-lint || return 2; golangci-lint run --config=.golangci.yaml; }
stage_test()     {
  have go || return 2
  if have gotestsum; then gotestsum -- -tags=tests,integration -count=1 ./...
  else go test -tags=tests,integration -count=1 ./...; fi
}
stage_vuln()     { have govulncheck || return 2; govulncheck ./...; }
stage_policies() { have go || return 2; go run ./cmd/cerbos compile policies/; }
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
  STAGES="${STAGES:-policies kamal helm}"
else
  STAGES="${STAGES:-compile lint test vuln policies helm kamal}"
fi

for s in $STAGES; do
  case "$s" in
    compile)  run_stage compile  stage_compile  ;;
    lint)     run_stage lint     stage_lint     ;;
    test)     run_stage test     stage_test     ;;
    vuln)     run_stage vuln     stage_vuln     ;;
    policies) run_stage policies stage_policies ;;
    helm)     run_stage helm     stage_helm     ;;
    kamal)    run_stage kamal    stage_kamal    ;;
    docker)   run_stage docker   stage_docker   ;;
    *) printf '%sUnknown stage: %s%s\n' "$RED" "$s" "$RST" ;;
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
