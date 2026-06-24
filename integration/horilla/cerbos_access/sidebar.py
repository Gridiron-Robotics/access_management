"""Adds the "Access Management" item to Horilla's sidebar.

Requires "cerbos_access" to be listed in horilla/horilla_apps.py -> SIDEBARS.
"""
from django.urls import reverse
from django.utils.translation import gettext_lazy as trans

MENU = trans("Access Management")
IMG_SRC = "images/ui/employees.svg"

# Hide the whole menu from users without the manage permission.
ACCESSIBILITY = "cerbos_access.sidebar.menu_accessibility"

SUBMENUS = [
    {
        "menu": trans("Employee Access"),
        "redirect": reverse("cerbos-access-view"),
        "accessibility": "cerbos_access.sidebar.access_accessibility",
    },
]


def menu_accessibility(request, menu, user_perms, *args, **kwargs):
    return request.user.has_perm("cerbos_access.manage_employeeaccess")


def access_accessibility(request, submenu, user_perms, *args, **kwargs):
    return request.user.has_perm("cerbos_access.manage_employeeaccess")
