"""The exception, and the thing that argues with it.

Row O-16 warns that "an undocumented suspension is indistinguishable from
nobody noticing". A *documented* one decays the same way once nothing re-reads
it — six months on, nobody can tell whether the list is still true, whether
something new appeared, or whether upstream fixed it all a while back.

`check_vuln_exception.py` is what stops that. These tests cover the three ways
it must disagree with the document, plus the two ways it must refuse to answer.

Note the regression at the bottom: the first version of the checker treated
"Fetching vulnerabilities from the database..." — the NORMAL progress line — as
evidence the database was unreachable, so it reported UNRUN on every successful
run. An always-UNRUN check is as useless as an always-PASS one, and harder to
notice because it looks cautious.

    python3 -m pytest harden/test_vuln_exception.py
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_CHECKER = _HERE / "check_vuln_exception.py"
_DOC = _HERE / "VULN-EXCEPTION.md"


def _load():
    spec = importlib.util.spec_from_file_location("_vuln_exc", _CHECKER)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


chk = _load()


class _Proc:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


def _finding(osv, called=True):
    trace = [{"module": "stdlib", "function": "F"} if called else {"module": "stdlib"}]
    return {"finding": {"osv": osv, "trace": trace}}


def _stream(objs):
    return "\n".join(json.dumps(o, indent=2) for o in objs)


def _run(monkeypatch, objs, doc_text=None, stderr=""):
    monkeypatch.setattr(chk.subprocess, "run",
                        lambda *a, **k: _Proc(_stream(objs), stderr))
    if doc_text is not None:
        tmp = _HERE / "_tmp_exception.md"
        tmp.write_text(doc_text)
        monkeypatch.setattr(chk, "_DOC", tmp)
        try:
            return chk.main()
        finally:
            tmp.unlink(missing_ok=True)
    return chk.main()


_GOOD_DOC = """**Expires:** on the next rebase, or **2099-01-01**, whichever comes first
| GO-2026-4970 | CVE-1 | stdlib | go1.26.5 |
| GO-2026-5026 | CVE-2 | stdlib | go1.26.6 |
"""


# --------------------------------------------------------------------------- #
# Parsing the document.


def test_only_table_rows_count_as_documented():
    """Prose mentioning an id must not silently widen the exception."""
    text = "We considered GO-2026-9999 and rejected it.\n| GO-2026-4970 | x | y | z |\n"
    assert chk.documented_osvs(text) == {"GO-2026-4970"}


def test_the_real_document_names_thirteen():
    ids = chk.documented_osvs(_DOC.read_text())
    assert len(ids) == 13, f"expected the measured 13, found {len(ids)}: {sorted(ids)}"


def test_the_real_document_has_an_expiry():
    assert chk.expiry(_DOC.read_text()) is not None, (
        "no **Expires:** date — an exception without one is a permanent waiver"
    )


def test_the_expiry_is_in_the_future_as_recorded():
    when = chk.expiry(_DOC.read_text())
    assert when > _dt.date(2026, 8, 20)


# --------------------------------------------------------------------------- #
# Only REACHABLE findings count — the gate says "your code is affected by".


def test_uncalled_findings_are_not_counted():
    raw = _stream([_finding("GO-1", called=True), _finding("GO-2", called=False)])
    assert chk.reported_osvs(raw) == {"GO-1"}


# --------------------------------------------------------------------------- #
# The three disagreements.


def test_a_new_vulnerability_not_in_the_document_fails(monkeypatch):
    """The exception must not silently widen to cover findings nobody accepted."""
    objs = [_finding("GO-2026-4970"), _finding("GO-2026-5026"), _finding("GO-2026-9999")]
    assert _run(monkeypatch, objs, _GOOD_DOC) == 1


def test_a_documented_vulnerability_that_is_gone_fails(monkeypatch):
    """Stale waiver: it was fixed and the row should close."""
    objs = [_finding("GO-2026-4970")]
    assert _run(monkeypatch, objs, _GOOD_DOC) == 1


def test_an_expired_exception_fails(monkeypatch):
    doc = _GOOD_DOC.replace("2099-01-01", "2020-01-01")
    objs = [_finding("GO-2026-4970"), _finding("GO-2026-5026")]
    assert _run(monkeypatch, objs, doc) == 1


def test_a_document_with_no_expiry_fails(monkeypatch):
    doc = "| GO-2026-4970 | x | y | z |\n| GO-2026-5026 | x | y | z |\n"
    objs = [_finding("GO-2026-4970"), _finding("GO-2026-5026")]
    assert _run(monkeypatch, objs, doc) == 1


def test_an_exact_match_passes(monkeypatch):
    """The other direction — it must be satisfiable, not just strict."""
    objs = [_finding("GO-2026-4970"), _finding("GO-2026-5026")]
    assert _run(monkeypatch, objs, _GOOD_DOC) == 0


# --------------------------------------------------------------------------- #
# Refusing to answer. Exit 2, never 0.


def test_an_unreachable_database_is_UNRUN(monkeypatch):
    monkeypatch.setattr(chk.subprocess, "run",
                        lambda *a, **k: _Proc("", "vuln.go.dev: no such host"))
    tmp = _HERE / "_tmp_exception.md"; tmp.write_text(_GOOD_DOC)
    monkeypatch.setattr(chk, "_DOC", tmp)
    try:
        assert chk.main() == 2
    finally:
        tmp.unlink(missing_ok=True)


def test_a_missing_govulncheck_is_UNRUN(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(chk.subprocess, "run", boom)
    tmp = _HERE / "_tmp_exception.md"; tmp.write_text(_GOOD_DOC)
    monkeypatch.setattr(chk, "_DOC", tmp)
    try:
        assert chk.main() == 2
    finally:
        tmp.unlink(missing_ok=True)


def test_a_missing_document_is_UNRUN(monkeypatch):
    monkeypatch.setattr(chk, "_DOC", _HERE / "does-not-exist.md")
    assert chk.main() == 2


def test_zero_findings_is_UNRUN_not_a_pass(monkeypatch):
    """Clean or blind, both mean the exception must not be reaffirmed silently."""
    assert _run(monkeypatch, [], _GOOD_DOC) == 2


# --------------------------------------------------------------------------- #
# THE REGRESSION.


def test_the_normal_progress_line_is_not_read_as_unreachable(monkeypatch):
    """An always-UNRUN check is as useless as an always-PASS one.

    "Fetching vulnerabilities from the database..." is printed on every
    successful run. The first version of this checker matched it and reported
    UNRUN even when the scan had just found 13 vulnerabilities — a check that
    looks cautious and answers nothing.
    """
    objs = [_finding("GO-2026-4970"), _finding("GO-2026-5026")]
    code = _run(monkeypatch, objs, _GOOD_DOC,
                stderr="Fetching vulnerabilities from the database...\n"
                       "Checking the code against the vulnerabilities...")
    assert code == 0, "the normal progress output was mistaken for an unreachable database"


def test_the_two_zero_finding_reasons_are_reported_differently(monkeypatch, capsys):
    """Both exit 2 — but a human does opposite things with them.

    "The database was unreachable" means fix the network and re-run. "No
    reachable vulnerabilities" means the exception may be stale and the row may
    be closeable. Collapsing the two into one message is how an outage gets
    filed as good news. This is what the unreachable-signature regex is FOR:
    it changes no exit code, only which of these an operator reads.
    """
    tmp = _HERE / "_tmp_exception.md"
    tmp.write_text(_GOOD_DOC)
    monkeypatch.setattr(chk, "_DOC", tmp)
    try:
        monkeypatch.setattr(chk.subprocess, "run",
                            lambda *a, **k: _Proc("", "vuln.go.dev: no such host"))
        assert chk.main() == 2
        unreachable_msg = capsys.readouterr().out

        monkeypatch.setattr(chk.subprocess, "run",
                            lambda *a, **k: _Proc("", "Fetching vulnerabilities from the database..."))
        assert chk.main() == 2
        clean_msg = capsys.readouterr().out
    finally:
        tmp.unlink(missing_ok=True)

    assert "NOTHING WAS SCANNED" in unreachable_msg
    assert "NOTHING WAS SCANNED" not in clean_msg, (
        "a successful scan that found nothing was reported as an unreachable "
        "database — an outage filed as good news, or the reverse"
    )
    assert "RESOLVED" in clean_msg
