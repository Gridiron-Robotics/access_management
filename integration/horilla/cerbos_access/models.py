from django.conf import settings
from django.db import models


class EmployeeAccess(models.Model):
    """The access roles assigned to an employee — the 'who has which role' data.

    This is the source of truth for assignments. The *rules* (what each role can
    do) live in the access_management repo's policies / Cerbos Hub, never here.
    """

    employee = models.OneToOneField(
        "employee.Employee",
        on_delete=models.CASCADE,
        related_name="cerbos_access",
    )
    # List of role keys from the catalog (see cerbos_access/catalog.py).
    roles = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "Employee access"
        verbose_name_plural = "Employee access"
        permissions = [("manage_employeeaccess", "Can manage employee access roles")]

    def __str__(self):
        return f"{self.employee} -> {', '.join(self.roles) if self.roles else 'no roles'}"
