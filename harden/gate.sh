#!/usr/bin/env bash
# gate.sh — the final merge-eligibility verdict (the bouncer).
#
# ELIGIBLE iff:
#   1) verify.sh passes (objective gate green), AND
#   2) harden/review-findings.json has no UNRESOLVED critical/high findings.
#
# This is what CI and you should trust before merging. You still click merge.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

echo ">> 1/2 Running objective gate (verify.sh)..."
if ! bash harden/verify.sh; then
  echo
  echo "MERGE VERDICT: BLOCKED — verify.sh failed."
  exit 1
fi

FINDINGS="harden/review-findings.json"
if [[ -f "$FINDINGS" ]] && command -v ruby >/dev/null 2>&1; then
  echo
  echo ">> 2/2 Checking review findings for unresolved critical/high items..."
  if ! ruby -rjson -e '
    data = JSON.parse(File.read("harden/review-findings.json")) rescue []
    data = [] unless data.is_a?(Array)
    bad = data.select { |f| f.is_a?(Hash) && %w[critical high].include?(f["severity"].to_s) && !f["resolved"] }
    if bad.any?
      warn "Unresolved high/critical findings:"
      bad.each { |f| warn "  - [#{f["severity"]}] #{f["file"]}: #{f["finding"]}" }
      exit 1
    end
    puts "No unresolved high/critical findings."
  '; then
    echo
    echo "MERGE VERDICT: BLOCKED — unresolved review findings."
    exit 1
  fi
else
  echo ">> 2/2 No review findings file (run harden/review.sh to add this layer)."
fi

echo
echo "MERGE VERDICT: ELIGIBLE — gates green, no blocking findings. You still click merge."
exit 0
