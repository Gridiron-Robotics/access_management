"""Full reconcile of access-page assignments into Keycloak realm role mappings.

    python manage.py sync_keycloak_roles            # apply
    python manage.py sync_keycloak_roles --dry-run  # report the diff, change nothing
    python manage.py sync_keycloak_roles --employee 42

Exit status: 0 when every employee was processed (employees with no matching
Keycloak user are reported, not created); non-zero when the sync is not
configured or any Keycloak call failed. See keycloak_sync.py.
"""

from django.core.management.base import BaseCommand, CommandError

from employee.models import Employee

from ... import keycloak_sync
from ...models import EmployeeAccess


class Command(BaseCommand):
    help = "Make Keycloak realm role mappings (realm erp) match the access page's token roles."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Print what would change; change nothing.")
        parser.add_argument("--employee", type=int, action="append", default=None,
                            help="Only this employee id (repeatable).")

    def handle(self, *args, dry_run=False, employee=None, **options):
        employees = Employee.objects.all().order_by("pk")
        if employee:
            employees = employees.filter(pk__in=employee)
        roles_by_emp = {
            a.employee_id: a.roles
            for a in EmployeeAccess.objects.filter(employee__in=employees)
        }
        # An employee with no EmployeeAccess row holds no catalog role, so any
        # managed realm role they hold is removed — the page is the source of truth.
        records = (
            keycloak_sync.AccessRecord(
                label=f"employee:{e.pk}",
                email=getattr(e, "email", None),
                roles=list(roles_by_emp.get(e.pk) or []),
            )
            for e in employees
        )
        code = keycloak_sync.run_reconcile(
            records,
            dry_run=dry_run,
            write=self.stdout.write,
            report_unmatched_holders=not employee,
        )
        if code:
            raise CommandError("keycloak role sync failed (see above)", returncode=code)
