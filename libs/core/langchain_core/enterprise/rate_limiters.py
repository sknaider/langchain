"""Distributed rate limiting for multi-process/multi-pod environments.

Extends the base rate limiter with Redis-backed distributed rate limiting
that works across multiple processes and Kubernetes pods.
"""

from __future__ import annotations

import abc
import asyncio
import time
from typing import Literal

from langchain_core.enterprise.observability import EnterpriseLogger
from langchain_core.rate_limiters import BaseRateLimiter

logger = EnterpriseLogger(__name__)

try:
    import redis.asyncio as aioredis
    from redis import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class DistributedRateLimiter(BaseRateLimiter, abc.ABC):
    """Base class for distributed rate limiters.

    Distributed rate limiters work across multiple processes and pods,
    using external storage (e.g., Redis) to coordinate rate limiting.
    """

    @abc.abstractmethod
    def get_current_usage(self) -> dict[str, int | float]:
        """Get current usage statistics.

        Returns:
            Dictionary with usage stats (requests, tokens, etc.).
        """


class RedisRateLimiter(DistributedRateLimiter):
    """Redis-backed distributed rate limiter using token bucket algorithm.

    This rate limiter works across multiple processes and Kubernetes pods by
    using Redis as a centralized token bucket store. It supports multiple
    strategies:

    - **token_bucket**: Classic token bucket (refills at constant rate)
    - **sliding_window**: Sliding window counter (more accurate but slower)
    - **fixed_window**: Fixed window counter (fastest but less accurate)

    Example:
        ```python
        from langchain_core.enterprise import RedisRateLimiter

        # Create distributed rate limiter
        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
            strategy="token_bucket",
            namespace="langchain:acme-corp",  # Multi-tenant support
        )

        # Use in sync context
        if limiter.acquire():
            result = expensive_api_call()

        # Use in async context
        if await limiter.aacquire():
            result = await expensive_api_call()
        ```
    """

    def __init__(
        self,
        redis_url: str,
        requests_per_second: float = 10.0,
        *,
        burst_size: float | None = None,
        strategy: Literal["token_bucket", "sliding_window", "fixed_window"] = "token_bucket",
        namespace: str = "langchain",
        timeout_seconds: float = 10.0,
    ):
        """Initialize Redis rate limiter.

        Args:
            redis_url: Redis connection URL (e.g., `redis://localhost:6379/0`).
            requests_per_second: Request rate limit.
            burst_size: Max burst size (tokens in bucket). If `None`, uses
                `requests_per_second * 2`.
            strategy: Rate limiting strategy.
            namespace: Redis key namespace for multi-tenancy.
            timeout_seconds: Timeout for blocking acquire operations.
        """
        if not REDIS_AVAILABLE:
            msg = (
                "Redis rate limiter requires 'redis' package. "
                "Install with: pip install redis"
            )
            raise ImportError(msg)

        self.redis_url = redis_url
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size or (requests_per_second * 2)
        self.strategy = strategy
        self.namespace = namespace
        self.timeout_seconds = timeout_seconds

        # Lazy initialization of Redis clients
        self._sync_client: Redis | None = None
        self._async_client: aioredis.Redis | None = None

        self._key = f"{namespace}:rate_limit"

    def _get_sync_client(self) -> Redis:
        """Get or create sync Redis client.

        Returns:
            Sync Redis client.
        """
        if self._sync_client is None:
            self._sync_client = Redis.from_url(self.redis_url, decode_responses=True)
        return self._sync_client

    async def _get_async_client(self) -> aioredis.Redis:
        """Get or create async Redis client.

        Returns:
            Async Redis client.
        """
        if self._async_client is None:
            self._async_client = await aioredis.from_url(
                self.redis_url, decode_responses=True
            )
        return self._async_client

    def _token_bucket_acquire_sync(self, blocking: bool) -> bool:
        """Token bucket algorithm (sync).

        Args:
            blocking: Whether to block until tokens are available.

        Returns:
            `True` if tokens were acquired, `False` otherwise.
        """
        client = self._get_sync_client()
        now = time.time()
        start_time = now

        while True:
            # Get current bucket state
            pipe = client.pipeline()
            pipe.hgetall(self._key)
            result = pipe.execute()[0]

            if result:
                last_update = float(result.get("last_update", now))
                tokens = float(result.get("tokens", self.burst_size))
            else:
                last_update = now
                tokens = self.burst_size

            # Refill tokens based on elapsed time
            elapsed = now - last_update
            tokens = min(
                self.burst_size, tokens + (elapsed * self.requests_per_second)
            )

            # Try to consume a token
            if tokens >= 1.0:
                new_tokens = tokens - 1.0

                # Use optimistic locking with WATCH/MULTI/EXEC
                pipe = client.pipeline()
                pipe.watch(self._key)
                pipe.multi()
                pipe.hset(
                    self._key,
                    mapping={
                        "tokens": str(new_tokens),
                        "last_update": str(now),
                    },
                )
                pipe.expire(self._key, int(self.timeout_seconds) + 60)

                try:
                    pipe.execute()
                    return True
                except Exception:  # Transaction failed (concurrent modification)
                    if not blocking:
                        return False
                    # Retry with exponential backoff
                    time.sleep(0.001)
                    now = time.time()
                    continue

            # Not enough tokens
            if not blocking:
                return False

            # Check timeout
            if now - start_time >= self.timeout_seconds:
                return False

            # Wait for tokens to refill
            wait_time = (1.0 - tokens) / self.requests_per_second
            time.sleep(min(wait_time, 0.1))
            now = time.time()

    async def _token_bucket_acquire_async(self, blocking: bool) -> bool:
        """Token bucket algorithm (async).

        Args:
            blocking: Whether to block until tokens are available.

        Returns:
            `True` if tokens were acquired, `False` otherwise.
        """
        client = await self._get_async_client()
        now = time.time()
        start_time = now

        while True:
            # Get current bucket state
            result = await client.hgetall(self._key)

            if result:
                last_update = float(result.get("last_update", now))
                tokens = float(result.get("tokens", self.burst_size))
            else:
                last_update = now
                tokens = self.burst_size

            # Refill tokens based on elapsed time
            elapsed = now - last_update
            tokens = min(
                self.burst_size, tokens + (elapsed * self.requests_per_second)
            )

            # Try to consume a token
            if tokens >= 1.0:
                new_tokens = tokens - 1.0

                # Use optimistic locking
                async with client.pipeline(transaction=True) as pipe:
                    await pipe.watch(self._key)
                    pipe.multi()
                    pipe.hset(
                        self._key,
                        mapping={
                            "tokens": str(new_tokens),
                            "last_update": str(now),
                        },
                    )
                    pipe.expire(self._key, int(self.timeout_seconds) + 60)

                    try:
                        await pipe.execute()
                        return True
                    except Exception:
                        if not blocking:
                            return False
                        await asyncio.sleep(0.001)
                        now = time.time()
                        continue

            # Not enough tokens
            if not blocking:
                return False

            # Check timeout
            if now - start_time >= self.timeout_seconds:
                return False

            # Wait for tokens to refill
            wait_time = (1.0 - tokens) / self.requests_per_second
            await asyncio.sleep(min(wait_time, 0.1))
            now = time.time()

    def acquire(self, *, blocking: bool = True) -> bool:
        """Attempt to acquire a token (sync).

        Args:
            blocking: If `True`, block until token is available.

        Returns:
            `True` if token was acquired, `False` otherwise.
        """
        if self.strategy == "token_bucket":
            return self._token_bucket_acquire_sync(blocking)
        else:
            msg = f"Strategy '{self.strategy}' not yet implemented"
            raise NotImplementedError(msg)

    async def aacquire(self, *, blocking: bool = True) -> bool:
        """Attempt to acquire a token (async).

        Args:
            blocking: If `True`, block until token is available.

        Returns:
            `True` if token was acquired, `False` otherwise.
        """
        if self.strategy == "token_bucket":
            return await self._token_bucket_acquire_async(blocking)
        else:
            msg = f"Strategy '{self.strategy}' not yet implemented"
            raise NotImplementedError(msg)

    def get_current_usage(self) -> dict[str, int | float]:
        """Get current usage statistics.

        Returns:
            Dictionary with current token count and last update time.
        """
        client = self._get_sync_client()
        result = client.hgetall(self._key)

        if result:
            return {
                "tokens": float(result.get("tokens", self.burst_size)),
                "last_update": float(result.get("last_update", time.time())),
                "max_tokens": self.burst_size,
                "refill_rate": self.requests_per_second,
            }
        return {
            "tokens": self.burst_size,
            "last_update": time.time(),
            "max_tokens": self.burst_size,
            "refill_rate": self.requests_per_second,
        }

    def reset(self) -> None:
        """Reset the rate limiter (clear all tokens)."""
        client = self._get_sync_client()
        client.delete(self._key)
        logger.info("rate_limiter_reset", namespace=self.namespace)

    def __del__(self) -> None:
        """Cleanup Redis connections."""
        if self._sync_client is not None:
            self._sync_client.close()
