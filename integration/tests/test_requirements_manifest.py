"""The manifest must declare everything the integration layer imports.

WHY THIS TEST EXISTS
--------------------
`integration/requirements.txt` is what `deploy/mcp/Dockerfile` installs. The
gate, meanwhile, runs against whatever happens to be on the machine. When those
two disagree the gate is green and the shipped container is broken — and the
failure is quiet, because the imports that matter most here sit inside
`try/except` blocks in `gridiron_otel.py` so the process still boots.

Measured instance: `opentelemetry.instrumentation.httpx` was imported by
`setup_observability()` and absent from the manifest. The container would come
up, report `httpx: False`, and lose outbound trace propagation — the thing the
self-heal loop uses to keep one incident on one trace id — with nothing red
anywhere.

So: every distribution the layer imports must be pinned in the manifest, and
pinned with `==`. A floating range would let a fresh image build pull a
different major and change the fail-closed behaviour these versions were
verified against (repo rule 3).

`integration/horilla/**` is deliberately out of scope: that app is installed
into Horilla's own virtualenv and its dependencies (Django, employee models)
are Horilla's to declare, not ours.
"""

from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "integration" / "requirements.txt"

# The code the MCP container runs, plus the tests the gate runs.
SCANNED_DIRS = ("integration/mcp", "integration/erp", "integration/tests")

# Modules that ship with Python, or that are this repo's own.
LOCAL_MODULES = {"integration", "gridiron_otel", "pdp_contract", "server", "cerbos_erp"}


def _imported_modules() -> tuple[set[str], set[str]]:
    """Modules named in import statements, split into two kinds.

    `certain` — written as a module by the import itself (`import x`,
    `from x.y import ...`). If one of these will not resolve, a dependency is
    genuinely missing and that is a failure.

    `possible` — the name half of `from x import y`, which may be a submodule
    (`from opentelemetry import trace`) or may be a class (`from fastapi import
    FastAPI`). They matter because a namespace package like `opentelemetry`
    belongs to no distribution, so only the submodule carries the real check.
    The ones that turn out to be classes simply do not resolve, and are skipped.
    """
    certain: set[str] = set()
    possible: set[str] = set()
    for rel in SCANNED_DIRS:
        for path in sorted((ROOT / rel).glob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    certain.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    # level > 0 is a relative import — ours by definition.
                    if node.level == 0 and node.module:
                        certain.add(node.module)
                        possible.update(f"{node.module}.{a.name}" for a in node.names)

    def keep(names: set[str]) -> set[str]:
        return {
            m
            for m in names
            if m.split(".")[0] not in LOCAL_MODULES
            and m.split(".")[0] not in sys.stdlib_module_names
        }

    return keep(certain), keep(possible)


# A namespace package (`opentelemetry`) is provided by no single distribution;
# the submodule candidates recorded above carry the real check.
NAMESPACE = "<namespace>"
# A `from x import SomeClass` candidate that is not a module at all.
NOT_A_MODULE = "<not-a-module>"


def _distribution_for(module: str) -> str | None:
    """Which installed distribution provides `module`?

    Resolved by file, not by name: `opentelemetry.instrumentation.httpx` and
    `opentelemetry.sdk.trace` share a top-level name but come from different
    packages, and it is exactly that distinction the manifest has to get right.
    """
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError, AttributeError):
        return NOT_A_MODULE
    if spec is None:
        return None
    if not spec.origin:
        return NAMESPACE if spec.submodule_search_locations else None

    origin = Path(spec.origin).resolve()
    for dist in importlib.metadata.distributions():
        try:
            base = Path(dist.locate_file("")).resolve()
            rel = origin.relative_to(base).as_posix()
        except (ValueError, OSError):
            continue
        for recorded in dist.files or []:
            if recorded.as_posix() == rel:
                return dist.metadata["Name"]
    return None


def _pinned() -> dict[str, str]:
    """{normalised distribution name: exact version} from the manifest."""
    pins: dict[str, str] = {}
    for line in MANIFEST.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, sep, version = line.partition("==")
        pins[re.sub(r"[-_.]+", "-", name.strip()).lower()] = version.strip() if sep else ""
    return pins


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


CERTAIN, POSSIBLE = _imported_modules()
IMPORTED = sorted(CERTAIN | POSSIBLE)


def test_the_scan_actually_resolves_real_distributions():
    """
    Anti-vacuity guard. The parametrised test below skips candidates that are
    classes rather than modules, so a scan that resolved nothing would skip
    everything and still report green. Name the distributions that must come
    out of it.
    """
    resolved = {
        _distribution_for(m)
        for m in IMPORTED
        if _distribution_for(m) not in (None, NAMESPACE, NOT_A_MODULE)
    }
    resolved = {_normalise(d) for d in resolved}

    for expected in ("fastapi", "requests", "opentelemetry-api", "opentelemetry-sdk"):
        assert expected in resolved, f"the import scan never resolved {expected!r}: {sorted(resolved)}"
    # The OTel instrumentation packages are the ones that went missing before.
    assert any(d.startswith("opentelemetry-instrumentation") for d in resolved), (
        f"no opentelemetry-instrumentation distribution was resolved: {sorted(resolved)}"
    )


@pytest.mark.parametrize("module", IMPORTED)
def test_every_imported_distribution_is_pinned_in_the_manifest(module):
    dist = _distribution_for(module)
    if dist in (NAMESPACE, NOT_A_MODULE):
        pytest.skip(f"{module!r} is {dist}, not something a manifest can pin")
    if dist is None:
        if module not in CERTAIN:
            # `from fastapi import FastAPI` — a class, not a submodule.
            pytest.skip(f"{module!r} is a name inside a module, not a module")
        pytest.fail(
            f"{module!r} is imported by the integration layer but is not installed here, "
            "so the gate cannot prove the manifest covers it. Install it and pin it."
        )

    pins = _pinned()
    key = _normalise(dist)
    assert key in pins, (
        f"{module!r} comes from the {dist!r} distribution, which is missing from "
        f"{MANIFEST.relative_to(ROOT)}. deploy/mcp/Dockerfile installs only that file, "
        "so the shipped container would not have it."
    )
    assert pins[key], (
        f"{dist!r} is listed in {MANIFEST.relative_to(ROOT)} without an exact '==' pin. "
        "A floating range lets a fresh image build pull a different major (repo rule 3)."
    )


def test_the_manifest_pins_every_line_exactly():
    """No `>=`, `~=`, or bare names anywhere in the manifest."""
    loose = []
    for raw in MANIFEST.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "==" not in line:
            loose.append(line)
    assert not loose, f"unpinned requirement(s): {loose}"
