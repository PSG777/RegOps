import os
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


_provider_configured = False


def configure_telemetry() -> None:
    """Configure local telemetry once; exporting is opt-in and non-authoritative."""

    global _provider_configured
    if _provider_configured:
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": "regops-api"})
    )
    if os.getenv("REGOPS_TELEMETRY_EXPORTER", "none").lower() == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _provider_configured = True


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """Create a sanitized span without allowing telemetry failures to escape."""

    try:
        current = trace.get_tracer("regops.presentation").start_span(name)
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
    except Exception:
        yield
        return
    with trace.use_span(current, end_on_exit=True):
        yield
