"""Map a Horilla Employee to a Cerbos principal: {id, roles, attr}.

Roles come from the EmployeeAccess assignment; attributes come from the
employee's work information (department, job position, etc.).
"""


def _safe(obj, method_name):
    try:
        fn = getattr(obj, method_name, None)
        return fn() if callable(fn) else None
    except Exception:
        return None


def build_principal(employee):
    user = getattr(employee, "employee_user_id", None)
    principal_id = getattr(user, "username", None) or f"employee:{employee.pk}"

    roles = []
    access = getattr(employee, "cerbos_access", None)
    if access and access.roles:
        roles = list(access.roles)
    if getattr(employee, "is_active", True) and "employee" not in roles:
        roles.append("employee")

    attr = {}
    dept = _safe(employee, "get_department")
    if dept is not None:
        attr["department"] = getattr(dept, "department", str(dept))
    job = _safe(employee, "get_job_position")
    if job is not None:
        attr["job_position"] = str(job)
    company = _safe(employee, "get_company")
    if company is not None:
        attr["company"] = str(company)
    etype = _safe(employee, "get_employee_type")
    if etype is not None:
        attr["employee_type"] = str(etype)
    manager = _safe(employee, "get_reporting_manager")
    if manager is not None:
        manager_user = getattr(manager, "employee_user_id", None)
        attr["reporting_manager"] = getattr(manager_user, "username", None) or str(manager)

    return {"id": str(principal_id), "roles": roles or ["employee"], "attr": attr}
