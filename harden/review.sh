#!/usr/bin/env bash
# review.sh — a fresh-eyes, ADVERSARIAL review by a SEPARATE Claude context.
#
# It does not trust the inner loop's self-assessment. It writes structured
# findings to harden/review-findings.json, which gate.sh then enforces.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

command -v claude >/dev/null 2>&1 || { echo "claude CLI not found — install Claude Code first."; exit 2; }

OUT="harden/review-findings.json"

REVIEW_PROMPT="$(cat <<'EOF'
You are an adversarial reviewer for the access_management repo: a Cerbos-based
authorization layer for an ERP. Review ONLY our additions:

  - policies/**          Are the access rules correct and least-privilege? Any
                         accidental allow-all? Do the *_test.yaml suites assert
                         DENY cases, not just ALLOW? Any role that can escalate?
  - deploy/kamal/**, config/deploy.yml, .kamal/**, Gemfile, deploy/charts/cerbos/**
                         Is the deploy safe: TLS at the edge, pinned versions, no
                         real secrets committed, a sane healthcheck, no admin API
                         or playground exposed in production?

Do NOT review the upstream engine (internal, api, pkg, cmd, private, schema, tools).

Write your findings as a JSON array to harden/review-findings.json. Each item:
  {"severity":"critical|high|medium|low","area":"policies|deploy",
   "file":"<path>","finding":"<what is wrong>","fix":"<what to do>","resolved":false}
If there are genuinely no issues, write []. Output ONLY by writing that file.
EOF
)"

echo "Running adversarial review (separate context)..."
claude -p "$REVIEW_PROMPT" --max-turns "${MAX_TURNS:-20}" \
  || echo "claude returned non-zero; checking for a findings file anyway."

if [[ -f "$OUT" ]]; then
  echo "Findings written to $OUT:"
  cat "$OUT"
else
  echo "No findings file produced; writing empty []."
  echo "[]" > "$OUT"
fi
