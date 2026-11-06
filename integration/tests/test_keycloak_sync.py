"""The access page's assignments reach the Keycloak token — and nothing else does.

`cerbos_access/keycloak_sync.py` is what turns ticking `ops` on the access page
into the `ops` realm role in the user's token (which the ERP middleware reads as
the OPS scope). These tests drive it against a faked Keycloak admin REST API,
at the HTTP level, so the real request paths, the diff and the guard that it
only ever touches catalog token roles are all exercised.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integration.horilla.cerbos_access import catalog  # noqa: E402
from integration.horilla.cerbos_access import keycloak_sync as ks  # noqa: E402

BASE = "https://sso.test"
SECRET = "s3cret-value-that-must-never-be-logged"
ENV = {
    "KEYCLOAK_ADMIN_URL": BASE + "/",
    "KEYCLOAK_ADMIN_CLIENT_ID": "access-sync",
    "KEYCLOAK_ADMIN_CLIENT_SECRET": SECRET,
}
TOKEN = "tok-123"


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeKeycloak:
    """Just enough of the Keycloak admin REST API for the sync, realm `erp`."""

    def __init__(self, users, realm_roles, fail_on=None):
        # users: {id: {"email": str, "roles": set}}
        self.users = users
        self.realm_roles = set(realm_roles)
        self.fail_on = fail_on  # (method, path-substring) -> HTTP 500
        self.calls = []

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "DELETE") and "/admin/" in c[1]]

    def request(self, method, url, timeout=None, headers=None, params=None, data=None, json=None):
        assert timeout, "every Keycloak call must carry a timeout"
        path = urlparse(url).path
        self.calls.append((method, path, params, json))
        if self.fail_on and method == self.fail_on[0] and self.fail_on[1] in path:
            return _Resp(500, {"error": "boom"})
        if path == "/realms/erp/protocol/openid-connect/token":
            assert method == "POST" and data["grant_type"] == "client_credentials"
            assert data["client_secret"] == SECRET
            return _Resp(200, {"access_token": TOKEN})
        assert headers == {"Authorization": f"Bearer {TOKEN}"}, path
        prefix = "/admin/realms/erp"
        assert path.startswith(prefix), path
        rest = path[len(prefix):].split("/")[1:]
        if rest == ["users"] and method == "GET":
            assert params["exact"] == "true"
            return _Resp(200, [{"id": uid, "email": u["email"]}
                               for uid, u in self.users.items()
                               if u["email"].lower() == params["email"].lower()])
        if len(rest) == 4 and rest[0] == "users" and rest[2:] == ["role-mappings", "realm"]:
            user = self.users[rest[1]]
            if method == "GET":
                return _Resp(200, [{"id": f"rid-{n}", "name": n} for n in sorted(user["roles"])])
            names = {r["name"] for r in json}
            assert all(r["id"] == f"rid-{r['name']}" for r in json)
            if method == "POST":
                user["roles"] |= names
            else:
                user["roles"] -= names
            return _Resp(204)
        if len(rest) == 2 and rest[0] == "roles" and method == "GET":
            name = rest[1]
            if name not in self.realm_roles:
                return _Resp(404, {"error": "Could not find role"})
            return _Resp(200, {"id": f"rid-{name}", "name": name})
        if len(rest) == 3 and rest[0] == "roles" and rest[2] == "users":
            first, size = int(params["first"]), int(params["max"])
            holders = sorted(uid for uid, u in self.users.items() if rest[1] in u["roles"])
            return _Resp(200, [{"id": uid} for uid in holders[first:first + size]])
        raise AssertionError(f"unexpected call {method} {path}")


ALL_REALM_ROLES = {"ops", "external_auditor", "hr", "warehouse", "manager", "finance",
                   "default-roles-erp", "offline_access"}


def _kc(**users):
    return FakeKeycloak(
        {uid: {"email": email, "roles": set(roles)} for uid, (email, roles) in users.items()},
        ALL_REALM_ROLES,
    )


def _factory(fake):
    return lambda config: ks.KeycloakAdmin(config, session=fake)


def _reconcile(fake, records, **kw):
    lines = []
    code = ks.run_reconcile(records, env=ENV, admin_factory=_factory(fake), write=lines.append, **kw)
    return code, lines


# -- the catalog marks exactly the roles the sync may manage ----------------

def test_the_gateway_roles_are_the_token_roles():
    # The four gateway roles, plus the four model-change approvers (ITGC-M):
    # the middleware's model_promotion chains name ML_LEAD / CONTROLLER /
    # CFO_DESIGNATE / ONCALL_LEAD, so assigning one must put it in the token.
    assert catalog.token_realm_roles() == {
        "ops", "external_auditor", "hr", "warehouse",
        "ml_lead", "controller", "cfo_designate", "oncall_lead",
    }


def test_external_auditor_is_the_only_external_role():
    assert catalog.external_role_keys() == {"external_auditor"}


def test_diff_never_names_an_unmanaged_role():
    add, remove = ks.compute_diff(
        assigned=["ops", "accountant", "manager"],
        held=["hr", "manager", "finance", "default-roles-erp"],
        managed=catalog.token_realm_roles(),
    )
    assert (add, remove) == (["ops"], ["hr"])


# -- the behaviours the brief names -----------------------------------------

def test_adds_a_missing_role():
    fake = _kc(u1=("jo@example.com", {"default-roles-erp"}))
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["ops", "employee"])])
    assert code == 0
    assert fake.users["u1"]["roles"] == {"default-roles-erp", "ops"}
    assert "employee:1: add ops" in lines


def test_removes_a_revoked_role():
    fake = _kc(u1=("jo@example.com", {"ops", "warehouse"}))
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["warehouse"])])
    assert code == 0
    assert fake.users["u1"]["roles"] == {"warehouse"}
    assert "employee:1: remove ops" in lines


def test_leaves_a_non_catalog_realm_role_alone():
    # `manager` and `finance` are real realm roles the middleware reads, but they
    # are not catalog token roles: the page must never grant or revoke them,
    # even when the employee's assignment names one.
    fake = _kc(u1=("jo@example.com", {"manager", "finance", "default-roles-erp", "hr"}))
    code, _ = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["finance_manager", "admin"])])
    assert code == 0
    assert fake.users["u1"]["roles"] == {"manager", "finance", "default-roles-erp"}
    sent = [r["name"] for c in fake.writes() for r in c[3]]
    assert sent == ["hr"]


def test_an_assigned_non_token_catalog_role_is_not_pushed():
    fake = _kc(u1=("jo@example.com", set()))
    code, _ = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["admin", "accountant"])])
    assert code == 0
    assert fake.users["u1"]["roles"] == set()
    assert fake.writes() == []


def test_dry_run_changes_nothing():
    fake = _kc(u1=("jo@example.com", {"hr"}))
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["ops"])], dry_run=True)
    assert code == 0
    assert fake.users["u1"]["roles"] == {"hr"}
    assert fake.writes() == []
    assert "employee:1: would add ops; would remove hr" in lines


def test_idempotent_second_run_writes_nothing():
    fake = _kc(u1=("jo@example.com", {"hr"}))
    rec = [ks.AccessRecord("employee:1", "jo@example.com", ["ops", "external_auditor"])]
    assert _reconcile(fake, rec)[0] == 0
    before = len(fake.writes())
    code, lines = _reconcile(fake, rec)
    assert code == 0 and len(fake.writes()) == before
    assert "employee:1: in sync" in lines


def test_unknown_user_is_reported_not_created():
    fake = _kc(u1=("jo@example.com", set()))
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:7", "nobody@example.com", ["ops"])])
    assert code == 0
    assert any(line.startswith("employee:7: no_keycloak_user") for line in lines)
    assert fake.writes() == []
    assert not any(c[0] == "POST" and c[1].endswith("/users") for c in fake.calls)


def test_employee_without_email_and_ambiguous_email_are_reported():
    fake = _kc(u1=("dup@example.com", set()), u2=("DUP@example.com", set()))
    code, lines = _reconcile(fake, [
        ks.AccessRecord("employee:1", "", ["ops"]),
        ks.AccessRecord("employee:2", "dup@example.com", ["ops"]),
    ])
    assert code == 0
    assert any(line.startswith("employee:1: no_email") for line in lines)
    assert any(line.startswith("employee:2: ambiguous_keycloak_user") for line in lines)
    assert fake.writes() == []


def test_holders_unknown_to_the_page_are_reported_and_left_alone():
    fake = _kc(u1=("jo@example.com", set()), svc=("svc@example.com", {"ops"}))
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", [])])
    assert code == 0
    assert fake.users["svc"]["roles"] == {"ops"}
    assert any("svc holds ops but matches no employee" in line for line in lines)


def test_partial_run_does_not_report_everyone_else_as_unknown():
    fake = _kc(u1=("jo@example.com", set()), svc=("svc@example.com", {"ops"}))
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", [])],
                             report_unmatched_holders=False)
    assert code == 0
    assert not any("matches no employee" in line for line in lines)


def test_holder_listing_pages_through_every_holder():
    users = {f"u{i:03d}": (f"u{i}@example.com", {"hr"}) for i in range(ks.PAGE_SIZE + 5)}
    fake = _kc(**users)
    admin = ks.KeycloakAdmin(ks.KeycloakConfig.from_env(ENV), session=fake)
    assert len(admin.users_with_realm_role("hr")) == ks.PAGE_SIZE + 5


# -- configuration and failure model ----------------------------------------

@pytest.mark.parametrize("missing", ["KEYCLOAK_ADMIN_URL", "KEYCLOAK_ADMIN_CLIENT_ID",
                                     "KEYCLOAK_ADMIN_CLIENT_SECRET"])
def test_unconfigured_command_exits_non_zero_and_calls_nothing(missing):
    env = {k: v for k, v in ENV.items() if k != missing}
    fake = _kc(u1=("jo@example.com", set()))
    lines = []
    code = ks.run_reconcile([ks.AccessRecord("employee:1", "jo@example.com", ["ops"])], env=env,
                            admin_factory=_factory(fake), write=lines.append)
    assert code != 0
    assert fake.calls == []
    assert "not configured" in lines[0]


def test_unconfigured_save_is_a_logged_no_op(caplog):
    fake = _kc(u1=("jo@example.com", set()))
    with caplog.at_level(logging.WARNING, logger=ks.__name__):
        result = ks.sync_after_save(ks.AccessRecord("employee:1", "jo@example.com", ["ops"]),
                                    env={}, admin_factory=_factory(fake))
    assert result is None
    assert fake.calls == []
    assert "not configured" in caplog.text


def test_save_pushes_when_configured():
    fake = _kc(u1=("jo@example.com", set()))
    result = ks.sync_after_save(ks.AccessRecord("employee:1", "jo@example.com", ["warehouse"]),
                                env=ENV, admin_factory=_factory(fake))
    assert result.status == ks.OK and result.add == ["warehouse"]
    assert fake.users["u1"]["roles"] == {"warehouse"}


def test_realm_defaults_to_erp_and_can_be_overridden():
    assert ks.KeycloakConfig.from_env(ENV).realm == "erp"
    assert ks.KeycloakConfig.from_env({**ENV, "KEYCLOAK_ADMIN_REALM": "other"}).realm == "other"
    assert ks.KeycloakConfig.from_env(ENV).base_url == BASE


def test_keycloak_error_on_save_is_logged_never_raised_and_secret_free(caplog):
    fake = _kc(u1=("jo@example.com", set()))
    fake.fail_on = ("POST", "/role-mappings/realm")
    with caplog.at_level(logging.INFO, logger=ks.__name__):
        result = ks.sync_after_save(ks.AccessRecord("employee:1", "jo@example.com", ["ops"]),
                                    env=ENV, admin_factory=_factory(fake))
    assert result is None
    assert "keycloak role sync failed for employee:1" in caplog.text
    assert "sync_keycloak_roles" in caplog.text
    assert SECRET not in caplog.text and TOKEN not in caplog.text


def test_keycloak_error_fails_the_command():
    fake = _kc(u1=("jo@example.com", set()), u2=("al@example.com", set()))
    fake.fail_on = ("POST", "/users/u1/role-mappings/realm")
    code, lines = _reconcile(fake, [
        ks.AccessRecord("employee:1", "jo@example.com", ["ops"]),
        ks.AccessRecord("employee:2", "al@example.com", ["hr"]),
    ])
    assert code == 1
    assert any(line.startswith("employee:1: error") for line in lines)
    # One failure does not stop the rest of the reconcile.
    assert fake.users["u2"]["roles"] == {"hr"}
    assert lines[-1].startswith("FAILED")
    assert not any(SECRET in line or TOKEN in line for line in lines)


def test_token_failure_fails_the_command_without_leaking_the_secret():
    fake = _kc(u1=("jo@example.com", set()))
    fake.fail_on = ("POST", "/openid-connect/token")
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["ops"])])
    assert code == 1
    assert not any(SECRET in line for line in lines)


def test_role_missing_from_the_realm_is_a_loud_error():
    fake = _kc(u1=("jo@example.com", set()))
    fake.realm_roles.discard("ops")
    code, lines = _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["ops"])])
    assert code == 1
    assert any("'ops' is not defined in realm 'erp'" in line for line in lines)


def test_config_repr_hides_the_secret():
    assert SECRET not in repr(ks.KeycloakConfig.from_env(ENV))


def test_fake_records_writes_as_json_bodies():
    # Guard on the fake itself: role changes are sent as JSON role representations.
    fake = _kc(u1=("jo@example.com", set()))
    _reconcile(fake, [ks.AccessRecord("employee:1", "jo@example.com", ["ops"])])
    (method, path, _params, body), = fake.writes()
    assert method == "POST" and path == "/admin/realms/erp/users/u1/role-mappings/realm"
    assert json.loads(json.dumps(body)) == [{"id": "rid-ops", "name": "ops"}]
