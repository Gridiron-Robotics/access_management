"""HTTP service exposing the PDP as a Contract-A MCP surface.

    HEAD /            liveness
    GET  /tools       catalog (name, description, input_schema, annotations)
    POST /invoke      {"server","tool","arguments"}

Run:
    CERBOS_PDP_URL=http://cerbos:3592 \\
    ACCESS_MCP_TOKEN=<bearer> \\
    uvicorn --factory integration.mcp.server:build_default_app --port 8085

AUTHENTICATION IS FAIL-CLOSED
-----------------------------
With `ACCESS_MCP_TOKEN` unset the service refuses to start. This surface answers
"who may do what" for the whole estate, so an unauthenticated copy of it is a
map of the authorization model handed to anyone who can reach the port — and,
worse, a caller who can forge a principal can ask questions as somebody else.
There is no dev-convenience default here.
"""

from __future__ import annotations

import hmac
import os
import sys
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .gridiron_otel import setup_observability
from .pdp_contract import (
    CONTRACT_SERVER_NAME,
    ContractSurface,
    PdpError,
    build_catalog,
)

SERVICE_NAME = "access_management"


def _require_token() -> str:
    token = (os.environ.get("ACCESS_MCP_TOKEN") or "").strip()

    if not token:
        raise RuntimeError(
            "ACCESS_MCP_TOKEN is not set. This service answers 'who may do what' "
            "for the whole estate; it will not start unauthenticated."
        )

    return token


def _cerbos_checker():
    """The real PDP client, imported lazily so tests can inject their own."""
    from ..erp.cerbos_erp import CerbosERP  # noqa: PLC0415 - deliberate

    client = CerbosERP()
    return client.check


def create_app(checker: Any = None, token: str | None = None) -> FastAPI:
    resolved_token = token if token is not None else _require_token()
    surface = ContractSurface(checker or _cerbos_checker())

    app = FastAPI(title="access_management PDP (Contract-A)")

    # ERROR logs ride the OTLP rail to OpenObserve, where `level = error` opens
    # a self-heal incident against the `access_management` stream.
    setup_observability(SERVICE_NAME, app=app)

    def _authenticate(authorization: str | None) -> None:
        presented = ""
        if authorization and authorization.lower().startswith("bearer "):
            presented = authorization[7:].strip()

        # Constant-time: a timing oracle on this token is a way in.
        if not presented or not hmac.compare_digest(presented, resolved_token):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.head("/")
    def liveness() -> Response:
        # Unauthenticated on purpose: it reveals only reachability.
        return Response(status_code=200)

    @app.get("/tools")
    def tools(
        server: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict:
        # The catalog names every resource kind and action in the estate's
        # authorization model, so it is not public.
        _authenticate(authorization)

        # The estate contract is `GET /tools?server=<name>`. Answering with our
        # catalog regardless of which server was asked for would make a
        # misrouted gateway look like it works, and the caller would bind tools
        # it believes belong to something else.
        if server and server != CONTRACT_SERVER_NAME:
            return {"tools": []}

        return build_catalog()

    @app.post("/invoke")
    async def invoke(
        request: Request,
        authorization: str | None = Header(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> JSONResponse:
        _authenticate(authorization)

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        server = body.get("server")
        if server and server != CONTRACT_SERVER_NAME:
            return JSONResponse({"error": f"unknown server: {server}"}, status_code=404)

        tool = body.get("tool")
        if not tool:
            return JSONResponse({"error": "'tool' is required"}, status_code=400)

        arguments = body.get("arguments") or body.get("args") or {}
        if not isinstance(arguments, dict):
            return JSONResponse({"error": "'arguments' must be an object"}, status_code=422)

        # The platform sets `X-Tenant-Id` on tenant-scoped invocations. It may
        # only RESTATE the tenant already carried by the principal in the body —
        # it must never be the thing that decides which tenant we answer for,
        # because a header is spoofable and the principal is what the policies
        # are written against. Disagreement is a 403, not a silent preference
        # for one of the two.
        if x_tenant_id:
            principal = arguments.get("principal")
            claimed = (principal or {}).get("attr", {}).get("tenant_id") if isinstance(principal, dict) else None
            if claimed and claimed != x_tenant_id:
                return JSONResponse(
                    {"error": "X-Tenant-Id does not match principal.attr.tenant_id"},
                    status_code=403,
                )

        try:
            result = surface.invoke(tool, arguments)
        except PdpError as exc:
            message = str(exc)

            if message.startswith("unknown tool"):
                return JSONResponse({"error": message}, status_code=404)

            if "unavailable" in message:
                # The PDP could not be reached. Report it as a server-side
                # failure AND log it at ERROR so the self-heal loop sees it —
                # an authorization service that cannot decide is an incident,
                # not a routine 4xx.
                import logging

                logging.getLogger(SERVICE_NAME).error(
                    "policy decision unavailable for tool=%s: %s", tool, message
                )
                return JSONResponse({"error": message}, status_code=503)

            # A malformed request: missing tenant, absent action, bad shape.
            return JSONResponse({"error": message}, status_code=422)

        return JSONResponse({"tool": tool, "result": result})

    return app


def build_default_app() -> FastAPI:
    """Entrypoint for `uvicorn --factory integration.mcp.server:build_default_app`.

    A factory rather than a module-level `app`, so an unconfigured deployment
    dies with the RuntimeError that says WHY. Exporting `app = None` when the
    token is unset made uvicorn report "not callable", which sends whoever is
    on call looking for an import bug instead of a missing secret.
    """
    try:
        return create_app()
    except RuntimeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
