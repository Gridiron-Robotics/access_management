#!/usr/bin/env bash
# setup.sh — install the tools harden/verify.sh needs, so stages RUN instead of SKIP.
#
# A SKIP is not a pass. Every skipped stage is a check nobody performed, and the
# summary says so out loud. This script exists so "the tool isn't installed" is a
# five-minute fix rather than a permanent hole in the gate.
#
#   bash harden/setup.sh          # everything that can be installed here
#   bash harden/setup.sh lint     # just one
#
# Tools: lint (golangci-lint) · vuln (govulncheck) · helm · integration (python deps)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

have() { command -v "$1" >/dev/null 2>&1; }
BIN="${BIN:-/usr/local/bin}"

# The toolchain go.mod pins. golangci-lint MUST be built with at least this, or
# it cannot load .golangci.yaml and silently lints nothing.
go_toolchain() {
  awk '/^toolchain /{print $2; exit}' go.mod || true
}

setup_lint() {
  local want; want="$(go_toolchain)"
  [[ -n "$want" ]] || { echo "no toolchain directive in go.mod"; return 1; }

  if have golangci-lint && golangci-lint version 2>/dev/null | grep -q "built with ${want#go}"; then
    echo "golangci-lint already built with $want"
    return 0
  fi

  # Version pinned deliberately (repo rule 3). Bump it in one reviewable commit.
  local ver="v2.5.0"
  local src="${TMPDIR:-/tmp}/golangci-lint-src"

  echo "building golangci-lint $ver with $want (installed default is $(go env GOVERSION))"
  echo "NOTE: 'go install' will NOT work here — it honours golangci-lint's own"
  echo "      toolchain directive and produces a binary built with an older Go."

  rm -rf "$src"
  git clone --quiet --depth 1 --branch "$ver" \
    https://github.com/golangci/golangci-lint "$src" || return 1

  ( cd "$src" && GOTOOLCHAIN="$want" go build -o "$BIN/golangci-lint" ./cmd/golangci-lint ) || return 1

  golangci-lint --version
}

setup_vuln() {
  have govulncheck && { echo "govulncheck present"; return 0; }
  GOTOOLCHAIN="$(go_toolchain)" go install golang.org/x/vuln/cmd/govulncheck@v1.1.4 || return 1
  install -m 0755 "$(go env GOPATH)/bin/govulncheck" "$BIN/govulncheck"
  govulncheck -version | head -2
}

setup_helm() {
  have helm && { echo "helm present"; return 0; }
  local ver="v3.16.4" tmp
  tmp="$(mktemp -d)"
  curl -fsSL "https://get.helm.sh/helm-${ver}-linux-amd64.tar.gz" \
    | tar -xz -C "$tmp" || return 1
  install -m 0755 "$tmp/linux-amd64/helm" "$BIN/helm"
  rm -rf "$tmp"
  helm version --short
}

setup_integration() {
  python3 -m pip install --quiet --disable-pip-version-check \
    -r integration/requirements.txt || return 1
  python3 -c 'import fastapi, pytest, opentelemetry.sdk; print("integration deps ok")'
}

targets=("$@")
[[ ${#targets[@]} -gt 0 ]] || targets=(lint vuln helm integration)

rc=0
for t in "${targets[@]}"; do
  printf '\n== setup: %s ==\n' "$t"
  case "$t" in
    lint)        setup_lint        || { echo "FAILED: $t"; rc=1; } ;;
    vuln)        setup_vuln        || { echo "FAILED: $t"; rc=1; } ;;
    helm)        setup_helm        || { echo "FAILED: $t"; rc=1; } ;;
    integration) setup_integration || { echo "FAILED: $t"; rc=1; } ;;
    *) echo "unknown target: $t"; rc=1 ;;
  esac
done

printf '\nNow run: bash harden/verify.sh\n'
exit $rc
