#!/usr/bin/env bash
# check_deploy_guards.sh — run the deploy-time REFUSALS and prove they refuse.
#
# WHY THIS EXISTS
# ---------------
# The deploy surface ships three guards that are supposed to stop a broken or
# unauthenticated deploy:
#
#   1. `.kamal/hooks/pre-deploy` blocks while config/deploy.yml still carries
#      `<-- CHANGE` placeholders on real config lines.
#   2. `docker-compose.mcp.yml` interpolates ACCESS_MCP_TOKEN with the `:?` form
#      so `docker compose` fails rather than handing the container an empty
#      bearer.
#   3. The Helm chart `fail`s at render time when `mcp.enabled` is set without
#      `mcp.existingSecret`, rather than shipping a pod that CrashLoopBackOffs.
#
# None of them was executed by the gate. Measured, five mutations survived a
# full `verify.sh` run and left it GREEN: deleting the placeholder block from
# the hook, downgrading `${ACCESS_MCP_TOKEN:?}` to `${ACCESS_MCP_TOKEN:-}`,
# deleting the Helm fail-guard, deleting mcp-deployment.yaml, and deleting
# docker-compose.mcp.yml outright. A guard nothing runs is a comment.
#
# So this script runs each refusal in BOTH directions — it must refuse the bad
# input and it must NOT refuse the good one. A guard that only ever says no is
# as broken as one that only ever says yes; it just fails later, when someone
# deletes it to unblock a deploy.
#
# Usage:  bash harden/check_deploy_guards.sh {hook|compose|helm}
# Exit:   0 all checks passed, 1 a guard did not behave, 2 required tool absent.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

