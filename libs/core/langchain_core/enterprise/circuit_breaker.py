"""Circuit breaker pattern for resilience and fault tolerance.

Implements the circuit breaker pattern to prevent cascading failures and allow
systems to recover from transient faults.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failure threshold exceeded, requests fail fast
- HALF_OPEN: Testing if system has recovered
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar, Generic

from langchain_core.enterprise.observability import EnterpriseLogger

logger = EnterpriseLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, name: str, *, retry_after_seconds: float):
        """Initialize circuit breaker error.

        Args:
            name: Circuit breaker name.
            retry_after_seconds: Seconds until circuit may close.
        """
        self.name = name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Circuit breaker '{name}' is OPEN. "
            f"Retry after {retry_after_seconds:.1f} seconds."
        )


class CircuitBreaker(Generic[T]):
    """Circuit breaker for fault tolerance.

    The circuit breaker monitors failures and opens the circuit when a threshold
    is exceeded, preventing further calls and allowing the system to recover.

    After a timeout period, the circuit enters HALF_OPEN state to test if the
    system has recovered.

    Example:
        ```python
        from langchain_core.enterprise import CircuitBreaker

        # Create circuit breaker
        circuit = CircuitBreaker(
            name="openai_api",
            failure_threshold=5,
            timeout_seconds=60,
            half_open_max_calls=3,
        )

        # Protect a function
        @circuit.protected
        async def call_openai(prompt: str) -> str:
            return await openai_client.chat(prompt)

        # Or use as context manager
        try:
            with circuit:
                result = call_expensive_api()
        except CircuitBreakerError:
            # Circuit is open, use fallback
            result = get_cached_result()
        ```
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        timeout_seconds: float = 60,
        half_open_max_calls: int = 1,
        on_open: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        expected_exceptions: tuple[type[Exception], ...] = (Exception,),
    ):
        """Initialize circuit breaker.

        Args:
            name: Circuit breaker name for logging.
            failure_threshold: Number of failures before opening circuit.
            timeout_seconds: Seconds to wait before trying HALF_OPEN.
            half_open_max_calls: Max calls allowed in HALF_OPEN state.
            on_open: Optional callback when circuit opens.
            on_close: Optional callback when circuit closes.
            expected_exceptions: Exceptions that count as failures.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        self.on_open = on_open
        self.on_close = on_close
        self.expected_exceptions = expected_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state.

        Returns:
            Current circuit state.
        """
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count.

        Returns:
            Number of consecutive failures.
        """
        with self._lock:
            return self._failure_count

    def _should_allow_request(self) -> bool:
        """Check if request should be allowed.

        Returns:
            `True` if request should proceed, `False` otherwise.
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if timeout has elapsed
                if (
                    self._last_failure_time is not None
                    and time.time() - self._last_failure_time >= self.timeout_seconds
                ):
                    logger.info(
                        "circuit_breaker_half_open",
                        name=self.name,
                        timeout_seconds=self.timeout_seconds,
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    return True
                return False

            # HALF_OPEN state
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    def _record_success(self) -> None:
        """Record successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._close_circuit()
            else:
                self._failure_count = 0

    def _record_failure(self) -> None:
        """Record failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._open_circuit()
            elif self._failure_count >= self.failure_threshold:
                self._open_circuit()

    def _open_circuit(self) -> None:
        """Open the circuit (must hold lock)."""
        self._state = CircuitState.OPEN
        self._success_count = 0
        logger.error(
            "circuit_breaker_opened",
            name=self.name,
            failure_count=self._failure_count,
            failure_threshold=self.failure_threshold,
        )
        if self.on_open:
            self.on_open()

    def _close_circuit(self) -> None:
        """Close the circuit (must hold lock)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info("circuit_breaker_closed", name=self.name)
        if self.on_close:
            self.on_close()

    def __enter__(self) -> CircuitBreaker:
        """Enter context manager.

        Returns:
            This circuit breaker.

        Raises:
            CircuitBreakerError: If circuit is open.
        """
        if not self._should_allow_request():
            retry_after = self.timeout_seconds
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                retry_after = max(0, self.timeout_seconds - elapsed)
            raise CircuitBreakerError(self.name, retry_after_seconds=retry_after)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context manager.

        Args:
            exc_type: Exception type if raised.
            exc_val: Exception value if raised.
            exc_tb: Exception traceback if raised.

        Returns:
            `False` to propagate exceptions.
        """
        if exc_type is None:
            self._record_success()
        elif issubclass(exc_type, self.expected_exceptions):
            self._record_failure()
        return False

    def protected(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to protect a function with circuit breaker.

        Args:
            func: Function to protect.

        Returns:
            Protected function.
        """
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> T:
                if not self._should_allow_request():
                    retry_after = self.timeout_seconds
                    if self._last_failure_time:
                        elapsed = time.time() - self._last_failure_time
                        retry_after = max(0, self.timeout_seconds - elapsed)
                    raise CircuitBreakerError(self.name, retry_after_seconds=retry_after)

                try:
                    result = await func(*args, **kwargs)
                    self._record_success()
                    return result
                except self.expected_exceptions:
                    self._record_failure()
                    raise

            return async_wrapper  # type: ignore[return-value]
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> T:
                if not self._should_allow_request():
                    retry_after = self.timeout_seconds
                    if self._last_failure_time:
                        elapsed = time.time() - self._last_failure_time
                        retry_after = max(0, self.timeout_seconds - elapsed)
                    raise CircuitBreakerError(self.name, retry_after_seconds=retry_after)

                try:
                    result = func(*args, **kwargs)
                    self._record_success()
                    return result
                except self.expected_exceptions:
                    self._record_failure()
                    raise

            return sync_wrapper  # type: ignore[return-value]

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            logger.info("circuit_breaker_reset", name=self.name)
            self._close_circuit()
