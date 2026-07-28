"""Ratchet: the OpenObserve self-heal rail must keep working.

The estate alert fires on `level = error` in the `access_management` OpenObserve
stream, and OpenObserve fills `level` from the OTLP record's **severity_text**.
So the chain that has to hold is:

    logging.getLogger("access_management").error(...)
        -> LoggingHandler
            -> a log record whose severity_text == "ERROR"
                -> OTLP exporter
                    -> OpenObserve stream `access_management`
                        -> alert `access_management_errors`
                            -> langgraph self-heal loop

Every link is silent when it breaks. Nothing throws, no test goes red on its
own, and the first symptom is an authorization outage nobody was paged for —
which is exactly the failure the loop exists to catch. These tests pin the two
links that live in this repo.

They deliberately do NOT need a running OpenObserve: a test that only passes
against live infrastructure would be skipped in CI and would protect nothing.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integration.mcp.server import SERVICE_NAME  # noqa: E402


class TestStreamIdentity:
    def test_the_service_name_matches_the_stream_and_incident_name(self):
        """
        `service.name` becomes the OTLP stream name, the stream name is what the
        alert rule is registered against, and the alert's stream is what the
        self-heal loop reports as the incident's `module`. Rename any one of
        them and alerts land on a stream nobody watches.

        Registered with:  ./apply-alerts.sh access_management
        (langgraph-agents/deploy/observability/)
        """
        assert SERVICE_NAME == "access_management"


class TestSeverityMapping:
    """
    OpenObserve derives `level` from **severity_text**, not severityNumber. A
    record carrying only a number satisfies every OTel-side assertion and still
    never matches `level = error`.
    """

    @staticmethod
    def _capture(emit) -> list:
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import (
            LogExporter,
            LogExportResult,
            SimpleLogRecordProcessor,
        )

        captured: list = []

        class _Capture(LogExporter):
            def export(self, batch):
                captured.extend(batch)
                return LogExportResult.SUCCESS

            def shutdown(self):
                pass

        provider = LoggerProvider()
        provider.add_log_record_processor(SimpleLogRecordProcessor(_Capture()))

        logger = logging.getLogger("test_selfheal_rail")
        handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            emit(logger)
        finally:
            logger.removeHandler(handler)

        return [d.log_record for d in captured]

    def test_an_error_carries_severity_text_ERROR(self):
        records = self._capture(lambda log: log.error("policy decision unavailable"))

        assert records, "the ERROR never reached the exporter"
        assert records[0].severity_text == "ERROR", (
            "OpenObserve maps severity_text -> level; without 'ERROR' here the "
            "`level = error` alert never fires and the outage is invisible"
        )

    def test_a_warning_does_NOT_look_like_an_error(self):
        # If warnings arrived as ERROR the loop would open incidents for
        # non-incidents, and real ones would be lost in the volume.
        records = self._capture(lambda log: log.warning("slow PDP response"))

        assert records
        # The invariant is "does not match `level = error`", not an exact
        # spelling — this SDK emits "WARN", and pinning that string would make
        # the test about the SDK's vocabulary rather than about the alert.
        assert records[0].severity_text != "ERROR"
        assert records[0].severity_text.upper().startswith("WARN")

    def test_the_body_survives_so_the_loop_can_categorise_it(self):
        # The self-heal loop reads the message to decide code-fault vs
        # runtime-fault. An empty body routes the incident nowhere useful.
        records = self._capture(
            lambda log: log.error("policy decision unavailable for tool=%s", "check_access")
        )

        assert "check_access" in str(records[0].body)


class TestProcessorWiring:
    def test_the_log_processor_takes_the_exporter_positionally(self):
        """
        Pinning the shape the drop-in uses. In this SDK the exporter is the
        first positional argument; in the JavaScript SDK the same class takes an
        options object, and passing it positionally there silently exports
        nothing. Since the drop-in is copied between repos, assert which
        convention this one is on rather than trusting that it was checked.
        """
        import inspect

        from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor

        params = list(inspect.signature(SimpleLogRecordProcessor.__init__).parameters)

        assert params[1] == "exporter", (
            "the SDK changed its processor signature — integration/mcp/"
            "gridiron_otel.py passes the exporter positionally and would now be "
            "exporting nothing"
        )


class TestOutageIsAnIncident:
    def test_a_pdp_outage_logs_at_ERROR_on_the_service_logger(self, caplog):
        """
        End of the in-repo chain: the thing that must actually produce an ERROR
        is an unreachable PDP. Duplicated from test_mcp_server.py on purpose —
        that file tests the HTTP contract, this one tests the alerting rail, and
        the rail should fail loudly if someone "cleans up" the log level while
        working on status codes.
        """
        from fastapi.testclient import TestClient

        from integration.mcp.server import create_app

        def _boom(*_args, **_kwargs):
            raise ConnectionError("PDP unreachable")

        client = TestClient(create_app(checker=_boom, token="t"))

        with caplog.at_level(logging.ERROR, logger=SERVICE_NAME):
            response = client.post(
                "/invoke",
                headers={"Authorization": "Bearer t"},
                json={
                    "tool": "check_access",
                    "arguments": {
                        "principal": {"id": "a", "roles": ["admin"], "attr": {"tenant_id": "t-1"}},
                        "action": "issue",
                        "resource": {"kind": "commerce:refund", "id": "r", "attr": {"tenant_id": "t-1"}},
                    },
                },
            )

        assert response.status_code == 503
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "an unreachable PDP must produce an ERROR record"
        assert any(r.name == SERVICE_NAME for r in errors), (
            f"the ERROR must be on the '{SERVICE_NAME}' logger so it lands in "
            "that OpenObserve stream"
        )
