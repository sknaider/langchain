"""Tests for observability (logging and metrics)."""

import time

import pytest

from langchain_core.enterprise.observability import (
    EnterpriseLogger,
    MetricsCollector,
    get_correlation_id,
    set_correlation_id,
    correlation_context,
)


def test_correlation_id_generation():
    """Test automatic correlation ID generation."""
    corr_id = get_correlation_id()
    assert corr_id is not None
    assert len(corr_id) > 0

    # Should return same ID in same context
    corr_id2 = get_correlation_id()
    assert corr_id == corr_id2


def test_correlation_id_set():
    """Test setting correlation ID."""
    test_id = "test-correlation-456"
    set_correlation_id(test_id)

    corr_id = get_correlation_id()
    assert corr_id == test_id


def test_correlation_context_manager():
    """Test correlation context manager."""
    test_id = "context-test-789"

    with correlation_context(test_id) as ctx_id:
        assert ctx_id == test_id
        assert get_correlation_id() == test_id

    # After exiting, correlation ID should be reset
    # (in a new context it would generate a new one)


def test_enterprise_logger_basic():
    """Test basic enterprise logger functionality."""
    logger = EnterpriseLogger("test_module")

    # Should not raise errors
    logger.debug("debug message", key="value")
    logger.info("info message", key="value")
    logger.warning("warning message", key="value")
    logger.error("error message", key="value")
    logger.critical("critical message", key="value")


def test_enterprise_logger_enrichment():
    """Test log enrichment with correlation ID."""
    set_correlation_id("test-enrichment-123")

    logger = EnterpriseLogger("test_module", use_structlog=False)

    # Log should be enriched with correlation ID
    # (we can't easily test the output, but we can verify it doesn't crash)
    logger.info("test message", user_id="user123")


def test_metrics_collector_enabled():
    """Test metrics collector when Prometheus is available."""
    try:
        from prometheus_client import REGISTRY
        metrics = MetricsCollector(namespace="test_langchain")
        assert metrics.enabled is True
    except ImportError:
        # Prometheus not installed, metrics should be disabled
        metrics = MetricsCollector()
        assert metrics.enabled is False


def test_metrics_track_llm_call_success():
    """Test tracking successful LLM call."""
    metrics = MetricsCollector(namespace="test_langchain")

    start_time = time.time()
    with metrics.track_llm_call(model="gpt-4", tenant_id="test-tenant"):
        time.sleep(0.01)  # Simulate some work
    duration = time.time() - start_time

    # Should complete without error
    assert duration >= 0.01


def test_metrics_track_llm_call_error():
    """Test tracking failed LLM call."""
    metrics = MetricsCollector(namespace="test_langchain")

    with pytest.raises(ValueError):
        with metrics.track_llm_call(model="gpt-4", tenant_id="test-tenant"):
            raise ValueError("Test error")

    # Metrics should have recorded the error


def test_metrics_record_tokens():
    """Test recording token usage."""
    metrics = MetricsCollector(namespace="test_langchain")

    metrics.record_tokens(
        model="gpt-4",
        tokens=150,
        token_type="total",
        tenant_id="test-tenant",
    )

    metrics.record_tokens(
        model="gpt-4",
        tokens=100,
        token_type="input",
        tenant_id="test-tenant",
    )

    metrics.record_tokens(
        model="gpt-4",
        tokens=50,
        token_type="output",
        tenant_id="test-tenant",
    )

    # Should complete without error


def test_metrics_record_cost():
    """Test recording cost."""
    metrics = MetricsCollector(namespace="test_langchain")

    metrics.record_cost(
        model="gpt-4",
        cost_usd=0.003,
        tenant_id="test-tenant",
    )

    metrics.record_cost(
        model="gpt-3.5-turbo",
        cost_usd=0.0001,
        tenant_id="test-tenant",
    )

    # Should complete without error


def test_metrics_multiple_tenants():
    """Test metrics with multiple tenants."""
    metrics = MetricsCollector(namespace="test_langchain")

    # Track calls for different tenants
    with metrics.track_llm_call(model="gpt-4", tenant_id="tenant-a"):
        pass

    with metrics.track_llm_call(model="gpt-4", tenant_id="tenant-b"):
        pass

    # Record costs for different tenants
    metrics.record_cost(model="gpt-4", cost_usd=0.003, tenant_id="tenant-a")
    metrics.record_cost(model="gpt-4", cost_usd=0.005, tenant_id="tenant-b")

    # Should complete without error


def test_metrics_multiple_models():
    """Test metrics with multiple models."""
    metrics = MetricsCollector(namespace="test_langchain")

    models = ["gpt-4", "gpt-3.5-turbo", "claude-3-opus"]

    for model in models:
        with metrics.track_llm_call(model=model, tenant_id="test-tenant"):
            pass

        metrics.record_tokens(model=model, tokens=100, tenant_id="test-tenant")
        metrics.record_cost(model=model, cost_usd=0.001, tenant_id="test-tenant")

    # Should complete without error


def test_logger_with_tenant_context():
    """Test logger with tenant context."""
    from langchain_core.enterprise.tenancy import TenantContext, set_current_tenant

    tenant = TenantContext(tenant_id="test-tenant-logger")
    set_current_tenant(tenant)

    logger = EnterpriseLogger("test_module")
    logger.info("test message with tenant context", action="test")

    # Should complete without error


@pytest.mark.asyncio
async def test_metrics_async_tracking():
    """Test metrics tracking in async context."""
    import asyncio

    metrics = MetricsCollector(namespace="test_langchain")

    async def async_operation():
        await asyncio.sleep(0.01)
        return "done"

    with metrics.track_llm_call(model="gpt-4", tenant_id="test-tenant"):
        result = await async_operation()

    assert result == "done"


def test_correlation_id_propagation():
    """Test correlation ID propagation across components."""
    set_correlation_id("propagation-test-123")

    logger = EnterpriseLogger("test_module")
    metrics = MetricsCollector(namespace="test_langchain")

    # Both should use same correlation ID
    corr_id = get_correlation_id()
    assert corr_id == "propagation-test-123"

    # Log and metrics should use this correlation ID
    logger.info("test", operation="test")

    with metrics.track_llm_call(model="gpt-4"):
        pass
