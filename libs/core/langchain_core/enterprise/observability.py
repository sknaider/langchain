"""Enterprise observability with structured logging, metrics, and distributed tracing.

This module provides:
- Structured logging with correlation IDs
- Prometheus-compatible metrics
- OpenTelemetry integration
- Business metrics tracking (cost, latency, errors)
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict

try:
    import structlog

    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False

try:
    from prometheus_client import Counter, Gauge, Histogram, Summary

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


# Context variable for correlation ID (thread-safe)
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str:
    """Get the current correlation ID, creating one if it doesn't exist.

    Returns:
        The correlation ID for the current context.
    """
    correlation_id = _correlation_id.get()
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
        _correlation_id.set(correlation_id)
    return correlation_id


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context.

    Args:
        correlation_id: The correlation ID to set.
    """
    _correlation_id.set(correlation_id)


@contextmanager
def correlation_context(correlation_id: str | None = None):
    """Context manager for correlation ID.

    Args:
        correlation_id: Optional correlation ID. If not provided, a new one is
            generated.

    Yields:
        The correlation ID for this context.
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    token = _correlation_id.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _correlation_id.reset(token)


class LogLevel(str, Enum):
    """Log levels for enterprise logging."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogEvent(TypedDict, total=False):
    """Structured log event."""

    timestamp: str
    level: str
    message: str
    correlation_id: str
    tenant_id: str | None
    user_id: str | None
    operation: str
    duration_ms: float | None
    model: str | None
    tokens_used: int | None
    cost_usd: float | None
    error: str | None
    trace_id: str | None
    span_id: str | None


