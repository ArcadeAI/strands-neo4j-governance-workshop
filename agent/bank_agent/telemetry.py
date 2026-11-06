"""OpenTelemetry for the agent: every model call and tool call as a span.

    --trace console    spans printed to the terminal
    --trace otlp       spans sent to OTEL_EXPORTER_OTLP_ENDPOINT (Langfuse, Jaeger, Datadog, X-Ray via ADOT...)

Arcade's audit log and the control plane's `.gate/audit.jsonl` are the record of what was
allowed; these traces are the record of what the agent tried and why.
"""

from __future__ import annotations

MODES = ("console", "otlp")


def setup(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"--trace must be one of {', '.join(MODES)}")
    from strands.telemetry import StrandsTelemetry

    telemetry = StrandsTelemetry()
    if mode == "console":
        telemetry.setup_console_exporter()
    else:
        telemetry.setup_otlp_exporter()
