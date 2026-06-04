"""OpenTelemetry metrics for the AI telemetry pipeline.

Instruments are registered at module load time against no-op stubs so they
are always importable. Calling :func:`setup_otel` replaces them with real
SDK instruments.

When ``PROMETHEUS_PORT`` is set, metrics are exposed on
``http://localhost:{port}/metrics`` so Grafana can scrape them via
Prometheus — no extra collector needed for the local-dev profile.

In the production topology (Bucket 1) the runner sends OTLP to a central
OTel Collector. The Prometheus scrape endpoint stays available as a
sidecar for in-cluster scrapers that prefer pull mode.

Exemplars
---------
When recording the request-duration histogram, the active span's
``trace_id`` / ``span_id`` are attached as an exemplar by the SDK (provided
the histogram is recorded **inside** an active span). Grafana then renders
exemplars next to each bucket and a click navigates to Tempo.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from generator import semantic_conventions as sc  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional OTel SDK
# ---------------------------------------------------------------------------

try:
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    logger.warning("opentelemetry-sdk not found — metrics will be debug-logged only")

try:
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
        OTLPMetricExporter as OTLPGrpcMetricExporter,
    )

    _OTLP_GRPC_AVAILABLE = True
except ImportError:
    _OTLP_GRPC_AVAILABLE = False

try:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter as OTLPHttpMetricExporter,
    )

    _OTLP_HTTP_AVAILABLE = True
except ImportError:
    _OTLP_HTTP_AVAILABLE = False

_OTLP_AVAILABLE = _OTLP_GRPC_AVAILABLE or _OTLP_HTTP_AVAILABLE

try:
    from opentelemetry.exporter.prometheus import PrometheusMetricReader as _PrometheusReader

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

# ---------------------------------------------------------------------------
# No-op stubs — replaced by setup_otel()
# ---------------------------------------------------------------------------


class _NoOpCounter:
    def add(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        logger.debug("noop counter +%s %s", amount, attributes)


class _NoOpHistogram:
    def record(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        logger.debug("noop histogram %s %s", amount, attributes)


class _NoOpGauge:
    def set(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        logger.debug("noop gauge =%s %s", amount, attributes)


# Public instruments — see semantic_conventions.METRIC_* for canonical names.
request_count:    Any = _NoOpCounter()
request_duration: Any = _NoOpHistogram()
request_token:    Any = _NoOpCounter()
request_cost:     Any = _NoOpCounter()
exception_count:  Any = _NoOpCounter()

# Runner self-metrics (NFR-014).
_self_batch_duration: Any = _NoOpHistogram()
_self_publish_errors: Any = _NoOpCounter()
_self_queue_depth:    Any = _NoOpGauge()

_SELF_METRIC_INSTRUMENTS: dict[str, Any] = {}
_queue_depth_last: float = 0.0

_initialized = False

# Process-level labels — read once from env so we don't blow up Prometheus
# cardinality. High-cardinality fields (request_id, session_id, project_id)
# belong on spans / EH events only.
_PROCESS_SERVICE     = os.getenv("AI_SERVICE",  "ai-gateway")
_PROCESS_ENVIRONMENT = os.getenv("ENVIRONMENT", "prod")
_PROCESS_REGION      = os.getenv("AWS_REGION",  "us-east-1")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_otel() -> None:
    """Configure the real OTel MeterProvider and replace module-level instruments.

    Readers activated based on environment:
      ``PROMETHEUS_PORT``               → Prometheus /metrics HTTP endpoint
      ``OTEL_EXPORTER_OTLP_ENDPOINT``   → OTLP gRPC (the Collector)
    Both can be active simultaneously.
    """
    global request_count, request_duration, request_token, request_cost, exception_count
    global _self_batch_duration, _self_publish_errors, _self_queue_depth
    global _initialized

    if _initialized:
        return

    if not _OTEL_AVAILABLE:
        logger.warning("OTel unavailable — metrics will be debug-logged only")
        _initialized = True
        return

    service_name      = os.getenv("OTEL_SERVICE_NAME", "ai-telemetry")
    environment       = os.getenv("ENVIRONMENT", "prod")
    export_interval_ms = int(os.getenv("OTEL_EXPORT_INTERVAL_MS", "30000"))
    otlp_endpoint     = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    prometheus_port   = int(os.getenv("PROMETHEUS_PORT", "0"))

    resource = Resource.create({
        "service.name":            service_name,
        "deployment.environment":  environment,
    })

    readers: list[Any] = []

    if prometheus_port:
        if _PROMETHEUS_AVAILABLE:
            try:
                readers.append(_PrometheusReader())
                logger.info(
                    "Prometheus reader registered — HTTP served by runner_http on :%d/metrics",
                    prometheus_port,
                )
            except Exception as exc:
                logger.warning("Prometheus exporter init failed: %s", exc)
        else:
            logger.warning(
                "PROMETHEUS_PORT=%d set but opentelemetry-exporter-prometheus is missing",
                prometheus_port,
            )

    if otlp_endpoint and _OTLP_AVAILABLE:
        try:
            protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "").lower()
            use_http = protocol.startswith("http") or ":4318" in otlp_endpoint
            if use_http:
                if not _OTLP_HTTP_AVAILABLE:
                    raise RuntimeError("HTTP OTLP metric exporter package unavailable")
                exporter = OTLPHttpMetricExporter(endpoint=otlp_endpoint)
                logger.info(
                    "OTLP metric exporter (HTTP) → %s (interval %dms)",
                    otlp_endpoint, export_interval_ms,
                )
            else:
                if not _OTLP_GRPC_AVAILABLE:
                    raise RuntimeError("gRPC OTLP metric exporter package unavailable")
                insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() == "true"
                exporter = OTLPGrpcMetricExporter(endpoint=otlp_endpoint, insecure=insecure)
                logger.info(
                    "OTLP metric exporter (gRPC) → %s (interval %dms, insecure=%s)",
                    otlp_endpoint, export_interval_ms, insecure,
                )
            readers.append(
                PeriodicExportingMetricReader(
                    exporter, export_interval_millis=export_interval_ms,
                ),
            )
        except Exception as exc:
            logger.warning("OTLP exporter init failed: %s", exc)

    provider = MeterProvider(resource=resource, metric_readers=readers)
    _otel_metrics.set_meter_provider(provider)
    meter = _otel_metrics.get_meter(service_name)

    request_count = meter.create_counter(
        name=sc.METRIC_REQUEST_COUNT,
        unit="1",
        description="Total AI gateway requests",
    )
    request_duration = meter.create_histogram(
        name=sc.METRIC_REQUEST_DURATION,
        unit="ms",
        description="AI gateway request latency in milliseconds",
    )
    request_token = meter.create_counter(
        name=sc.METRIC_REQUEST_TOKEN,
        unit="1",
        description="Token consumption by type",
    )
    request_cost = meter.create_counter(
        name=sc.METRIC_REQUEST_COST,
        unit="USD",
        description="Accumulated request cost in USD",
    )
    exception_count = meter.create_counter(
        name=sc.METRIC_EXCEPTION_COUNT,
        unit="1",
        description="Failed requests",
    )

    # Self-metrics (observe the observer).
    _self_batch_duration = meter.create_histogram(
        name=sc.METRIC_SELF_BATCH_DURATION,
        unit="s",
        description="Wall-clock time spent in run_one_batch",
    )
    _self_publish_errors = meter.create_counter(
        name=sc.METRIC_SELF_PUBLISH_ERRORS,
        unit="1",
        description="Publish failures observed by the runner (does not include librdkafka internal retries)",
    )
    _self_queue_depth = meter.create_up_down_counter(
        name=sc.METRIC_SELF_QUEUE_DEPTH,
        unit="1",
        description="Local Kafka producer queue depth at end of batch",
    )

    _SELF_METRIC_INSTRUMENTS[sc.METRIC_SELF_BATCH_DURATION] = _self_batch_duration
    _SELF_METRIC_INSTRUMENTS[sc.METRIC_SELF_PUBLISH_ERRORS] = _self_publish_errors
    _SELF_METRIC_INSTRUMENTS[sc.METRIC_SELF_QUEUE_DEPTH]    = _self_queue_depth

    _initialized = True
    logger.info(
        "OTel metrics ready | service=%s | readers=%d", service_name, len(readers),
    )


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------


def record_metrics(event: dict[str, Any]) -> None:
    """Record all five OTel instruments for one event dict.

    Labels are kept low-cardinality so Prometheus counters accumulate on a
    bounded set of series. ``department`` is the single org-segment label used
    for dashboard filtering and breakdowns.
    """
    base: dict[str, Any] = {
        "model_name":          event["model_name"],
        "model_provider":      event["model_provider"],
        "operation_name":      event["operation_name"],
        "status":              event["status"],
        "service":             _PROCESS_SERVICE,
        "environment":         _PROCESS_ENVIRONMENT,
        "region":              event.get("region", _PROCESS_REGION),
        "department":          event.get("department", "unknown"),
        "data_classification": event.get("data_classification", "unknown"),
    }

    try:
        request_count.add(1, base)
        # Recording the histogram inside the active request span attaches
        # the trace_id as an exemplar via the OTel SDK's automatic
        # context-binding — no explicit exemplar API call needed.
        request_duration.record(event["latency_ms"], base)

        for token_type, count in (
            ("prompt",     event["prompt_tokens"]),
            ("completion", event["completion_tokens"]),
            ("cache_read", event["cache_read_tokens"]),
        ):
            request_token.add(count, {**base, "token_type": token_type})

        request_cost.add(event["cost_usd"], base)

        if event["status"] == "error":
            exception_count.add(
                1,
                {
                    **base,
                    "error_type":     event.get("error_type")     or "unknown",
                    "error_category": event.get("error_category") or "unknown",
                    "http_status":    str(event.get("http_status_code", 0)),
                },
            )
    except Exception as exc:
        logger.error("OTel record_metrics failed: %s", exc)


def record_self_metric(name: str, value: float, attrs: dict[str, str]) -> None:
    """Record one runner self-metric (NFR-014: observe the observer).

    Falls back to no-op when the OTel SDK isn't installed.
    """
    instrument = _SELF_METRIC_INSTRUMENTS.get(name)
    base = {"service": _PROCESS_SERVICE, "environment": _PROCESS_ENVIRONMENT, **attrs}
    try:
        if name == sc.METRIC_SELF_BATCH_DURATION and instrument is not None:
            instrument.record(value, base)
        elif name == sc.METRIC_SELF_PUBLISH_ERRORS and instrument is not None:
            instrument.add(int(value), base)
        elif name == sc.METRIC_SELF_QUEUE_DEPTH and instrument is not None:
            global _queue_depth_last
            delta = value - _queue_depth_last
            instrument.add(delta, base)
            _queue_depth_last = value
        else:
            logger.debug("self-metric %s not initialised — noop", name)
    except Exception as exc:
        logger.debug("self-metric %s failed: %s", name, exc)
