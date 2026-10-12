"""Role catalog rendered by the access-assignment page.

Mirrors access_management/integration/role-catalog.yaml — keep the two in sync
(integration/tests/test_role_catalog.py fails the build when they differ).
Embedded as Python so this app has no extra dependency (no YAML parser needed).

`keycloak_realm_role: True` marks a role that is also a Keycloak realm role
(realm `erp`) of the same name: assigning it here is what puts it in the user's
token, via keycloak_sync.py. `external: True` marks a role for people outside
the company; it grants no staff access.
"""

BASELINE_ROLES = [
    {
        "key": "employee",
        "label": "Employee (baseline)",
        "description": "Default for all staff; enables \"can act on my own records\".",
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
            {
                "key": "accountant",
                "label": "Accountant",
                "description": "View and create invoices.",
            },
            {
                "key": "finance_manager",
                "label": "Finance Manager",
                "description": "Approve invoices under $10,000.",
            },
        ],
    },
    {
        "key": "inventory",
        "label": "Inventory / Warehouse",
        "roles": [
            {
                "key": "warehouse_clerk",
                "label": "Warehouse Clerk",
                "description": "View items; create/adjust stock in their own location.",
            },
            {
                "key": "warehouse_manager",
                "label": "Warehouse Manager",
                "description": "Also transfer and delete items anywhere.",
            },
            {
                "key": "warehouse",
                "label": "Warehouse (ERP gateway)",
                "description": (
                    "Stock reads and adjustments in their own location; view tenant orders "
                    "and shipments; ERP gateway tools scoped to WAREHOUSE (destructive ones "
                    "only with a recorded human approval). No finance access."
                ),
                "keycloak_realm_role": True,
            },
        ],
    },
    {
        "key": "hr",
        "label": "HR / People",
        "roles": [
            {
                "key": "hr_specialist",
                "label": "HR Specialist",
                "description": "View and edit employee records.",
            },
            {
                "key": "hr_manager",
                "label": "HR Manager",
                "description": "Also terminate employee records.",
            },
            {
                "key": "hr",
                "label": "HR (ERP gateway)",
                "description": (
                    "View and edit employee records (not terminate); ERP gateway tools scoped"
                    " to HR (destructive ones only with a recorded human approval). No "
                    "inventory or finance access."
                ),
                "keycloak_realm_role": True,
            },
        ],
    },
    {
        "key": "sales",
        "label": "Sales / CRM",
        "roles": [
            {
                "key": "sales_rep",
                "label": "Sales Rep",
                "description": "View/create leads; update their own leads.",
            },
            {
                "key": "sales_manager",
                "label": "Sales Manager",
                "description": "Also reassign and update any lead.",
            },
        ],
    },
    {
        "key": "purchasing",
        "label": "Purchasing / Procurement",
        "roles": [
            {
                "key": "buyer",
                "label": "Buyer",
                "description": "View/create POs; submit their own for approval.",
            },
            {
                "key": "purchasing_manager",
                "label": "Purchasing Manager",
                "description": "Approve purchase orders up to $25,000.",
            },
        ],
    },
    {
        "key": "manufacturing",
        "label": "Manufacturing / Production",
        "roles": [
            {
                "key": "operator",
                "label": "Operator",
                "description": "View work orders; start/complete on their own line.",
            },
            {
                "key": "supervisor",
                "label": "Supervisor",
                "description": "Also start/complete on any line and cancel.",
            },
        ],
    },
    {
        "key": "commerce",
        "label": "Commerce / Selling",
        "roles": [
            {
                "key": "sales_rep",
                "label": "Sales Rep",
                "description": "View and create orders; view listings.",
            },
            {
                "key": "support_agent",
                "label": "Support Agent",
                "description": (
                    "Create RMAs, cancel unfulfilled orders, issue refunds under $250."
                ),
            },
            {
                "key": "support_manager",
                "label": "Support Manager",
                "description": (
                    "Also authorize out-of-window returns and refunds under $2,500."
                ),
            },
        ],
    },
    {
        "key": "channels",
        "label": "Sales Channels",
        "description": (
            "Grant a channel role together with the `channels` attribute below. A channel "
            "manager may only publish and edit listings on the channels they are actually "
            "assigned."
        ),
        "roles": [
            {
                "key": "channel_manager",
                "label": "Channel Manager",
                "description": (
                    "Publish/edit marketplace listings on their assigned channels."
                ),
            },
        ],
    },
    {
        "key": "pricing",
        "label": "Pricing",
        "roles": [
            {
                "key": "pricing_analyst",
                "label": "Pricing Analyst",
                "description": (
                    "Reprice within guardrails (at or above floor, moves of 15% or less)."
                ),
            },
            {
                "key": "pricing_manager",
                "label": "Pricing Manager",
                "description": (
                    "Approve repricing that breaks the guardrails, including below-floor."
                ),
            },
        ],
    },
    {
        "key": "distribution",
        "label": "Distributors / Drop-ship",
        "description": (
            "Grant together with the `distributors` attribute below. A distributor manager "
            "may only dispatch drop-ship orders and bulk-import feeds for the distributors "
            "they are assigned."
        ),
        "roles": [
            {
                "key": "distributor_manager",
                "label": "Distributor Manager",
                "description": (
                    "Dispatch drop-ship orders under $5,000; bulk-import that distributor's "
                    "feed."
                ),
            },
        ],
    },
    {
        "key": "catalog",
        "label": "Catalog / Fitment",
        "roles": [
            {
                "key": "catalog_manager",
                "label": "Catalog Manager",
                "description": (
                    "Edit catalog records; publish fitment once it has been validated."
                ),
            },
        ],
    },
    {
        "key": "agent",
        "label": "AI Agent Operation",
        "description": (
            "These govern what the autonomous agent may do on its own authority. Note that NO"
            " agent role can issue a refund, disburse funds, file a tax return or commit a "
            "drop-ship dispatch — those require a human every time."
        ),
        "roles": [
            {
                "key": "agent_operator",
                "label": "Agent Operator (service account)",
                "description": "Dispatch non-destructive MCP tools within its tool scopes.",
            },
            {
                "key": "agent_supervisor",
                "label": "Agent Supervisor",
                "description": (
                    "Dispatch destructive MCP tools, but only with a recorded human approval."
                ),
            },
        ],
    },
    {
        "key": "operations",
        "label": "Operations",
        "roles": [
            {
                "key": "ops",
                "label": "Operations (ERP gateway)",
                "description": (
                    "View/create purchase orders (not approve) and view stock; ERP gateway "
                    "tools scoped to OPS — purchasing, receiving, placement release, "
                    "deduction holds, model governance (destructive ones only with a recorded"
                    " human approval). Cannot administer the gateway."
                ),
                "keycloak_realm_role": True,
            },
        ],
    },
    {
        "key": "external",
        "label": "External parties — NOT staff",
        "description": (
            "For people OUTSIDE the company (e.g. the audit firm). These roles grant no staff"
            " access at all: do not combine them with staff roles, and do not assign them to "
            "employees. An employee assigned only an external role is not given the "
            "`employee` baseline either."
        ),
        "roles": [
            {
                "key": "external_auditor",
                "label": "External Auditor (read-only, NOT staff)",
                "description": (
                    "Read-only audit evidence through the ERP gateway — the five audit_prep "
                    "read tools (entity change history, audit-chain check, PBC request list, "
                    "tie-out run, audit package) in their own tenant. Cannot change anything "
                    "anywhere."
                ),
                "keycloak_realm_role": True,
                "external": True,
            },
        ],
    },
]


def all_role_keys():
    keys = {r["key"] for r in BASELINE_ROLES} | {r["key"] for r in GLOBAL_ROLES}
    for module in MODULES:
        keys |= {r["key"] for r in module["roles"]}
    return keys


def _all_roles():
    yield from BASELINE_ROLES
    yield from GLOBAL_ROLES
    for module in MODULES:
        yield from module["roles"]


def token_realm_roles():
    """Role keys that are also Keycloak realm roles. The ONLY realm roles the
    Keycloak sync may add or remove — every other realm role a user holds is
    left exactly as it is."""
    return frozenset(r["key"] for r in _all_roles() if r.get("keycloak_realm_role") is True)


def external_role_keys():
    """Role keys for people outside the company (e.g. the audit firm)."""
    return frozenset(r["key"] for r in _all_roles() if r.get("external") is True)


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
