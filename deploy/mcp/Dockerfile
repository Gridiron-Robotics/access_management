# The Contract-A MCP surface for the PDP (integration/mcp/server.py).
#
# A SEPARATE image from deploy/kamal/Dockerfile on purpose. That one is the
# upstream Cerbos PDP with our policies baked in — Go, no Python, and not ours
# to modify (CLAUDE.md rule 1). This is a thin sidecar that speaks the estate's
# HTTP tool contract and forwards decisions to that PDP. Keeping them apart
# means the sidecar can be redeployed, restarted, or removed entirely without
# touching the engine that every enforcing service depends on.
#
# Pinned to exact versions; never a floating tag (CLAUDE.md rule 3).
FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so a code change doesn't re-resolve the whole tree.
COPY integration/requirements.txt /app/integration/requirements.txt
RUN pip install --no-cache-dir -r /app/integration/requirements.txt

COPY integration /app/integration

# Run unprivileged. This process holds the bearer that authenticates every
# "who may do what" question in the estate.
RUN useradd --system --uid 10001 --no-create-home pdpmcp
USER 10001

EXPOSE 8085

# ACCESS_MCP_TOKEN is deliberately NOT defaulted here. The service refuses to
# start without it (integration/mcp/server.py::_require_token) — a baked-in
# default token in an image is a shared secret published to anyone who can pull.
ENV CERBOS_PDP_URL=http://access-management:3592

# --factory so an unconfigured deployment dies with the RuntimeError that names
# the missing secret, rather than uvicorn's generic "app is not callable".
CMD ["uvicorn", "--factory", "integration.mcp.server:build_default_app", \
     "--host", "0.0.0.0", "--port", "8085"]
