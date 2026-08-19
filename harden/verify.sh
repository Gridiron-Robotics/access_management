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
# Stages: compile lint test vuln policies integration ratchet helm kamal deploy compose docker
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
# ---- the test-count ratchet ----------------------------------------------
# Running a suite and reading its exit code cannot notice a DELETED test: a
# suite with one case fewer passes exactly as green as the whole one. So the
# two suites this repo owns carry a floor in harden/.test-counts, and this
# stage RE-DERIVES the live counts and compares.
#
# Re-derives is the whole point. A stage that reads 191 out of one file and
# compares it to 191 in another proves nothing; it is a check that cannot fail.
# So every number below is derived TWICE, along paths that share no code:
#
#   policies    — what `cerbos compile` reports it executed, versus a static
#                 walk of policies/*/*_test.yaml summing each test's
#                 principals x resources x actions cross-product.
#   integration — the per-<testcase> tally of pytest's JUnit XML, versus the
#                 "N passed" line pytest writes to stdout.
#
# The two must agree with each other AND meet the floor. That is what keeps the
# counter itself from becoming the hole: a derivation nailed to a constant (or
# to 0) stops matching its partner the moment the suite changes size, and the
# stage goes red instead of waving the change through.
readonly TEST_COUNTS_FILE="harden/.test-counts"

RATCHET_FAILS=0
r_ok()  { printf '  [ok]   %s\n' "$1"; }
r_bad() { printf '  %s[FAIL]%s %s\n' "$RED" "$RST" "$1"; RATCHET_FAILS=$((RATCHET_FAILS + 1)); }

# A count is usable only if it is a positive integer. Empty, non-numeric or
# zero means that counter counted nothing — never a pass.
r_num() { [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 > 0 )); }

r_floor()      { sed -n "s/^$1=\([0-9][0-9]*\)[[:space:]]*\$/\1/p" "$TEST_COUNTS_FILE" | tail -1; }
r_allow_lower(){ sed -n "s/^allow_lower=$1:\([0-9][0-9]*\):\([0-9][0-9]*\):.*\$/\1 \2/p" "$TEST_COUNTS_FILE" | tail -1; }

