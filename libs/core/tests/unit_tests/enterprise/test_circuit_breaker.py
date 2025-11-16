"""Tests for circuit breaker pattern."""

import asyncio
import time

import pytest

from langchain_core.enterprise.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
)


def test_circuit_breaker_closed_state():
    """Test circuit breaker in CLOSED state."""
    circuit = CircuitBreaker("test", failure_threshold=3, timeout_seconds=1)

    assert circuit.state == CircuitState.CLOSED
    assert circuit.failure_count == 0

    # Successful call
    with circuit:
        result = "success"

    assert result == "success"
    assert circuit.state == CircuitState.CLOSED


def test_circuit_breaker_opens_on_failures():
    """Test circuit breaker opens after failure threshold."""
    circuit = CircuitBreaker("test", failure_threshold=3, timeout_seconds=1)

    # Record failures
    for _ in range(3):
        try:
            with circuit:
                raise ValueError("Test error")
        except ValueError:
            pass

    # Circuit should be open
    assert circuit.state == CircuitState.OPEN
    assert circuit.failure_count == 3

    # Next call should fail fast
    with pytest.raises(CircuitBreakerError):
        with circuit:
            pass


def test_circuit_breaker_half_open_recovery():
    """Test circuit breaker recovers through HALF_OPEN state."""
    circuit = CircuitBreaker(
        "test",
        failure_threshold=2,
        timeout_seconds=0.1,  # Short timeout
        half_open_max_calls=2,
    )

    # Open the circuit
    for _ in range(2):
        try:
            with circuit:
                raise ValueError("Test error")
        except ValueError:
            pass

    assert circuit.state == CircuitState.OPEN

    # Wait for timeout
    time.sleep(0.15)

    # Should transition to HALF_OPEN
    with circuit:
        result = "success"

    assert result == "success"

    # One more success should close it
    with circuit:
        result2 = "success"

    assert result2 == "success"
    assert circuit.state == CircuitState.CLOSED


def test_circuit_breaker_decorator():
    """Test circuit breaker as decorator."""
    circuit = CircuitBreaker("test", failure_threshold=2)

    call_count = 0

    @circuit.protected
    def failing_function():
        nonlocal call_count
        call_count += 1
        raise ValueError("Test error")

    # Call twice to open circuit
    for _ in range(2):
        with pytest.raises(ValueError):
            failing_function()

    assert call_count == 2
    assert circuit.state == CircuitState.OPEN

    # Next call should fail fast without calling function
    with pytest.raises(CircuitBreakerError):
        failing_function()

    assert call_count == 2  # Function not called


@pytest.mark.asyncio
async def test_circuit_breaker_async():
    """Test circuit breaker with async functions."""
    circuit = CircuitBreaker("test", failure_threshold=2)

    @circuit.protected
    async def async_function():
        await asyncio.sleep(0.01)
        return "success"

    result = await async_function()
    assert result == "success"
    assert circuit.state == CircuitState.CLOSED


def test_circuit_breaker_callbacks():
    """Test circuit breaker open/close callbacks."""
    opened = False
    closed = False

    def on_open():
        nonlocal opened
        opened = True

    def on_close():
        nonlocal closed
        closed = True

    circuit = CircuitBreaker(
        "test",
        failure_threshold=2,
        timeout_seconds=0.1,
        half_open_max_calls=1,
        on_open=on_open,
        on_close=on_close,
    )

    # Open circuit
    for _ in range(2):
        try:
            with circuit:
                raise ValueError("Test error")
        except ValueError:
            pass

    assert opened is True
    assert closed is False
    assert circuit.state == CircuitState.OPEN

    # Wait and recover
    time.sleep(0.15)
    with circuit:
        pass

    assert closed is True
    assert circuit.state == CircuitState.CLOSED
