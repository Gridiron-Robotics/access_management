#!/usr/bin/env python3
"""Keep the govulncheck exception honest, or fail.

WHY THIS EXISTS (decision-register row O-16)
---------------------------------------------
`govulncheck` is RED — 13 reachable vulnerabilities — and the fix needs
`go.mod` edits that golden rule §1 forbids. So the RED is accepted, in writing,
in `harden/VULN-EXCEPTION.md`.

The row's own sentence is the risk: "An undocumented suspension is
indistinguishable from nobody noticing." A *documented* one decays the same way
if nothing ever re-reads it. Six months on, nobody can tell whether the list is
still the truth, whether something new appeared, or whether it was all fixed
upstream a while back.

So this compares the document against reality and fails when they disagree:

  * a vulnerability govulncheck reports that the document does NOT name — the
    exception must not silently widen to cover findings nobody accepted;
  * a vulnerability the document names that govulncheck no longer reports — the
    exception is stale and the row should close;
  * the expiry date has passed.

It is deliberately NOT an ignore list. An ignore list makes the signal quiet.
This keeps the signal loud and makes the *acceptance* auditable.

    python3 harden/check_vuln_exception.py

Exit: 0 document matches reality · 1 they disagree · 2 could not run.
Two is not zero on purpose — if govulncheck cannot reach its database it scans
NOTHING, and reporting that as agreement would be the exact defect this file
exists to prevent. `harden/verify.sh` already draws the same distinction.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DOC = _HERE / "VULN-EXCEPTION.md"

_OSV = re.compile(r"\bGO-\d{4}-\d{3,5}\b")
_EXPIRES = re.compile(r"\*\*Expires:\*\*.*?(\d{4}-\d{2}-\d{2})")


def documented_osvs(text: str) -> set[str]:
    """Only the ids inside the table rows, not prose mentions."""
    return {m.group(0) for line in text.splitlines() if line.strip().startswith("|")
            for m in _OSV.finditer(line)}


def expiry(text: str) -> _dt.date | None:
    m = _EXPIRES.search(text)
    return _dt.date.fromisoformat(m.group(1)) if m else None


def _stream_json(raw: str):
    decoder = json.JSONDecoder()
    i, n = 0, len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        obj, i = decoder.raw_decode(raw, i)
        yield obj


def reported_osvs(raw: str) -> set[str]:
    """The REACHABLE ones — a finding whose trace names a called function.

    govulncheck also reports vulnerabilities in imported-but-uncalled code.
    Those are real information but not what "your code is affected by" counts,
    and mixing them in would make this disagree with the gate.
    """
    out = set()
    for obj in _stream_json(raw):
        finding = obj.get("finding")
        if not finding:
            continue
        trace = finding.get("trace") or [{}]
        if trace[0].get("function"):
            out.add(finding["osv"])
    return out


def main() -> int:
    if not _DOC.is_file():
        print(f"UNRUN: {_DOC} is missing — there is no exception to check.")
        return 2

    text = _DOC.read_text()
    documented = documented_osvs(text)
    if not documented:
        print("UNRUN: the exception names no OSV ids — nothing to compare against.")
        return 2

    try:
        proc = subprocess.run(
            ["govulncheck", "-format", "json", "./..."],
            cwd=_HERE.parent, capture_output=True, text=True, timeout=1800,
        )
    except FileNotFoundError:
        print("UNRUN: govulncheck is not installed — nothing was scanned.")
        return 2
    except subprocess.TimeoutExpired:
        print("UNRUN: govulncheck timed out — nothing was scanned.")
        return 2

    try:
        reported = reported_osvs(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"UNRUN: could not parse govulncheck output ({exc}) — nothing was compared.")
        return 2

    if not reported:
        # Zero findings is ambiguous, so disambiguate before reporting anything.
        #
        # "Fetching vulnerabilities from the database..." is the NORMAL progress
        # line and appears on every successful run — matching on it alone made
        # this report UNRUN even when the scan had just found 13 vulnerabilities.
        # The failure signature is a database that could not be REACHED, and it
        # only means anything when nothing came back.
        unreachable = re.search(
            r"vuln\.go\.dev.*(Forbidden|no such host|timeout|connection refused)"
            r"|could not fetch|error fetching",
            (proc.stdout or "") + (proc.stderr or ""), re.I,
        )
        if unreachable:
            print("UNRUN: the vulnerability database is unreachable — NOTHING WAS SCANNED.")
            return 2
        print("UNRUN or RESOLVED: govulncheck reported no reachable vulnerabilities.")
        print("  If that is real, delete this exception and close the row.")
        print("  If the scan analysed nothing, fix that first — an empty result is not a pass.")
        return 2

    problems = []
    for osv in sorted(reported - documented):
        problems.append(f"{osv}: reported but NOT named in VULN-EXCEPTION.md — "
                        "the exception does not cover it")
    for osv in sorted(documented - reported):
        problems.append(f"{osv}: named in VULN-EXCEPTION.md but no longer reported — "
                        "the exception is stale")

    when = expiry(text)
    if when is None:
        problems.append("VULN-EXCEPTION.md has no **Expires:** date — an exception "
                        "without one is a permanent waiver")
    elif _dt.date.today() > when:
        problems.append(f"the exception expired on {when} — decide again rather than by default")

    if problems:
        for line in problems:
            print(f"  ✗ {line}")
        print(f"\nFAIL: the exception and reality disagree ({len(problems)} issue(s))")
        return 1

    print(f"OK: {len(reported)} reachable vulnerabilities, all named in the exception; "
          f"expires {when}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