# The highest value this key has ever held in git history. Editing the floor
# down is the obvious way to "fix" a red ratchet, so the floor is itself
# ratcheted. (Needs real history: CI checks out with fetch-depth 0.)
r_hist_max() {
  local key="$1" max=0 sha v
  have git && git rev-parse --git-dir >/dev/null 2>&1 || { printf '0'; return; }
  while read -r sha; do
    [[ -n "$sha" ]] || continue
    v="$(git show "$sha:$TEST_COUNTS_FILE" 2>/dev/null | sed -n "s/^$key=\([0-9][0-9]*\)[[:space:]]*\$/\1/p" | tail -1)"
    if [[ "$v" =~ ^[0-9]+$ ]] && (( 10#$v > max )); then max=$((10#$v)); fi
  done < <(git log --format=%H -- "$TEST_COUNTS_FILE" 2>/dev/null)
  printf '%s' "$max"
}

r_check() {  # <key> <label-a> <count-a> <label-b> <count-b>
  local key="$1" la="$2" a="$3" lb="$4" b="$5"
  local floor hist old new

  floor="$(r_floor "$key")"
  if ! r_num "$floor"; then
    r_bad "$key: no usable floor in $TEST_COUNTS_FILE (read '${floor:-<missing>}')"
    return
  fi

  hist="$(r_hist_max "$key")"
  if r_num "$hist" && (( floor < hist )); then
    read -r old new <<<"$(r_allow_lower "$key")"
    if [[ "${old:-}" == "$hist" && "${new:-}" == "$floor" ]]; then
      printf '  %s[RATCHET LOWERED]%s %s: floor %s -> %s by an allow_lower line in %s. Every run says so until the coverage comes back.\n' \
        "$YLW" "$RST" "$key" "$hist" "$floor" "$TEST_COUNTS_FILE"
    else
      r_bad "$key: floor LOWERED $hist -> $floor. The ratchet only moves up; restore the tests instead. A real shrink must be recorded and reviewed as: allow_lower=$key:$hist:$floor:<reason>"
      return
    fi
  fi

  r_num "$a" || { r_bad "$key: the $la count came back '${a:-<empty>}' — that counter counted nothing, which is not a pass"; return; }
  r_num "$b" || { r_bad "$key: the $lb count came back '${b:-<empty>}' — that counter counted nothing, which is not a pass"; return; }

  if (( 10#$a != 10#$b )); then
    r_bad "$key: the two derivations disagree ($la=$a, $lb=$b). One of them is not counting the suite that exists — neither number can be trusted until that is fixed."
    return
  fi
  if (( 10#$a < 10#$floor )); then
    r_bad "$key: $a tests now, floor is $floor — $((10#$floor - 10#$a)) MISSING. Tests were deleted or silenced; restore them (editing the floor down is refused)."
    return
  fi
  if (( 10#$a > 10#$floor )); then
    printf '  [note] %s: %s tests, floor is %s — raise the floor in %s so the new coverage is held too.\n' \
      "$key" "$a" "$floor" "$TEST_COUNTS_FILE"
  fi
  r_ok "$key: $a tests ($la=$a, $lb=$b) >= floor $floor"
}

stage_ratchet() {
  have go || return 2
  have python3 || return 2
  python3 -c 'import yaml, pytest' >/dev/null 2>&1 || return 2
  if [[ ! -f "$TEST_COUNTS_FILE" ]]; then
    printf '%s is missing — the ratchet has no floor to hold.\n' "$TEST_COUNTS_FILE"
    return 1
  fi

  RATCHET_FAILS=0
  local tmp; tmp="$(mktemp -d)"

  # -- policies, derivation A: what the runner says it just executed --------
  local pol_out pol_rc=0 pol_runner pol_static
  pol_out="$(go run ./cmd/cerbos compile policies/ 2>&1)" || pol_rc=$?
  if [[ $pol_rc -ne 0 ]]; then
    printf '%s\n' "$pol_out"
    r_bad "policies: the suite did not pass, so counting it proves nothing (see stage 'policies')"
  fi
  pol_runner="$(grep -oE '^[0-9]+ tests executed' <<<"$pol_out" | tail -1 | grep -oE '^[0-9]+')"

  # -- policies, derivation B: a static walk of the suite files -------------
  pol_static="$(python3 - <<'PY'
import glob, yaml

total = 0
for path in sorted(glob.glob("policies/*/*_test.yaml")):
    with open(path) as fh:
        doc = yaml.safe_load(fh) or {}
    for t in doc.get("tests") or []:
        if t.get("skip"):
            continue
        i = t.get("input") or {}
        total += (len(i.get("principals") or [])
                  * len(i.get("resources") or [])
                  * len(i.get("actions") or []))
print(total)
PY
  )" || pol_static=""
  r_check policies runner "$pol_runner" suite-files "$pol_static"

  # -- integration: one run, two independent readings of it -----------------
  local pyt_out pyt_rc=0 pyt_stdout_pass pyt_xml pyt_xml_pass pyt_xml_total pyt_collected
  pyt_out="$(python3 -m pytest integration/tests -q --junitxml="$tmp/junit.xml" 2>&1)" || pyt_rc=$?
  if [[ $pyt_rc -ne 0 ]]; then
    printf '%s\n' "$pyt_out"
    r_bad "integration: the suite did not pass, so counting it proves nothing (see stage 'integration')"
  fi
  pyt_stdout_pass="$(grep -oE '[0-9]+ passed' <<<"$pyt_out" | tail -1 | grep -oE '^[0-9]+')"
  pyt_xml="$(python3 - "$tmp/junit.xml" <<'PY'
import sys, xml.etree.ElementTree as ET

try:
    root = ET.parse(sys.argv[1]).getroot()
except Exception:
    print("0 0")
    raise SystemExit(0)
passed = total = 0
for case in root.iter("testcase"):
    total += 1
    if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
        continue
    passed += 1
print(passed, total)
PY
  )" || pyt_xml=""
  read -r pyt_xml_pass pyt_xml_total <<<"$pyt_xml"
  r_check integration junit-xml "${pyt_xml_pass:-}" pytest-stdout "${pyt_stdout_pass:-}"

  # Collection is the third leg: every test pytest found has to be accounted
  # for by the run, so a test cannot vanish between collection and reporting.
  pyt_collected="$(python3 -m pytest integration/tests -q --collect-only 2>/dev/null \
    | grep -oE '^[0-9]+ tests? collected' | tail -1 | grep -oE '^[0-9]+')"
  if r_num "${pyt_collected:-}" && r_num "${pyt_xml_total:-}"; then
    if (( 10#$pyt_xml_total != 10#$pyt_collected )); then
      r_bad "integration: pytest collected $pyt_collected tests but the run recorded $pyt_xml_total"
    else
      r_ok "integration: all $pyt_collected collected tests were recorded ($(( 10#$pyt_xml_total - 10#${pyt_xml_pass:-0} )) skipped, not counted toward the floor)"
    fi
  else
    r_bad "integration: could not derive the collected count (collected='${pyt_collected:-<empty>}', recorded='${pyt_xml_total:-<empty>}')"
  fi

  rm -rf "$tmp"
  (( RATCHET_FAILS == 0 ))
}

# `helm lint deploy/charts/cerbos` renders with DEFAULT values, and mcp.enabled
# defaults to false — so on its own it never touches a single line of the MCP
# sidecar templates. Measured: deleting mcp-deployment.yaml, or the render-time
# `fail` that demands mcp.existingSecret, left this stage green. The lint stays
# (it checks the chart as upstream ships it); the guard checks are what make the
# stage able to notice our half of the chart disappearing.
stage_helm()     {
  have helm || return 2
  helm lint deploy/charts/cerbos || return 1
  bash harden/check_deploy_guards.sh helm
}

# The deploy-time refusals. See harden/check_deploy_guards.sh for why these are
# separate stages: a guard that nothing executes is a comment, and every one of
# these was a comment until it was measured.
stage_deploy()   { bash harden/check_deploy_guards.sh hook; }
stage_compose()  { have docker || return 2; bash harden/check_deploy_guards.sh compose; }
stage_kamal()    {
  if have kamal; then kamal config
  elif have bundle && [[ -f Gemfile ]] && bundle exec kamal version >/dev/null 2>&1; then bundle exec kamal config
  elif have ruby; then ruby harden/validate_kamal.rb
  else return 2; fi
}
stage_docker()   { have docker || return 2; docker build -f deploy/kamal/Dockerfile -t access-management:verify .; }

# ---- select & run --------------------------------------------------------
if [[ "${FAST:-0}" == "1" ]]; then
  STAGES="${STAGES:-policies integration ratchet kamal helm deploy compose}"
else
  STAGES="${STAGES:-compile lint test vuln policies integration ratchet helm kamal deploy compose}"
fi

for s in $STAGES; do
  case "$s" in
    compile)  run_stage compile  stage_compile  ;;
    lint)     run_stage lint     stage_lint     ;;
    test)     run_stage test     stage_test     ;;
    vuln)     run_stage vuln     stage_vuln     ;;
    policies) run_stage policies stage_policies ;;
    integration) run_stage integration stage_integration ;;
    ratchet)  run_stage ratchet  stage_ratchet  ;;
    helm)     run_stage helm     stage_helm     ;;
    kamal)    run_stage kamal    stage_kamal    ;;
    deploy)   run_stage deploy   stage_deploy   ;;
    compose)  run_stage compose  stage_compose  ;;
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
