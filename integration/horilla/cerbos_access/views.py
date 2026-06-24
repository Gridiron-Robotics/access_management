from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from employee.models import Employee

from . import catalog
from . import cerbos_client
from . import principal as principal_mod
from .models import EmployeeAccess

PERM = "cerbos_access.manage_employeeaccess"


@login_required
@permission_required(PERM)
def access_list(request):
    """List employees with their assigned access roles."""
    search = request.GET.get("search", "").strip()
    employees = Employee.objects.all().order_by("employee_first_name", "employee_last_name")
    if search:
        employees = employees.filter(
            Q(employee_first_name__icontains=search)
            | Q(employee_last_name__icontains=search)
            | Q(email__icontains=search)
        )

    paginator = Paginator(employees, 25)
    page = paginator.get_page(request.GET.get("page"))

    roles_by_emp = {
        a.employee_id: a.roles
        for a in EmployeeAccess.objects.filter(employee__in=list(page.object_list))
    }
    rows = [{"employee": e, "roles": roles_by_emp.get(e.pk, [])} for e in page.object_list]
    return render(
        request,
        "cerbos_access/access_list.html",
        {"rows": rows, "page": page, "search": search},
    )


@login_required
@permission_required(PERM)
def access_edit(request, employee_id):
    """Assign/clear access roles for one employee."""
    employee = get_object_or_404(Employee, pk=employee_id)
    access, _ = EmployeeAccess.objects.get_or_create(employee=employee)

    if request.method == "POST":
        access.roles = catalog.valid_roles(request.POST.getlist("roles"))
        access.updated_by = request.user if request.user.is_authenticated else None
        access.save()
        messages.success(request, "Access updated.")
        return redirect(reverse("cerbos-access-view"))

    context = {
        "employee": employee,
        "selected": set(access.roles or []),
        "baseline_roles": catalog.BASELINE_ROLES,
        "global_roles": catalog.GLOBAL_ROLES,
        "modules": catalog.MODULES,
    }
    return render(request, "cerbos_access/access_form.html", context)


@login_required
@permission_required(PERM)
def access_preview(request, employee_id):
    """Show what the employee can actually do, by asking the Cerbos PDP."""
    employee = get_object_or_404(Employee, pk=employee_id)
    principal = principal_mod.build_principal(employee)
    allowed, error = [], None
    try:
        result = cerbos_client.check_resources(
            principal, catalog.preview_resources(principal["id"])
        )
        for r in result.get("results", []):
            kind = r.get("resource", {}).get("kind", "")
            for action, effect in r.get("actions", {}).items():
                if effect == "EFFECT_ALLOW":
                    allowed.append({"kind": kind, "action": action})
    except Exception as exc:  # PDP unreachable / misconfigured
        error = str(exc)
    return render(
        request,
        "cerbos_access/_preview.html",
        {"principal": principal, "allowed": allowed, "error": error},
    )


def principal_api(request, employee_id):
    """Service-to-service endpoint: the principal (id, roles, attrs) your ERP
    sends to Cerbos. Auth via a logged-in session OR an `Authorization: Api-Key`
    header (django-rest-framework-api-key)."""
    if not (request.user.is_authenticated or _has_api_key(request)):
        return JsonResponse({"detail": "authentication required"}, status=401)
    employee = get_object_or_404(Employee, pk=employee_id)
    return JsonResponse(principal_mod.build_principal(employee))


def _has_api_key(request):
    try:
        from rest_framework_api_key.models import APIKey
    except Exception:
        return False
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    key = auth.split("Api-Key", 1)[-1].strip() if "Api-Key" in auth else ""
    return bool(key) and APIKey.objects.is_valid(key)
