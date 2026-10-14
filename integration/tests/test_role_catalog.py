"""The access page's catalog: one source, two copies, every key backed by a rule.

`role-catalog.yaml` is the contract; `cerbos_access/catalog.py` is the copy the
Horilla page renders (embedded so Horilla needs no YAML parser). They had
already drifted — the Python copy was missing seven modules — so the page
offered a different menu from the one the contract describes. And a role key
with no policy behind it is a toggle that grants nothing.
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from integration.horilla.cerbos_access import catalog  # noqa: E402
from integration.horilla.cerbos_access import principal  # noqa: E402

CATALOG_YAML = ROOT / "integration" / "role-catalog.yaml"


def _yaml():
    return yaml.safe_load(CATALOG_YAML.read_text())


def _policy_role_names():
    names = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("roles", "parentRoles") and isinstance(value, list):
                    names.update(v for v in value if isinstance(v, str))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in glob.glob(str(ROOT / "policies" / "**" / "*.yaml"), recursive=True):
        if path.endswith("_test.yaml"):
            continue
        for doc in yaml.safe_load_all(Path(path).read_text()):
            walk(doc)
    return names


def test_python_catalog_mirrors_the_yaml_exactly():
    data = _yaml()
    assert catalog.BASELINE_ROLES == data["baseline_roles"]
    assert catalog.GLOBAL_ROLES == data["global_roles"]
    assert catalog.MODULES == data["modules"]


def test_every_catalog_role_exists_in_a_policy():
    missing = sorted(catalog.all_role_keys() - _policy_role_names())
    assert missing == [], f"catalog roles with no policy rule: {missing}"


def test_each_gateway_role_is_a_token_role_in_its_module():
    where = {r["key"]: (m["key"], r) for m in catalog.MODULES for r in m["roles"]}
    assert where["ops"][0] == "operations"
    assert where["hr"][0] == "hr"
    assert where["warehouse"][0] == "inventory"
    assert where["external_auditor"][0] == "external"
    for key in ("ops", "hr", "warehouse", "external_auditor"):
        assert where[key][1]["keycloak_realm_role"] is True


def test_external_auditor_cannot_be_mistaken_for_staff_access():
    module = next(m for m in catalog.MODULES if m["key"] == "external")
    role = module["roles"][0]
    assert "NOT staff" in module["label"]
    assert "NOT staff" in role["label"] and "read-only" in role["label"].lower()
    assert role["external"] is True


def test_token_role_flags_are_booleans_only():
    for m in _yaml()["modules"]:
        for r in m["roles"]:
            for flag in ("keycloak_realm_role", "external"):
                if flag in r:
                    assert r[flag] is True, (r["key"], flag)


# -- principal: an outside party does not pick up the staff baseline --------

def _employee(roles, active=True):
    return SimpleNamespace(
        pk=9,
        is_active=active,
        employee_user_id=SimpleNamespace(username="aud"),
        cerbos_access=SimpleNamespace(roles=roles),
    )


def test_external_only_principal_gets_no_employee_baseline():
    assert principal.build_principal(_employee(["external_auditor"]))["roles"] == ["external_auditor"]


def test_staff_principal_still_gets_the_baseline():
    assert principal.build_principal(_employee(["ops"]))["roles"] == ["ops", "employee"]
    assert principal.build_principal(_employee([]))["roles"] == ["employee"]


def test_staff_who_also_audits_keeps_the_baseline():
    roles = principal.build_principal(_employee(["external_auditor", "accountant"]))["roles"]
    assert roles == ["external_auditor", "accountant", "employee"]
