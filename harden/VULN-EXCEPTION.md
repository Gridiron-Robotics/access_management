# Exception: `govulncheck` is RED, and `go.mod` stays frozen for now

**Status:** accepted, dated, and re-checked by `harden/check_vuln_exception.py`
**Recorded:** 2026-08-20 · **Closes:** estate decision-register row `O-16`
**Expires:** on the next Cerbos rebase, or **2026-11-20**, whichever comes first

## What is actually red

`govulncheck ./...` exits **3**:

> Your code is affected by **13 vulnerabilities from 3 modules and the Go
> standard library.**

It is the only RED stage; the other ten pass. Measured 2026-08-20 with
`govulncheck` against `go 1.25.11` / `toolchain go1.26.4` (`go.mod:3,5`).

## The 13, named

Naming them is the point. A suspension that says "there are some CVEs" is
indistinguishable from nobody having looked.

| OSV | CVE | Module | Fixed in |
|---|---|---|---|
| GO-2026-4970 | CVE-2026-39822 | stdlib | go1.26.5 |
| GO-2026-5856 | CVE-2026-42505 | stdlib | go1.26.5 |
| GO-2026-5026 | CVE-2026-39821 | stdlib | go1.26.6 |
| GO-2026-5972 | CVE-2026-33818 | stdlib | go1.26.6 |
| GO-2026-6088 | CVE-2026-56859 | stdlib | go1.26.6 |
| GO-2026-6089 | CVE-2026-56853 | stdlib | go1.26.6 |
| GO-2026-6090 | CVE-2026-56862 | stdlib | go1.26.6 |
| GO-2026-6091 | CVE-2026-56858 | stdlib | go1.26.6 |
| GO-2026-6218 | CVE-2026-56860 | stdlib | go1.26.6 |
| GO-2026-5970 | CVE-2026-56852 | `golang.org/x/text` v0.38.0 (indirect) | v0.39.0 |
| GO-2026-6061 | — | `google.golang.org/grpc` v1.81.1 | v1.82.1 |
| GO-2026-6213 | CVE-2026-71556 | `github.com/go-git/go-git/v6` v6.0.0-alpha.4 | v6.0.0-alpha.5 |
| GO-2026-6214 | CVE-2026-71557 | `github.com/go-git/go-git/v6` v6.0.0-alpha.4 | v6.0.0-alpha.5 |

## The split that matters — and it is not 13 against the golden rule

**Nine of the thirteen are the Go standard library**, and every one is fixed by a
**toolchain** bump to go1.26.6. That is not a dependency change: it does not
alter what upstream Cerbos depends on, only which compiler builds it. It can be
done with `GOTOOLCHAIN=go1.26.6` in the build environment and **no `go.mod` edit
at all**, or with a one-line change to the `toolchain` directive.

So the golden rule (§1 — `go.mod` is off-limits) is genuinely at stake for
**four** findings across **three** modules, not thirteen:

* `golang.org/x/text` → v0.39.0 — **indirect**, so it moves when its parent does
* `google.golang.org/grpc` → v1.82.1
* `github.com/go-git/go-git/v6` → v6.0.0-alpha.5

*Not verified here:* this environment has go1.26.4 and could not run a 1.26.6
toolchain, so the claim that the stdlib nine disappear under it rests on
`govulncheck`'s own "Fixed in" data, not on a re-scan. Re-scan when you bump.

## Why the bump is out of charter right now

Golden rule §1 exists for a real reason: `go.mod`/`go.sum` are upstream Cerbos's,
and editing them diverges the fork from a well-tested codebase on the axis where
divergence hurts most — every future rebase conflicts on the dependency graph,
and this repo's whole value is that the engine is *not ours to rewrite*.

Bumping grpc and go-git in the fork means carrying that conflict indefinitely,
to arrive at versions upstream Cerbos will itself adopt on its own schedule.
**The correct fix is upstream's, and the correct action here is to take it.**

## Do not add an ignore list

`govulncheck` has no persistent ignore mechanism in this setup, and none should
be introduced. An ignore list converts a loud, dated, re-checkable signal into a
silent one — and unlike this document, it does not expire, does not name a
revisit trigger, and does not fail when the situation changes.

## How this exception is kept honest

`harden/check_vuln_exception.py` re-runs `govulncheck` and compares the result
against the table above. It **fails** if:

* a vulnerability appears that this document does not name — the waiver does not
  silently widen to cover new findings;
* a vulnerability named here is no longer reported — the waiver is stale and the
  row should close;
* the expiry date has passed.

That is the difference between an exception and a waiver. This one has a date, a
list, and a check that argues with it.

## Revisit trigger

Whichever comes first:

1. **Cerbos publishes a release** whose `go.mod` carries the three patched
   modules → rebase onto it, bump the toolchain in the same change, re-run.
2. **2026-11-20** → if no upstream release has landed, the decision gets made
   again explicitly rather than by default.
3. **A reachable CRITICAL appears** in any of these modules → the calculus
   changes immediately; patch in-fork and accept the rebase cost.
