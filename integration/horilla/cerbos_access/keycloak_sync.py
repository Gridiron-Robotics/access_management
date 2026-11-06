"""Push access-page assignments into Keycloak realm role mappings (realm `erp`).

WHY
---
The ERP middleware decides from the TOKEN: a realm role such as `ops` reaches
its code as the `OPS` scope. Assigning a role on the access page therefore has
to put that realm role in the user's token, or the page and the gateway
disagree about who holds what. `EmployeeAccess.roles` is the source of truth;
this module makes Keycloak follow it.

WHAT IT MANAGES — AND WHAT IT NEVER TOUCHES
-------------------------------------------
Only realm roles that are in the role catalog AND marked
`keycloak_realm_role: true` (catalog.token_realm_roles()). For each user it
computes   add = assigned ∩ managed − held   and   remove = held ∩ managed −
assigned.  Any other realm role the user holds (default roles, `manager`,
`finance`, whatever an operator granted by hand) is never added or removed.
Only DIRECT realm role mappings are read and written; composite/effective
roles are Keycloak's business.

WHICH KEYCLOAK USER
-------------------
An employee is matched to a Keycloak user by EMAIL: the Horilla
`Employee.email` must equal the Keycloak user's email, exact match (Keycloak
`?email=<e>&exact=true`), and exactly one user must match. Horilla stores no
Keycloak user id, and the principal id (the Horilla username) is not
guaranteed to be the Keycloak username, so email is the stable key both
systems hold. No match, several matches, or no email on the employee is
REPORTED; the sync never creates a Keycloak user.

CONFIGURATION (environment only — nothing here is hardcoded)
------------------------------------------------------------
  KEYCLOAK_ADMIN_URL            e.g. https://sso.example.com (no trailing /admin)
  KEYCLOAK_ADMIN_REALM          the realm to manage and to get the token from (default: erp)
  KEYCLOAK_ADMIN_CLIENT_ID      a confidential client with a service account ...
  KEYCLOAK_ADMIN_CLIENT_SECRET  ... holding ONLY realm-management manage-users + view-realm

Unset URL, client id or secret = unconfigured: a logged no-op on save, and a
non-zero exit from `manage.py sync_keycloak_roles`. The secret and the access
token are never logged and never appear in an exception message.

FAILURE MODEL
-------------
On save (post-commit): a Keycloak error is logged and swallowed — the
EmployeeAccess record stays saved, and the next reconcile repairs the token.
On the reconcile command: any Keycloak error makes the command exit non-zero.

This module imports no Django, so it is unit-tested without Horilla
(integration/tests/test_keycloak_sync.py).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

from .catalog import token_realm_roles

logger = logging.getLogger(__name__)

DEFAULT_REALM = "erp"
TIMEOUT_SECONDS = 10
PAGE_SIZE = 100

ENV_URL = "KEYCLOAK_ADMIN_URL"
ENV_REALM = "KEYCLOAK_ADMIN_REALM"
ENV_CLIENT_ID = "KEYCLOAK_ADMIN_CLIENT_ID"
ENV_CLIENT_SECRET = "KEYCLOAK_ADMIN_CLIENT_SECRET"


class KeycloakError(Exception):
    """A Keycloak call failed. The message names the call and the status only —
    never a request body, a token or the client secret."""


@dataclass(frozen=True)
class KeycloakConfig:
    base_url: str
    realm: str
    client_id: str
    client_secret: str = field(repr=False)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> Optional["KeycloakConfig"]:
        """The config, or None when any required variable is unset/blank."""
        env = os.environ if env is None else env
        base_url = (env.get(ENV_URL) or "").strip().rstrip("/")
        client_id = (env.get(ENV_CLIENT_ID) or "").strip()
        client_secret = (env.get(ENV_CLIENT_SECRET) or "").strip()
        realm = (env.get(ENV_REALM) or "").strip() or DEFAULT_REALM
        if not (base_url and client_id and client_secret):
            return None
        return cls(base_url=base_url, realm=realm, client_id=client_id, client_secret=client_secret)


class KeycloakAdmin:
    """The handful of Keycloak admin REST calls the sync needs."""

    def __init__(self, config: KeycloakConfig, session=None, timeout: float = TIMEOUT_SECONDS):
        self._config = config
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout
        self._token: Optional[str] = None
        self._role_reps: dict = {}

    # -- plumbing ---------------------------------------------------------
    def _admin(self, path: str) -> str:
        return f"{self._config.base_url}/admin/realms/{quote(self._config.realm, safe='')}{path}"

    def _request(self, method: str, url: str, what: str, ok=(200, 204), **kwargs):
        try:
            resp = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            # The exception text can carry the URL; it never carries the body,
            # which is where the secret is.
            raise KeycloakError(f"{what}: {type(exc).__name__}") from None
        if resp.status_code not in ok:
            raise KeycloakError(f"{what}: HTTP {resp.status_code}")
        return resp

    def _headers(self) -> dict:
        if self._token is None:
            url = (
                f"{self._config.base_url}/realms/{quote(self._config.realm, safe='')}"
                "/protocol/openid-connect/token"
            )
            resp = self._request(
                "POST",
                url,
                "service-account token",
                ok=(200,),
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                },
            )
            token = (resp.json() or {}).get("access_token")
            if not token:
                raise KeycloakError("service-account token: no access_token in the response")
            self._token = token
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path: str, what: str, ok=(200,), **kwargs):
        return self._request("GET", self._admin(path), what, ok=ok, headers=self._headers(), **kwargs)

    # -- calls ------------------------------------------------------------
    def find_users_by_email(self, email: str) -> List[str]:
        resp = self._get(
            "/users", "look up user by email", params={"email": email, "exact": "true"}
        )
        users = resp.json() or []
        # `exact=true` is honoured by every supported Keycloak, but the match is
        # re-checked here (case-insensitively: Keycloak lower-cases emails).
        return [
            u["id"]
            for u in users
            if isinstance(u, dict) and (u.get("email") or "").lower() == email.lower()
        ]

    def realm_role_mappings(self, user_id: str) -> set:
        resp = self._get(
            f"/users/{quote(user_id, safe='')}/role-mappings/realm", "read realm role mappings"
        )
        return {r["name"] for r in (resp.json() or []) if isinstance(r, dict) and "name" in r}

    def _role_rep(self, name: str) -> dict:
        if name not in self._role_reps:
            resp = self._get(f"/roles/{quote(name, safe='')}", f"read realm role {name!r}", ok=(200, 404))
            if resp.status_code == 404:
                raise KeycloakError(
                    f"realm role {name!r} is not defined in realm {self._config.realm!r} "
                    "(create it: erp_django_middleware keycloak/DEPLOYMENT.md)"
                )
            rep = resp.json() or {}
            self._role_reps[name] = {"id": rep.get("id"), "name": rep.get("name", name)}
        return self._role_reps[name]

    def _change(self, method: str, user_id: str, names: Sequence[str], what: str) -> None:
        if not names:
            return
        reps = [self._role_rep(n) for n in names]
        self._request(
            method,
            self._admin(f"/users/{quote(user_id, safe='')}/role-mappings/realm"),
            what,
            ok=(204,),
            headers=self._headers(),
            json=reps,
        )

    def add_realm_roles(self, user_id: str, names: Sequence[str]) -> None:
        self._change("POST", user_id, names, "add realm roles")

    def remove_realm_roles(self, user_id: str, names: Sequence[str]) -> None:
        self._change("DELETE", user_id, names, "remove realm roles")

    def users_with_realm_role(self, name: str) -> List[str]:
        """Ids of users holding `name` directly (paged)."""
        out: List[str] = []
        first = 0
        while True:
            resp = self._get(
                f"/roles/{quote(name, safe='')}/users",
                f"list holders of realm role {name!r}",
                params={"first": first, "max": PAGE_SIZE},
            )
            page = resp.json() or []
            out.extend(u["id"] for u in page if isinstance(u, dict) and "id" in u)
            if len(page) < PAGE_SIZE:
                return out
            first += PAGE_SIZE


# ---------------------------------------------------------------------------
# The diff and the per-employee sync
# ---------------------------------------------------------------------------

OK = "ok"  # in sync after this run (roles may have been changed)
NO_EMAIL = "no_email"
NO_KEYCLOAK_USER = "no_keycloak_user"
AMBIGUOUS = "ambiguous_keycloak_user"
ERROR = "error"


@dataclass
class SyncResult:
    label: str
    status: str
    keycloak_user_id: Optional[str] = None
    add: List[str] = field(default_factory=list)
    remove: List[str] = field(default_factory=list)
    dry_run: bool = False
    detail: str = ""

    def describe(self) -> str:
        verb = "would " if self.dry_run else ""
        if self.status == OK:
            if not (self.add or self.remove):
                return f"{self.label}: in sync"
            parts = []
            if self.add:
                parts.append(f"{verb}add {', '.join(self.add)}")
            if self.remove:
                parts.append(f"{verb}remove {', '.join(self.remove)}")
            return f"{self.label}: {'; '.join(parts)}"
        return f"{self.label}: {self.status}{(' — ' + self.detail) if self.detail else ''}"


def compute_diff(assigned: Iterable[str], held: Iterable[str], managed: Iterable[str]):
    """(to_add, to_remove), both restricted to `managed`. A held role outside
    `managed` can never appear in either list."""
    managed = set(managed)
    want = set(assigned) & managed
    have = set(held) & managed
    return sorted(want - have), sorted(have - want)


def sync_employee(
    admin: KeycloakAdmin,
    label: str,
    email: Optional[str],
    assigned_roles: Iterable[str],
    *,
    managed: Optional[Iterable[str]] = None,
    dry_run: bool = False,
) -> SyncResult:
    """Make one Keycloak user's managed realm roles equal the assignment.
    Raises KeycloakError on a Keycloak failure."""
    managed = token_realm_roles() if managed is None else frozenset(managed)
    email = (email or "").strip()
    if not email:
        return SyncResult(label, NO_EMAIL, dry_run=dry_run, detail="employee has no email")
    ids = admin.find_users_by_email(email)
    if not ids:
        return SyncResult(label, NO_KEYCLOAK_USER, dry_run=dry_run,
                          detail="no Keycloak user has this email; not created")
    if len(ids) > 1:
        return SyncResult(label, AMBIGUOUS, dry_run=dry_run,
                          detail=f"{len(ids)} Keycloak users have this email")
    user_id = ids[0]
    add, remove = compute_diff(assigned_roles, admin.realm_role_mappings(user_id), managed)
    if not dry_run:
        admin.add_realm_roles(user_id, add)
        admin.remove_realm_roles(user_id, remove)
    return SyncResult(label, OK, keycloak_user_id=user_id, add=add, remove=remove, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Entry points used by the Django glue (signals.py, the management command)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccessRecord:
    """What the sync needs from one employee: a label for reports (never the
    email, which is PII in logs), the email to match on, the assigned roles."""

    label: str
    email: Optional[str]
    roles: Sequence[str]


AdminFactory = Callable[[KeycloakConfig], KeycloakAdmin]


def sync_after_save(
    record: AccessRecord,
    *,
    env: Optional[Mapping[str, str]] = None,
    admin_factory: AdminFactory = KeycloakAdmin,
) -> Optional[SyncResult]:
    """Run from `transaction.on_commit` after an EmployeeAccess save. Never
    raises: the record is already saved, and the next reconcile repairs any
    drift. Returns None when nothing was synced."""
    config = KeycloakConfig.from_env(env)
    if config is None:
        logger.warning(
            "keycloak role sync is not configured (%s, %s, %s); %s not pushed to Keycloak",
            ENV_URL, ENV_CLIENT_ID, ENV_CLIENT_SECRET, record.label,
        )
        return None
    try:
        result = sync_employee(admin_factory(config), record.label, record.email, record.roles)
    except Exception as exc:  # noqa: BLE001 — logged, the save must stand
        logger.error(
            "keycloak role sync failed for %s: %s. The access record is saved; "
            "`manage.py sync_keycloak_roles` will repair the token roles.",
            record.label, exc if isinstance(exc, KeycloakError) else type(exc).__name__,
        )
        return None
    if result.status == OK:
        logger.info("keycloak role sync: %s", result.describe())
    else:
        logger.warning("keycloak role sync: %s", result.describe())
    return result


def run_reconcile(
    records: Iterable[AccessRecord],
    *,
    dry_run: bool = False,
    env: Optional[Mapping[str, str]] = None,
    admin_factory: AdminFactory = KeycloakAdmin,
    write: Callable[[str], None] = print,
    report_unmatched_holders: bool = True,
) -> int:
    """Full reconcile. Returns the process exit code:
    0 — every record was processed (unmatched employees are reported, not fatal);
    1 — any Keycloak error;
    2 — not configured."""
    config = KeycloakConfig.from_env(env)
    if config is None:
        write(
            f"keycloak role sync is not configured: set {ENV_URL}, {ENV_CLIENT_ID} and "
            f"{ENV_CLIENT_SECRET} (and {ENV_REALM} if the realm is not '{DEFAULT_REALM}')"
        )
        return 2
    admin = admin_factory(config)
    managed = token_realm_roles()
    write(f"managed realm roles: {', '.join(sorted(managed))}{' (dry run)' if dry_run else ''}")
    errors = 0
    matched_ids = set()
    for record in records:
        try:
            result = sync_employee(admin, record.label, record.email, record.roles,
                                   managed=managed, dry_run=dry_run)
        except KeycloakError as exc:
            errors += 1
            write(f"{record.label}: {ERROR} — {exc}")
            continue
        if result.keycloak_user_id:
            matched_ids.add(result.keycloak_user_id)
        write(result.describe())

    # Holders the access page does not know about: reported, never changed.
    # They are typically service accounts or operators granted by hand; the
    # page is not allowed to take roles from someone it cannot see. (Skipped
    # for a partial run, where everyone outside the subset would look unknown.)
    for name in sorted(managed) if report_unmatched_holders else ():
        try:
            holders = admin.users_with_realm_role(name)
        except KeycloakError as exc:
            errors += 1
            write(f"realm role {name}: {ERROR} — {exc}")
            continue
        for uid in sorted(set(holders) - matched_ids):
            write(f"keycloak user {uid} holds {name} but matches no employee on the access page "
                  "(left unchanged)")

    if errors:
        write(f"FAILED: {errors} Keycloak error(s)")
        return 1
    return 0
