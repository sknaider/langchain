"""Tests for cost management."""

import pytest

from langchain_core.enterprise.cost_management import (
    CostTracker,
    CostLimitExceededError,
)


def test_cost_estimation():
    """Test cost estimation."""
    tracker = CostTracker()

    # GPT-4 estimation
    cost = tracker.estimate_cost("gpt-4", tokens_input=100, tokens_output=50)
    assert cost > 0
    assert isinstance(cost, float)


def test_cost_recording():
    """Test cost recording."""
    tracker = CostTracker()

    tracker.record_cost(
        model="gpt-4",
        tokens_input=100,
        tokens_output=50,
        cost_usd=0.009,
        tenant_id="test-tenant",
    )

    summary = tracker.get_summary(hours=1)
    assert summary.total_cost_usd == 0.009
    assert summary.total_tokens_input == 100
    assert summary.total_tokens_output == 50
    assert summary.total_requests == 1


def test_daily_limit_enforcement():
    """Test daily cost limit enforcement."""
    tracker = CostTracker(daily_limit_usd=10.0)

    # Add costs up to limit
    for _ in range(5):
        tracker.record_cost(
            model="gpt-4",
            tokens_input=100,
            tokens_output=100,
            cost_usd=2.0,
        )

    # Next record should raise exception
    with pytest.raises(CostLimitExceededError) as exc_info:
        tracker.record_cost(
            model="gpt-4",
            tokens_input=100,
            tokens_output=100,
            cost_usd=1.0,
        )

    assert exc_info.value.limit_usd == 10.0


def test_cost_summary_by_model():
    """Test cost summary grouped by model."""
    tracker = CostTracker()

    tracker.record_cost(
        model="gpt-4", tokens_input=100, tokens_output=100, cost_usd=0.009
    )
    tracker.record_cost(
        model="gpt-3.5-turbo", tokens_input=100, tokens_output=100, cost_usd=0.0002
    )

    summary = tracker.get_summary(hours=1)

    assert "gpt-4" in summary.cost_by_model
    assert "gpt-3.5-turbo" in summary.cost_by_model
    assert summary.cost_by_model["gpt-4"] > summary.cost_by_model["gpt-3.5-turbo"]


def test_cost_tracker_context_manager():
    """Test cost tracker context manager."""
    tracker = CostTracker(daily_limit_usd=100.0)

    with tracker.track_request("gpt-4"):
        # Request tracking should not raise
        pass

    # Should work fine within limit
    tracker.record_cost(
        model="gpt-4", tokens_input=10, tokens_output=10, cost_usd=0.001
    )