FAILS=0
ok()  { printf '  [ok]   %s\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; FAILS=$((FAILS + 1)); }

# A sandbox holding just the files the hook reads, so a check never edits the
# repo's own config/deploy.yml.
#
# `harden/verify.sh` inside the sandbox is a STUB that prints a marker and
# exits 0. That is deliberate and it is not a hole: the hook's second half
# (compile the policies) is already run for real by `stage_policies`, and
# re-running it here would only make this script slow. What the stub buys is
# the ability to tell the two halves apart — the marker in the output is proof
# the hook reached the policy step, which is exactly what the placeholder guard
# is supposed to prevent when the config is unfilled.
new_sandbox() {  # <dst-var-name>
  local dir
  dir="$(mktemp -d)"
  mkdir -p "$dir/config" "$dir/harden"
  cat >"$dir/harden/verify.sh" <<'STUB'
#!/usr/bin/env bash
echo "STUB-VERIFY-REACHED stages=${STAGES:-<unset>}"
exit 0
STUB
  printf '%s' "$dir"
}

# ---------------------------------------------------------------------------
# 1. The Kamal pre-deploy hook: unfilled placeholders must block the deploy.
# ---------------------------------------------------------------------------
check_hook() {
  local hook="$ROOT/.kamal/hooks/pre-deploy"
  [[ -f "$hook" ]] || { bad "missing $hook (the deploy has no placeholder guard at all)"; return; }

  # The repo ships config/deploy.yml as a TEMPLATE on purpose, so it must still
  # contain the markers. If someone fills them in-repo, every check below turns
  # vacuous — catch that here rather than reporting a green that proved nothing.
  if ! grep -q -- '<-- CHANGE' config/deploy.yml; then
    bad "config/deploy.yml no longer contains any '<-- CHANGE' marker — this check would be testing nothing"
    return
  fi

  local dir out rc
  dir="$(new_sandbox)"

  # (a) placeholders present -> refuse, and say which lines.
  cp config/deploy.yml "$dir/config/deploy.yml"
  out="$(cd "$dir" && bash "$hook" 2>&1)"; rc=$?
  if [[ $rc -eq 0 ]]; then
    bad "pre-deploy hook ALLOWED a deploy while config/deploy.yml still had placeholders"
  else
    ok "pre-deploy hook blocks an unfilled config/deploy.yml (exit $rc)"
  fi
  if grep -q 'unfilled placeholders' <<<"$out"; then
    ok "the refusal says what is wrong"
  else
    bad "the hook refused without naming the problem; output was: $out"
  fi
  # The offending lines must be echoed, or the operator has to go hunting.
  if grep -qE '^[0-9]+:' <<<"$out"; then
    ok "the refusal names the offending line numbers"
  else
    bad "the refusal did not list the offending lines: $out"
  fi
  # It must refuse BEFORE doing the expensive work, not after.
  if grep -q 'STUB-VERIFY-REACHED' <<<"$out"; then
    bad "the hook ran the policy gate anyway — the placeholder guard is not blocking"
  else
    ok "the refusal short-circuits before the policy gate"
  fi

  # (b) a filled config must pass, and must still run the policy gate.
  sed 's/<-- CHANGE.*//' config/deploy.yml >"$dir/config/deploy.yml"
  out="$(cd "$dir" && bash "$hook" 2>&1)"; rc=$?
  if [[ $rc -ne 0 ]]; then
    bad "pre-deploy hook BLOCKED a fully-filled config/deploy.yml (exit $rc): $out"
  else
    ok "pre-deploy hook lets a filled config/deploy.yml through"
  fi
  if grep -q 'STUB-VERIFY-REACHED stages=policies' <<<"$out"; then
    ok "the hook still gates the deploy on the policy suite"
  else
    bad "the hook no longer runs 'STAGES=policies verify.sh' — a broken access-rule set could deploy: $out"
  fi

  # (c) a placeholder marker inside a COMMENT is not a reason to block.
  # Without this the guard would fire on its own documentation, and the first
  # person to hit that would 'fix' it by deleting the guard.
  {
    sed 's/<-- CHANGE.*//' config/deploy.yml
    printf '# registry: your-org   <-- CHANGE this comment is documentation, not config\n'
  } >"$dir/config/deploy.yml"
  out="$(cd "$dir" && bash "$hook" 2>&1)"; rc=$?
  if [[ $rc -ne 0 ]]; then
    bad "pre-deploy hook blocked on a '<-- CHANGE' marker that was inside a comment: $out"
  else
    ok "pre-deploy hook ignores placeholder markers in comments"
  fi

  rm -rf "$dir"
  return 0
}

# ---------------------------------------------------------------------------
# 2. docker-compose.mcp.yml: no bearer, no start.
# ---------------------------------------------------------------------------
check_compose() {
  command -v docker >/dev/null 2>&1 || return 2
  local file="docker-compose.mcp.yml"
  # `docker compose config` interpolates and validates WITHOUT a daemon, so this
  # runs anywhere the CLI is installed.
  docker compose version >/dev/null 2>&1 || return 2

  if [[ ! -f "$file" ]]; then
    bad "missing $file — the Contract-A sidecar has no runnable definition"
    return 0
  fi

  local out rc
  # (a) unset bearer -> compose must refuse to produce a config at all.
  out="$(env -u ACCESS_MCP_TOKEN docker compose -f "$file" config 2>&1)"; rc=$?
  if [[ $rc -eq 0 ]]; then
    bad "$file produced a config with ACCESS_MCP_TOKEN unset — the container would get an empty bearer"
  else
    ok "$file refuses to render without ACCESS_MCP_TOKEN (exit $rc)"
  fi
  if grep -q 'ACCESS_MCP_TOKEN' <<<"$out"; then
    ok "the refusal names the missing variable"
  else
    bad "the refusal did not name ACCESS_MCP_TOKEN: $out"
  fi

  # (b) with the bearer -> it must parse, and it must still be the surface the
  #     agent platform binds. The service name IS the API: langgraph-agents
  #     resolves http://access-management-mcp:8085 by DNS.
  local sentinel="gate-sentinel-9d1f"
  out="$(ACCESS_MCP_TOKEN="$sentinel" docker compose -f "$file" config 2>&1)"; rc=$?
  if [[ $rc -ne 0 ]]; then
    bad "$file does not parse even with ACCESS_MCP_TOKEN set: $out"
    return 0
  fi
  ok "$file parses with the bearer set"

  grep -q 'access-management-mcp' <<<"$out" \
    && ok "the service keeps the contract name access-management-mcp" \
    || bad "the compose service is no longer named access-management-mcp — the consumer's DNS binding breaks"
  grep -qE '(^|[^0-9])8085' <<<"$out" \
    && ok "the sidecar still listens on the contract port 8085" \
    || bad "port 8085 is gone from $file — Contract-A fixes it at 8085"
  grep -q "$sentinel" <<<"$out" \
    && ok "ACCESS_MCP_TOKEN comes from the environment, not a baked-in default" \
    || bad "the rendered ACCESS_MCP_TOKEN is not the value we exported — something is defaulting it"
  grep -qE 'image:.*:latest' <<<"$out" \
    && bad "$file references a :latest image — an unreproducible deploy" \
    || ok "no :latest image in $file"
  return 0
}

# ---------------------------------------------------------------------------
# 3. Helm: the MCP sidecar must not render without its Secret.
# ---------------------------------------------------------------------------
check_helm() {
  command -v helm >/dev/null 2>&1 || return 2
  local chart="deploy/charts/cerbos"
  local vals="$chart/values-mcp.yaml"
  local out rc

  # (a) default render stays byte-identical to upstream: no MCP objects at all.
  out="$(helm template gate "$chart" 2>&1)"; rc=$?
  if [[ $rc -ne 0 ]]; then
    bad "the default chart render failed: $out"
  elif grep -q 'access-management-mcp' <<<"$out"; then
    bad "the MCP sidecar renders with default values — it is supposed to be opt-in"
  else
    ok "default render contains no MCP objects (opt-in preserved)"
  fi

  [[ -f "$vals" ]] || { bad "missing $vals — nothing documents or exercises the enabled path"; return 0; }

  # (b) enabled render must actually ship the Contract-A surface.
  helm lint -f "$vals" "$chart" >/dev/null 2>&1 \
    && ok "helm lint passes with $vals" \
    || bad "helm lint FAILS with $vals"

  out="$(helm template gate "$chart" -f "$vals" 2>&1)"; rc=$?
  if [[ $rc -ne 0 ]]; then
    bad "the MCP-enabled render failed: $out"
    return 0
  fi
  grep -q 'name: access-management-mcp' <<<"$out" \
    && ok "renders the Service named access-management-mcp (the name the agent platform resolves)" \
    || bad "no Service named access-management-mcp in the MCP-enabled render"
  grep -qE 'containerPort: 8085' <<<"$out" \
    && ok "the sidecar container listens on 8085" \
    || bad "no containerPort 8085 in the MCP-enabled render"
  grep -q 'component: mcp' <<<"$out" \
    && ok "the sidecar carries its own component label" \
    || bad "the MCP Deployment/Service is missing from the render"

  # The bearer must arrive by secretKeyRef and never as a literal in the
  # rendered pod spec — a rendered manifest ends up in git, CI logs, and
  # `kubectl get deploy -o yaml` for anyone with read access.
  if grep -A3 'name: ACCESS_MCP_TOKEN' <<<"$out" | grep -q 'secretKeyRef'; then
    ok "ACCESS_MCP_TOKEN is injected via secretKeyRef"
  else
    bad "ACCESS_MCP_TOKEN is not sourced from a Secret in the rendered manifest"
  fi
  if grep -A1 'name: ACCESS_MCP_TOKEN' <<<"$out" | grep -qE '^\s+value:'; then
    bad "ACCESS_MCP_TOKEN appears as a literal value in the rendered manifest"
  else
    ok "no literal token value in the rendered manifest"
  fi

  # The two Services must not select each other's pods, or the PDP Service can
  # front the MCP sidecar (a 405 storm) and vice versa.
  local pdp_sel mcp_sel
  selector_of() {  # <template> -> the selector's label lines, normalised
    helm template gate "$chart" -f "$vals" -s "$1" 2>/dev/null \
      | awk '/^  selector:/{inside=1; next} inside && /^    /{print $0; next} inside{exit}' \
      | tr -d ' ' | sort | paste -sd,
  }
  pdp_sel="$(selector_of templates/service.yaml)"
  mcp_sel="$(selector_of templates/mcp-service.yaml)"
  if [[ -z "$pdp_sel" || -z "$mcp_sel" ]]; then
    # An empty extraction would make the comparison below pass no matter what.
    bad "could not read both Service selectors (pdp='$pdp_sel' mcp='$mcp_sel')"
  elif [[ "$pdp_sel" == "$mcp_sel" ]]; then
    bad "the PDP and MCP Services share a selector ($pdp_sel) — each would front the other's pods"
  else
    ok "the PDP and MCP Services have distinct selectors"
  fi

  # (c) enabled WITHOUT a Secret must fail at render, not at CrashLoopBackOff.
  out="$(helm template gate "$chart" --set mcp.enabled=true --set-string mcp.existingSecret= \
        --set-string mcp.image.repository=example/mcp --set-string mcp.image.tag=0.0.1 2>&1)"; rc=$?
  if [[ $rc -eq 0 ]]; then
    bad "the chart rendered an MCP sidecar with no Secret for ACCESS_MCP_TOKEN — it would crash-loop in the cluster"
  else
    ok "the chart refuses to render an MCP sidecar without mcp.existingSecret (exit $rc)"
  fi
  grep -q 'existingSecret' <<<"$out" \
    && ok "the render failure names existingSecret" \
    || bad "the render failed without explaining that existingSecret is required: $out"
  return 0
}

# ---------------------------------------------------------------------------
case "${1:-}" in
  hook)    check_hook ;;
  compose) check_compose || exit $? ;;
  helm)    check_helm    || exit $? ;;
  *) printf 'usage: %s {hook|compose|helm}\n' "$0" >&2; exit 2 ;;
esac

if [[ $FAILS -gt 0 ]]; then
  printf '\n%d deploy guard check(s) failed.\n' "$FAILS"
  exit 1
fi
exit 0
