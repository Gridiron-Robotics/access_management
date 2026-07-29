# Observability + the self-heal rail

## Identity

Three names must be **the same string**, and the string is `access_management`:

| Where | What it is |
|---|---|
| `OTEL_SERVICE_NAME` / `service.name` | the resource attribute on every span + log |
| OpenObserve stream | derived from `service.name` |
| Self-heal incident `module` | derived from the alerting stream |

Rename any one of them and alerts land on a stream nobody watches, or an
incident is filed against a module that does not exist. Pinned by
`integration/tests/test_selfheal_rail.py::TestStreamIdentity`.

## What emits

`integration/mcp/server.py` calls `setup_observability("access_management", app=app)`
(the estate drop-in, `integration/mcp/gridiron_otel.py`). Traces and logs go out
over OTLP HTTP.

The upstream Cerbos PDP has its own OTLP support, configured separately in
`deploy/kamal/conf.yaml` / the Helm chart's `values-otlp.yaml`. This document is
about the MCP sidecar.

```bash
OTEL_SERVICE_NAME=access_management
OTEL_EXPORTER_OTLP_ENDPOINT=http://openobserve:5080/api/default
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64 email:password>
```

## Registering the alert

The estate template already exists. Registration is one command, run from
`langgraph-agents/deploy/observability/`:

```bash
OPENOBSERVE_URL=https://openobserve.gridironrobotics.com \
OPENOBSERVE_ORG=default \
OPENOBSERVE_AUTH="$(printf '%s' "$EMAIL:$PASSWORD" | base64)" \
OPENOBSERVE_WEBHOOK_TOKEN="$SELFHEAL_TOKEN" \
./apply-alerts.sh access_management
```

That creates alert `access_management_errors`: real-time, `level = error`,
threshold ≥ 1 in a 1-minute window, 10-minute silence, firing the
`estate-selfheal-ingress` destination. Re-running updates in place.

Verify:

```bash
curl -s -H "Authorization: Basic $OPENOBSERVE_AUTH" \
  "$OPENOBSERVE_URL/api/default/access_management/alerts" | jq '.list[].name'
# -> "access_management_errors"
```

## What counts as an incident here

**A PDP this service cannot reach.** An authorization service that cannot decide
is an outage, not a routine 4xx — every enforcing service that asks it is now
denying, and nothing else in the estate will notice until someone reports work
not going through. It is logged at ERROR and returns `503`.

**Not an incident: a denial.** Denials are the normal output of an authorization
service. Logging them at ERROR would open incidents for the system working
correctly, and bury the real ones. Pinned by
`test_mcp_server.py::test_a_routine_denial_does_NOT_raise_an_incident`.

Also not incidents, deliberately: `401` (bad bearer), `403` (tenant mismatch),
`422` (malformed arguments). Those are callers being refused, which is the
service doing its job. A spike in them is a security signal worth a dashboard,
but it is not something the self-heal loop can fix by restarting anything.

## The failure this rail is prone to

Every link is silent when it breaks: nothing throws, no test goes red on its
own, and the first symptom is an outage nobody was paged for.

The specific trap: **OpenObserve fills `level` from the OTLP record's
`severity_text`, not `severityNumber`.** A record carrying only the number
satisfies every OTel-side assertion and still never matches `level = error`.
`test_selfheal_rail.py::TestSeverityMapping` asserts on the text.

A second trap, carried by the drop-in being copied between repos: in this
Python SDK `SimpleLogRecordProcessor` takes the exporter **positionally**; in
the JavaScript SDK the same class takes an options object, and passing it
positionally there exports nothing at all, silently. `TestProcessorWiring`
asserts which convention this SDK is on rather than trusting it was checked.

## Ratchet

When something escapes a green run, add a check here **and** a test in
`test_selfheal_rail.py`. The rail is only as good as the last thing that proved
it end to end.
