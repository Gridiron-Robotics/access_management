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
  # wearing a failure's clothes, so SKIP: FAIL would say "the code is bad" when
  # nothing was examined, and green would be worse. Fix it by building the
  # linter with the toolchain go.mod pins — see harden/setup.sh.
  local out rc=0
  out="$(golangci-lint run --config=.golangci.yaml 2>&1)" || rc=$?
  printf '%s\n' "$out"
  if [[ $rc -ne 0 ]] && grep -q "used to build golangci-lint is lower than the targeted Go version" <<<"$out"; then
    printf 'golangci-lint predates the toolchain in go.mod — NOTHING WAS LINTED.\n'
    printf 'Fix: bash harden/setup.sh (builds a matching linter).\n'
    return 2
  fi
  return $rc
}

# Upstream packages whose tests require a Docker daemon (testcontainers) or that
# fail on upstream main in this fork. Excluded ONLY from the no-Docker subset —
# the full run still executes every one of them, and CI runs the full set.
#
# This list is not a place to hide our own failures: nothing under policies/ or
# integration/ may ever appear here, and the repo contains no Go of ours at all.
readonly GO_CONTAINER_PKGS='cmd/cerbosctl/(del|disable|enable|get|put)|internal/audit/(hub|kafka)|internal/storage/(blob|db/mysql|db/postgres|git|hub|overlay)'
readonly GO_UPSTREAM_RED_PKGS='internal/schema|internal/storage/index|internal/server|private/verify'

stage_test()     {
  have go || return 2

  if docker info >/dev/null 2>&1; then
    if have gotestsum; then gotestsum -- -tags=tests,integration -count=1 ./...
    else go test -tags=tests,integration -count=1 ./...; fi
    return $?
  fi

  # No Docker. Run everything that does NOT need it rather than skipping the
  # whole suite: a wholesale SKIP means a real regression in the 37 runnable
  # packages goes unnoticed until CI. Report the exclusion loudly so nobody
  # reads this as "the Go tests passed".
  printf 'no Docker daemon — running the subset that does not need one.\n'
  printf 'EXCLUDED (container-backed): %s\n' "$GO_CONTAINER_PKGS"
  printf 'EXCLUDED (red on upstream main, not ours): %s\n' "$GO_UPSTREAM_RED_PKGS"

  local pkgs
  pkgs="$(go list ./... | grep -Ev "$GO_CONTAINER_PKGS" | grep -Ev "$GO_UPSTREAM_RED_PKGS")"
  [[ -n "$pkgs" ]] || { printf 'no packages left to test\n'; return 1; }

  # shellcheck disable=SC2086
  go test -tags=tests,integration -count=1 $pkgs
}
stage_vuln()     {
  have govulncheck || return 2
  # govulncheck downloads its database at run time. If the network blocks
  # vuln.go.dev it scans NOTHING — a FAIL there would read as "vulnerabilities
  # found", which is the opposite of what happened.
  local out rc=0
  out="$(govulncheck ./... 2>&1)" || rc=$?
  printf '%s\n' "$out"
  if [[ $rc -ne 0 ]] && grep -qE "fetching vulnerabilities|vuln\.go\.dev.*(Forbidden|no such host|timeout|connection refused)" <<<"$out"; then
    printf 'the vulnerability database is unreachable — NOTHING WAS SCANNED.\n'
    printf 'Allow vuln.go.dev, or rely on CI (REQUIRE_STAGES makes this fatal there).\n'
    return 2
  fi
  return $rc
}
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

# REQUIRE_STAGES turns a SKIP into a FAIL for the named stages.
#
# Locally a SKIP is honest — a missing tool did not examine the code, and
# calling that a failure trains people to ignore red. But somewhere the checks
# have to actually run, or "SKIP" quietly becomes "never". CI sets this to the
# full list, so an unreachable vulnerability DB or an absent Docker daemon on
# the runner is fatal there instead of silently green.
if [[ -n "${REQUIRE_STAGES:-}" ]]; then
  for req in $REQUIRE_STAGES; do
    for s in "${SKIP[@]:-}"; do
      if [[ "$s" == "$req" ]]; then
        printf '%s[REQUIRED]%s stage %s was SKIPPED but REQUIRE_STAGES demands it run.\n' \
          "$RED" "$RST" "$req"
        FAIL+=("required-but-skipped:$req")
      fi
    done
  done
fi

# ---- summary -------------------------------------------------------------
printf '\n%s===== SUMMARY =====%s\n' "$BLD" "$RST"
printf '%sPASS%s: %s\n' "$GRN" "$RST" "${PASS[*]:-none}"
printf '%sSKIP%s: %s\n' "$YLW" "$RST" "${SKIP[*]:-none}"
printf '%sFAIL%s: %s\n' "$RED" "$RST" "${FAIL[*]:-none}"

if [[ "${#SKIP[@]}" -gt 0 ]]; then
  printf '\n%sWARNING:%s %d stage(s) skipped. A gate only proves what it actually ran.\n' "$YLW" "$RST" "${#SKIP[@]}"
  printf 'Install the missing tools with:  bash harden/setup.sh\n'
fi

if [[ "${#FAIL[@]}" -gt 0 ]]; then
  printf '\n%sGATE: RED%s\n' "$RED" "$RST"
  exit 1
fi
printf '\n%sGATE: GREEN%s\n' "$GRN" "$RST"
exit 0
