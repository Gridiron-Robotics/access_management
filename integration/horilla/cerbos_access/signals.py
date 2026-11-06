"""Push EmployeeAccess changes to Keycloak after the transaction commits.

The work itself is in keycloak_sync.py (Django-free, unit-tested). This file
only decides WHEN: after commit, so a rolled-back save never reaches Keycloak,
and never inside the request's transaction, so a Keycloak outage cannot undo
an assignment the admin just saved. A Keycloak error is logged; the next
`manage.py sync_keycloak_roles` repairs it.
"""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from . import keycloak_sync
from .models import EmployeeAccess


def _record(access, roles):
    employee = access.employee
    return keycloak_sync.AccessRecord(
        label=f"employee:{employee.pk}",
        email=getattr(employee, "email", None),
        roles=list(roles or []),
    )


@receiver(post_save, sender=EmployeeAccess, dispatch_uid="cerbos_access_keycloak_sync_save")
def _sync_on_save(sender, instance, created, **kwargs):
    # The edit page get_or_create()s an empty record just by being opened;
    # a fresh record with no roles is not an assignment, so viewing the page
    # changes nothing in Keycloak. (A reconcile still applies it.)
    if created and not instance.roles:
        return
    record = _record(instance, instance.roles)
    transaction.on_commit(lambda: keycloak_sync.sync_after_save(record))


@receiver(pre_delete, sender=EmployeeAccess, dispatch_uid="cerbos_access_keycloak_sync_pre_delete")
def _capture_before_delete(sender, instance, **kwargs):
    # After the delete (it cascades from Employee) the employee row may be gone,
    # so capture who it was now.
    try:
        instance._keycloak_record = _record(instance, [])
    except Exception:  # noqa: BLE001 — nothing to revoke against; reconcile reports holders
        instance._keycloak_record = None


@receiver(post_delete, sender=EmployeeAccess, dispatch_uid="cerbos_access_keycloak_sync_delete")
def _sync_on_delete(sender, instance, **kwargs):
    record = getattr(instance, "_keycloak_record", None)
    if record is not None:
        # No assignment left: revoke every managed realm role, nothing else.
        transaction.on_commit(lambda: keycloak_sync.sync_after_save(record))
