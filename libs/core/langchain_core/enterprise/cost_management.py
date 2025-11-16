"""Cost management and tracking for LLM operations.

Tracks costs, enforces budgets, and provides cost optimization insights.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from langchain_core.enterprise.observability import EnterpriseLogger
from langchain_core.enterprise.tenancy import get_current_tenant

logger = EnterpriseLogger(__name__)


class CostLimitExceededError(Exception):
    """Raised when cost limit is exceeded."""

    def __init__(
        self,
        limit_usd: float,
        current_usd: float,
        *,
        period: str = "day",
        tenant_id: str | None = None,
    ):
        """Initialize cost limit exceeded error.

        Args:
            limit_usd: Cost limit in USD.
            current_usd: Current cost in USD.
            period: Time period for the limit.
            tenant_id: Tenant identifier.
        """
        self.limit_usd = limit_usd
        self.current_usd = current_usd
        self.period = period
        self.tenant_id = tenant_id

        tenant_msg = f" for tenant '{tenant_id}'" if tenant_id else ""
        super().__init__(
            f"Cost limit exceeded{tenant_msg}: "
            f"${current_usd:.4f} / ${limit_usd:.4f} per {period}"
        )


@dataclass
class CostEntry:
    """Single cost entry."""

    timestamp: datetime
    model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    tenant_id: str | None = None
    user_id: str | None = None
    operation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CostSummary:
    """Cost summary for a time period."""

    total_cost_usd: float
    total_tokens_input: int
    total_tokens_output: int
    total_requests: int
    cost_by_model: dict[str, float]
    tokens_by_model: dict[str, int]
    period_start: datetime
    period_end: datetime


class CostTracker:
    """Track and enforce cost limits for LLM operations.

    Example:
        ```python
        from langchain_core.enterprise import CostTracker

        # Create cost tracker with daily limit
        tracker = CostTracker(
            daily_limit_usd=100.0,
            alert_threshold=0.8,  # Alert at 80%
        )

        # Track a request
        estimated_cost = tracker.estimate_cost("gpt-4", tokens=1000)

        with tracker.track_request("gpt-4", tenant_id="acme-corp"):
            result = llm.invoke("Hello")
            tracker.record_cost(
                model="gpt-4",
                tokens_input=10,
                tokens_output=50,
                cost_usd=0.003,
            )

        # Get cost summary
        summary = tracker.get_summary(hours=24)
        print(f"Last 24h: ${summary.total_cost_usd:.2f}")
        ```
    """

    # Approximate pricing (USD per 1K tokens) - update with actual rates
    MODEL_PRICING = {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "claude-3-opus": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    }

    def __init__(
        self,
        *,
        daily_limit_usd: float | None = None,
        hourly_limit_usd: float | None = None,
        alert_threshold: float = 0.8,
        on_limit_exceeded: Callable[[CostLimitExceededError], None] | None = None,
        on_alert: Callable[[float, float], None] | None = None,
    ):
        """Initialize cost tracker.

        Args:
            daily_limit_usd: Daily cost limit in USD.
            hourly_limit_usd: Hourly cost limit in USD.
            alert_threshold: Threshold (0.0-1.0) for sending alerts.
            on_limit_exceeded: Callback when limit is exceeded.
            on_alert: Callback when alert threshold is reached.
        """
        self.daily_limit_usd = daily_limit_usd
        self.hourly_limit_usd = hourly_limit_usd
        self.alert_threshold = alert_threshold
        self.on_limit_exceeded = on_limit_exceeded
        self.on_alert = on_alert

        self._entries: list[CostEntry] = []
        self._lock = threading.Lock()
        self._alerted = False

    def estimate_cost(
        self,
        model: str,
        *,
        tokens: int | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
    ) -> float:
        """Estimate cost for a request.

        Args:
            model: Model name.
            tokens: Total tokens (if input/output not specified separately).
            tokens_input: Input tokens.
            tokens_output: Output tokens.

        Returns:
            Estimated cost in USD.
        """
        pricing = self.MODEL_PRICING.get(model)
        if not pricing:
            logger.warning("unknown_model_pricing", model=model)
            return 0.0

        if tokens is not None:
            # Assume 20% input, 80% output as rough estimate
            tokens_input = int(tokens * 0.2)
            tokens_output = int(tokens * 0.8)

        tokens_input = tokens_input or 0
        tokens_output = tokens_output or 0

        cost_usd = (tokens_input / 1000 * pricing["input"]) + (
            tokens_output / 1000 * pricing["output"]
        )

        return cost_usd

    def record_cost(
        self,
        model: str,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        operation: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a cost entry.

        Args:
            model: Model name.
            tokens_input: Input tokens.
            tokens_output: Output tokens.
            cost_usd: Actual cost in USD.
            tenant_id: Tenant identifier.
            user_id: User identifier.
            operation: Operation name.
            metadata: Additional metadata.
        """
        # Get tenant from context if not provided
        if tenant_id is None:
            tenant = get_current_tenant()
            if tenant:
                tenant_id = tenant.tenant_id

        entry = CostEntry(
            timestamp=datetime.utcnow(),
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
            tenant_id=tenant_id,
            user_id=user_id,
            operation=operation,
            metadata=metadata or {},
        )

        with self._lock:
            self._entries.append(entry)

            # Check limits
            self._check_limits(tenant_id)

        logger.info(
            "cost_recorded",
            model=model,
            cost_usd=cost_usd,
            tokens_total=tokens_input + tokens_output,
            tenant_id=tenant_id,
        )

    def _check_limits(self, tenant_id: str | None = None) -> None:
        """Check if cost limits are exceeded (must hold lock).

        Args:
            tenant_id: Tenant identifier to check limits for.

        Raises:
            CostLimitExceededError: If limit is exceeded.
        """
        now = datetime.utcnow()

        # Check hourly limit
        if self.hourly_limit_usd is not None:
            hour_ago = now - timedelta(hours=1)
            hourly_cost = self._get_cost_in_period(
                hour_ago, now, tenant_id=tenant_id
            )

            if hourly_cost >= self.hourly_limit_usd:
                error = CostLimitExceededError(
                    self.hourly_limit_usd,
                    hourly_cost,
                    period="hour",
                    tenant_id=tenant_id,
                )
                if self.on_limit_exceeded:
                    self.on_limit_exceeded(error)
                raise error

            self._check_alert(hourly_cost, self.hourly_limit_usd)

        # Check daily limit
        if self.daily_limit_usd is not None:
            day_ago = now - timedelta(days=1)
            daily_cost = self._get_cost_in_period(
                day_ago, now, tenant_id=tenant_id
            )

            if daily_cost >= self.daily_limit_usd:
                error = CostLimitExceededError(
                    self.daily_limit_usd,
                    daily_cost,
                    period="day",
                    tenant_id=tenant_id,
                )
                if self.on_limit_exceeded:
                    self.on_limit_exceeded(error)
                raise error

            self._check_alert(daily_cost, self.daily_limit_usd)

    def _check_alert(self, current: float, limit: float) -> None:
        """Check if alert threshold is reached.

        Args:
            current: Current cost.
            limit: Cost limit.
        """
        if current >= limit * self.alert_threshold and not self._alerted:
            self._alerted = True
            logger.warning(
                "cost_alert_threshold_reached",
                current_usd=current,
                limit_usd=limit,
                threshold=self.alert_threshold,
            )
            if self.on_alert:
                self.on_alert(current, limit)

    def _get_cost_in_period(
        self,
        start: datetime,
        end: datetime,
        *,
        tenant_id: str | None = None,
    ) -> float:
        """Get total cost in a time period.

        Args:
            start: Period start.
            end: Period end.
            tenant_id: Optional tenant filter.

        Returns:
            Total cost in USD.
        """
        total = 0.0
        for entry in self._entries:
            if start <= entry.timestamp <= end:
                if tenant_id is None or entry.tenant_id == tenant_id:
                    total += entry.cost_usd
        return total

    def get_summary(
        self,
        *,
        hours: int | None = None,
        days: int | None = None,
        tenant_id: str | None = None,
    ) -> CostSummary:
        """Get cost summary for a time period.

        Args:
            hours: Number of hours to look back.
            days: Number of days to look back.
            tenant_id: Optional tenant filter.

        Returns:
            Cost summary.
        """
        now = datetime.utcnow()

        if hours is not None:
            start = now - timedelta(hours=hours)
        elif days is not None:
            start = now - timedelta(days=days)
        else:
            start = now - timedelta(days=1)  # Default to 24h

        total_cost = 0.0
        total_tokens_input = 0
        total_tokens_output = 0
        total_requests = 0
        cost_by_model: dict[str, float] = {}
        tokens_by_model: dict[str, int] = {}

        with self._lock:
            for entry in self._entries:
                if start <= entry.timestamp <= now:
                    if tenant_id is None or entry.tenant_id == tenant_id:
                        total_cost += entry.cost_usd
                        total_tokens_input += entry.tokens_input
                        total_tokens_output += entry.tokens_output
                        total_requests += 1

                        cost_by_model[entry.model] = (
                            cost_by_model.get(entry.model, 0.0) + entry.cost_usd
                        )
                        tokens_by_model[entry.model] = tokens_by_model.get(
                            entry.model, 0
                        ) + (entry.tokens_input + entry.tokens_output)

        return CostSummary(
            total_cost_usd=total_cost,
            total_tokens_input=total_tokens_input,
            total_tokens_output=total_tokens_output,
            total_requests=total_requests,
            cost_by_model=cost_by_model,
            tokens_by_model=tokens_by_model,
            period_start=start,
            period_end=now,
        )

    @contextmanager
    def track_request(
        self,
        model: str,
        *,
        tenant_id: str | None = None,
    ):
        """Context manager to track a request.

        Args:
            model: Model name.
            tenant_id: Tenant identifier.

        Yields:
            None

        Raises:
            CostLimitExceededError: If cost limit would be exceeded.
        """
        # Check if we can proceed
        with self._lock:
            self._check_limits(tenant_id)

        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            logger.debug(
                "request_tracked",
                model=model,
                duration_ms=duration * 1000,
                tenant_id=tenant_id,
            )