class EnterpriseLogger:
    """Enterprise-grade structured logger with correlation IDs and metadata.

    This logger provides structured logging with automatic correlation ID injection,
    tenant/user context, and integration with OpenTelemetry.

    Example:
        ```python
        from langchain_core.enterprise import EnterpriseLogger

        logger = EnterpriseLogger("my_service")

        logger.info(
            "llm_invocation",
            model="gpt-4",
            tokens_used=150,
            cost_usd=0.003,
            tenant_id="acme-corp",
        )
        ```
    """

    def __init__(self, name: str, *, use_structlog: bool = True):
        """Initialize enterprise logger.

        Args:
            name: Logger name (typically module or service name).
            use_structlog: Whether to use structlog if available. If `False` or
                structlog is not installed, uses standard logging.
        """
        self.name = name
        self.use_structlog = use_structlog and STRUCTLOG_AVAILABLE

        if self.use_structlog:
            self._logger = structlog.get_logger(name)
        else:
            self._logger = logging.getLogger(name)

    def _enrich_event(self, **kwargs: Any) -> dict[str, Any]:
        """Enrich log event with correlation ID and tracing context.

        Args:
            **kwargs: Log event data.

        Returns:
            Enriched log event with additional context.
        """
        event = dict(kwargs)
        event["timestamp"] = datetime.utcnow().isoformat()
        event["correlation_id"] = get_correlation_id()

        # Add OpenTelemetry context if available
        if OTEL_AVAILABLE:
            span = trace.get_current_span()
            if span.is_recording():
                ctx = span.get_span_context()
                event["trace_id"] = format(ctx.trace_id, "032x")
                event["span_id"] = format(ctx.span_id, "016x")

        return event

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message.

        Args:
            message: Log message.
            **kwargs: Additional structured data.
        """
        event = self._enrich_event(message=message, **kwargs)
        if self.use_structlog:
            self._logger.debug(**event)
        else:
            self._logger.debug(f"{message} | {kwargs}", extra=event)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message.

        Args:
            message: Log message.
            **kwargs: Additional structured data.
        """
        event = self._enrich_event(message=message, **kwargs)
        if self.use_structlog:
            self._logger.info(**event)
        else:
            self._logger.info(f"{message} | {kwargs}", extra=event)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message.

        Args:
            message: Log message.
            **kwargs: Additional structured data.
        """
        event = self._enrich_event(message=message, **kwargs)
        if self.use_structlog:
            self._logger.warning(**event)
        else:
            self._logger.warning(f"{message} | {kwargs}", extra=event)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message.

        Args:
            message: Log message.
            **kwargs: Additional structured data.
        """
        event = self._enrich_event(message=message, **kwargs)
        if self.use_structlog:
            self._logger.error(**event)
        else:
            self._logger.error(f"{message} | {kwargs}", extra=event)

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message.

        Args:
            message: Log message.
            **kwargs: Additional structured data.
        """
        event = self._enrich_event(message=message, **kwargs)
        if self.use_structlog:
            self._logger.critical(**event)
        else:
            self._logger.critical(f"{message} | {kwargs}", extra=event)


class MetricsCollector:
    """Prometheus-compatible metrics collector for LangChain operations.

    Tracks business metrics including:
    - Request counts and rates
    - Latency distributions
    - Token usage
    - Costs
    - Error rates

    Example:
        ```python
        from langchain_core.enterprise import MetricsCollector

        metrics = MetricsCollector()

        with metrics.track_llm_call(model="gpt-4", tenant_id="acme"):
            result = llm.invoke("Hello")

        metrics.record_tokens(model="gpt-4", tokens=150, tenant_id="acme")
        metrics.record_cost(model="gpt-4", cost_usd=0.003, tenant_id="acme")
        ```
    """

    def __init__(self, *, namespace: str = "langchain"):
        """Initialize metrics collector.

        Args:
            namespace: Metrics namespace prefix.
        """
        self.namespace = namespace
        self.enabled = PROMETHEUS_AVAILABLE

        if self.enabled:
            # Request metrics
            self.llm_requests = Counter(
                f"{namespace}_llm_requests_total",
                "Total LLM requests",
                ["model", "tenant_id", "status"],
            )

            self.llm_latency = Histogram(
                f"{namespace}_llm_latency_seconds",
                "LLM request latency in seconds",
                ["model", "tenant_id"],
                buckets=(
                    0.005,
                    0.01,
                    0.025,
                    0.05,
                    0.075,
                    0.1,
                    0.25,
                    0.5,
                    0.75,
                    1.0,
                    2.5,
                    5.0,
                    7.5,
                    10.0,
                    float("inf"),
                ),
            )

            # Token metrics
            self.llm_tokens = Counter(
                f"{namespace}_llm_tokens_total",
                "Total LLM tokens used",
                ["model", "tenant_id", "token_type"],
            )

            # Cost metrics
            self.llm_cost = Counter(
                f"{namespace}_llm_cost_usd_total",
                "Total LLM cost in USD",
                ["model", "tenant_id"],
            )

            # Error metrics
            self.llm_errors = Counter(
                f"{namespace}_llm_errors_total",
                "Total LLM errors",
                ["model", "tenant_id", "error_type"],
            )

            # Active requests
            self.active_requests = Gauge(
                f"{namespace}_active_requests",
                "Number of active LLM requests",
                ["model", "tenant_id"],
            )

    @contextmanager
    def track_llm_call(
        self,
        model: str,
        *,
        tenant_id: str = "default",
    ):
        """Context manager to track LLM call metrics.

        Args:
            model: Model name.
            tenant_id: Tenant identifier.

        Yields:
            None
        """
        if not self.enabled:
            yield
            return

        start_time = time.time()
        self.active_requests.labels(model=model, tenant_id=tenant_id).inc()

        try:
            yield
            status = "success"
        except Exception as e:
            status = "error"
            error_type = type(e).__name__
            self.llm_errors.labels(
                model=model, tenant_id=tenant_id, error_type=error_type
            ).inc()
            raise
        finally:
            duration = time.time() - start_time
            self.llm_latency.labels(model=model, tenant_id=tenant_id).observe(duration)
            self.llm_requests.labels(model=model, tenant_id=tenant_id, status=status).inc()
            self.active_requests.labels(model=model, tenant_id=tenant_id).dec()

    def record_tokens(
        self,
        model: str,
        tokens: int,
        *,
        token_type: str = "total",
        tenant_id: str = "default",
    ) -> None:
        """Record token usage.

        Args:
            model: Model name.
            tokens: Number of tokens.
            token_type: Type of tokens (`'input'`, `'output'`, or `'total'`).
            tenant_id: Tenant identifier.
        """
        if self.enabled:
            self.llm_tokens.labels(
                model=model, tenant_id=tenant_id, token_type=token_type
            ).inc(tokens)

    def record_cost(
        self,
        model: str,
        cost_usd: float,
        *,
        tenant_id: str = "default",
    ) -> None:
        """Record cost in USD.

        Args:
            model: Model name.
            cost_usd: Cost in USD.
            tenant_id: Tenant identifier.
        """
        if self.enabled:
            self.llm_cost.labels(model=model, tenant_id=tenant_id).inc(cost_usd)


# Global instances
logger = EnterpriseLogger(__name__)
metrics = MetricsCollector()
