Cerbos Helm Chart
=================

Cerbos is the open core, language-agnostic, scalable authorization solution that makes user permissions and authorization simple to implement and manage by writing context-aware access control policies for your application resources.

* [Cerbos website](https://cerbos.dev)
* [Cerbos documentation](https://docs.cerbos.dev)
* [Cerbos GitHub repository](https://github.com/cerbos/cerbos)
* [Cerbos Slack community](http://go.cerbos.io/slack)

Contract-A MCP sidecar (`mcp.*`)
--------------------------------

The chart can optionally ship the Contract-A MCP surface (`integration/mcp/server.py`) —
the agent-plane surface that answers *"may this principal do that?"* for the agent
brain before an action is planned. It is a **separate** Deployment + Service from the
Cerbos PDP so it can be restarted or removed without touching the engine every
enforcing service depends on.

It is **disabled by default** (`mcp.enabled: false`) so a default render stays
byte-identical to upstream. Enable it with the example in
[`values-mcp.yaml`](values-mcp.yaml):

```bash
# The bearer token that guards the estate's authorization model must come from a
# PRE-CREATED Secret — it is never a chart value (matches CONTRACT.md's
# "Fail-closed boot" posture).
kubectl create secret generic access-mcp --from-literal=ACCESS_MCP_TOKEN=<token>

helm upgrade --install cerbos deploy/charts/cerbos -f deploy/charts/cerbos/values-mcp.yaml
```

Key values:

| Value | Default | Notes |
|---|---|---|
| `mcp.enabled` | `false` | Render the sidecar Deployment + Service. |
| `mcp.image.repository` / `mcp.image.tag` / `mcp.image.digest` | `""` | Built from `deploy/mcp/Dockerfile`. Pin an exact tag or digest, never `:latest`. |
| `mcp.port` | `8085` | Contract-A fixes the listen port at 8085. |
| `mcp.service.name` | `access-management-mcp` | The agent platform binds this exact DNS name (`langgraph-agents/specialists/registry.py`); keep it unless the consumer changes too. |
| `mcp.existingSecret` | `""` | **Required when enabled.** Name of a pre-created Secret holding `ACCESS_MCP_TOKEN`; the chart fails to render without it. |
| `mcp.tokenSecretKey` | `ACCESS_MCP_TOKEN` | Key within `existingSecret`. |

The sidecar's liveness/readiness use a TCP probe because the MCP serves `HEAD /`,
not `GET /`. `ACCESS_MCP_TOKEN` is injected only via `secretKeyRef` — it never
appears in the rendered pod spec.
