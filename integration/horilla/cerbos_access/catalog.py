"""Role catalog rendered by the access-assignment page.

Mirrors access_management/integration/role-catalog.yaml — keep the two in sync.
Embedded as Python so this app has no extra dependency (no YAML parser needed).
"""

BASELINE_ROLES = [
    {
        "key": "employee",
        "label": "Employee (baseline)",
        "description": "Default for all staff; enables 'act on my own records'.",
    },
]

GLOBAL_ROLES = [
    {
        "key": "admin",
        "label": "Administrator",
        "description": "Full access to every module. Grant to very few people.",
    },
]

MODULES = [
    {
        "key": "finance",
        "label": "Finance / Accounting",
        "roles": [
            {"key": "accountant", "label": "Accountant",
             "description": "View and create invoices."},
            {"key": "finance_manager", "label": "Finance Manager",
             "description": "Approve invoices under $10,000."},
        ],
    },
    {
        "key": "inventory",
        "label": "Inventory / Warehouse",
        "roles": [
            {"key": "warehouse_clerk", "label": "Warehouse Clerk",
             "description": "View; create/adjust stock in their own location."},
            {"key": "warehouse_manager", "label": "Warehouse Manager",
             "description": "Also transfer and delete items anywhere."},
        ],
    },
    {
        "key": "hr",
        "label": "HR / People",
        "roles": [
            {"key": "hr_specialist", "label": "HR Specialist",
             "description": "View and edit employee records."},
            {"key": "hr_manager", "label": "HR Manager",
             "description": "Also terminate employee records."},
        ],
    },
    {
        "key": "sales",
        "label": "Sales / CRM",
        "roles": [
            {"key": "sales_rep", "label": "Sales Rep",
             "description": "View/create leads; update their own leads."},
            {"key": "sales_manager", "label": "Sales Manager",
             "description": "Also reassign and update any lead."},
        ],
    },
    {
        "key": "purchasing",
        "label": "Purchasing / Procurement",
        "roles": [
            {"key": "buyer", "label": "Buyer",
             "description": "View/create POs; submit their own for approval."},
            {"key": "purchasing_manager", "label": "Purchasing Manager",
             "description": "Approve purchase orders up to $25,000."},
        ],
    },
    {
        "key": "manufacturing",
        "label": "Manufacturing / Production",
        "roles": [
            {"key": "operator", "label": "Operator",
             "description": "View work orders; start/complete on their own line."},
            {"key": "supervisor", "label": "Supervisor",
             "description": "Also start/complete on any line and cancel."},
        ],
    },
]


def all_role_keys():
    keys = {r["key"] for r in BASELINE_ROLES} | {r["key"] for r in GLOBAL_ROLES}
    for module in MODULES:
        keys |= {r["key"] for r in module["roles"]}
    return keys


def valid_roles(roles):
    """Drop anything not in the catalog (defends against tampered form posts)."""
    allowed = all_role_keys()
    # preserve order, de-dupe
    seen, out = set(), []
    for r in roles:
        if r in allowed and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def preview_resources(principal_id):
    """Representative sample records used by the 'preview access' feature, so an
    admin can see what the selected roles actually permit. `owner` is set to the
    principal so ownership rules show up."""
    return [
        {"actions": ["view", "create", "approve"],
         "resource": {"kind": "finance:invoice", "id": "sample",
                      "attr": {"owner": principal_id, "amount": 5000, "department": "finance"}}},
        {"actions": ["view", "create", "adjust", "transfer"],
         "resource": {"kind": "inventory:item", "id": "sample", "attr": {"location": "NYC"}}},
        {"actions": ["view", "edit", "terminate"],
         "resource": {"kind": "hr:employee_record", "id": "sample",
                      "attr": {"owner": principal_id, "department": "hr"}}},
        {"actions": ["view", "create", "update", "reassign"],
         "resource": {"kind": "sales:lead", "id": "sample", "attr": {"owner": principal_id}}},
        {"actions": ["view", "create", "submit", "approve"],
         "resource": {"kind": "purchasing:purchase_order", "id": "sample",
                      "attr": {"owner": principal_id, "amount": 5000}}},
        {"actions": ["view", "start", "complete", "cancel"],
         "resource": {"kind": "manufacturing:work_order", "id": "sample", "attr": {"line": "A"}}},
    ]
