# Human-in-the-loop: how `approval_ref` stays honest

Several policies here treat a role as **necessary but not sufficient** and
additionally require a recorded human approval:

| Policy | Action | Also requires a human |
|---|---|---|
| `commerce:refund` | `issue` | amount ≥ 10,000 |
| `commerce:payment` | `disburse` | **always**, for `ach_credit` / `wire` — pushing money out has no routine band |
| `commerce:order` | `place` | drop-ship above 5,000 |
| `commerce:shipment` | `buy_label` | freight above 500 |
| `commerce:tax` | `file_return`, `remit` | always — a filing is a signed statement to an authority |
| `commerce:rma` | `authorize` | outside the return window |
| `commerce:marketplace_listing` | `reprice` | below the price floor |
| `agent:mcp_tool` | `dispatch` | whenever the tool is destructive |

---

## The problem this document exists to solve

A PDP is a pure function. Cerbos evaluates the attributes it is handed; it
cannot call out to check anything. So `approved_by_human: true` is, on its own,
**a boolean the calling service set**. Anything that can reach the PDP can set
it, and after the fact there is nothing to inspect — no approver, no timestamp,
no chain. A refund band that any caller can step over by adding one field is
not a band.

## The rule

**Every approval-gated policy requires BOTH:**

```yaml
- expr: request.resource.attr.approved_by_human == true
- expr: size(request.resource.attr.approval_ref) > 0
```

`approval_ref` is the id of an `ApprovalRequest` in
`erp_django_middleware`'s `approvals` app. Requiring it converts an
unfalsifiable boolean into a claim that **points at a record** — one that either
exists and is `APPROVED`, or does not. That is checkable during an incident and
auditable afterwards.

This does not make the PDP able to verify the record; it makes the enforcing
service unable to fabricate an approval without also fabricating a row that an
auditor can look for.

## What the enforcing service MUST do

The service that owns the operation — not the PDP, not the agent — is
responsible for these three steps, in order:

1. **Open the approval.** Do not perform the action.

   ```python
   from django_middleware.approvals.services import ApprovalService

   req = ApprovalService(tenant_id).request_approval(
       resource_type="commerce:refund",
       resource_id=refund_id,
       context={"amount": amount},
       requested_by=principal_id,
       amount=amount,
   )
   ```

   `request_approval` returns `None` when no rule matches — meaning no approval
   was required. That is not the same as "approved", and it must not be turned
   into `approved_by_human: true`.

2. **Resolve the approval when the caller comes back.** Derive both attributes
   from the stored record. **Never from client input.**

   ```python
   req = ApprovalService(tenant_id).get(approval_id)

   attrs = {
       "tenant_id": tenant_id,
       "amount": amount,
       "approved_by_human": req.status == ApprovalStatus.APPROVED,
       "approval_ref": str(req.id) if req.status == ApprovalStatus.APPROVED else "",
   }
   ```

   `ApprovalService.get` is already tenant-filtered, so an approval belonging to
   another tenant raises rather than resolving.

3. **Then ask the PDP, and act only on ALLOW.**

### The three ways to get this wrong

- **Passing the request body through.** If `approved_by_human` or
  `approval_ref` can arrive from the caller and reach the PDP unmodified, the
  gate is decorative. Build the attribute map server-side, field by field.
- **Treating "no rule matched" as approved.** `request_approval` returning
  `None` means the rule engine found nothing to route — the action may well be
  fine, but it was not *approved*, and the policy's high band still applies.
- **Reusing an approval.** The approval names one `resource_id`. Check it
  matches the resource being acted on, or a 250-dollar approval authorizes a
  25,000-dollar refund.

## Why the middleware owns the record and this repo owns the rule

They answer different questions, and keeping them apart is what makes both
answerable:

- **This repo** decides *whether an approval is required at all* — the bands, the
  roles, the tenancy. That is policy, it changes with the business, and it is
  testable offline against 191 cases.
- **The middleware** runs the *approval itself* — the chain of approver roles,
  the SLA and escalation, the audit record, the NATS event. That needs a
  database, a clock, and a UI. None of those belong in a PDP.

Neither can be collapsed into the other. A PDP with a database stops being a
pure decision function; an approvals engine with the bands hard-coded stops
being configurable.

## For the agent brain

`explain_denial` names this case specifically:

```
denied: this action requires a recorded human approval
        (route it through the approval gate, then retry)
```

That is the string an agent should act on — open an approval and stop, rather
than retrying the same call or attempting a smaller variant that slips under a
band. See `integration/CONTRACT.md`.
