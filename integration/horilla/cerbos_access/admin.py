from django.contrib import admin

from .models import EmployeeAccess


@admin.register(EmployeeAccess)
class EmployeeAccessAdmin(admin.ModelAdmin):
    list_display = ("employee", "roles", "updated_at", "updated_by")
    search_fields = ("employee__employee_first_name", "employee__employee_last_name")
