#!/usr/bin/env bash
# harden.sh — the INNER LOOP.
#
# Repeatedly: run the gate (verify.sh). If it's red, ask Claude Code to fix the
# POLICIES and DEPLOY CONFIG (never the upstream engine, never the gate itself),
# then re-run. Stop when the gate is green or after $ROUNDS.
#
# COSTS MONEY: every round may invoke the `claude` CLI against your account.
# The ROUNDS / MAX_TURNS caps are intentional. Start small, loosen once trusted.
#
#   ROUNDS=4 MAX_TURNS=30 bash harden/harden.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

ROUNDS="${ROUNDS:-4}"
MAX_TURNS="${MAX_TURNS:-30}"

command -v claude >/dev/null 2>&1 || { echo "claude CLI not found — install Claude Code first."; exit 2; }

FIX_PROMPT="$(cat <<'EOF'
You are hardening the access_management repository until its objective gate passes.

Run the gate with:  bash harden/verify.sh   (read the output carefully.)

Make the gate GREEN by fixing problems ONLY in:
  - policies/**                              (Cerbos YAML policies and *_test.yaml)
  - deploy/kamal/**                          (deploy Dockerfile + Cerbos config)
  - config/deploy.yml, .kamal/**, Gemfile    (Kamal deployment)
  - deploy/charts/cerbos/**                  (only if a helm-lint failure is ours)

HARD RULES — never break these:
  - NEVER modify the upstream Cerbos engine: internal/**, api/**, pkg/**, cmd/**,
    private/**, schema/**, tools/**, go.mod, go.sum, go.work.
  - NEVER modify anything under harden/ (do not edit the gate to make it pass).
  - NEVER delete a failing test, weaken a policy to allow-all, or relax a security
    check just to go green. Fix the real cause.
  - Keep every version PINNED (Cerbos image tag, kamal 2.11.0). Never use "latest".

After each change, re-run `bash harden/verify.sh` and keep going until it prints
"GATE: GREEN", or explain clearly why you are stuck.
EOF
)"

green() { bash harden/verify.sh; }

for ((i = 1; i <= ROUNDS; i++)); do
  echo "================ ROUND $i / $ROUNDS ================"
  if green; then
    echo "GATE GREEN on round $i — nothing left to fix."
    exit 0
  fi
  echo "Gate is red. Invoking Claude Code (max-turns=$MAX_TURNS)..."
  claude -p "$FIX_PROMPT" --max-turns "$MAX_TURNS" \
    || echo "claude returned non-zero; re-checking the gate anyway."
done

echo "================ FINAL CHECK ================"
if green; then
  echo "GATE GREEN."
  exit 0
fi
echo "Still red after $ROUNDS round(s). Inspect the output above and adjust."
exit 1
