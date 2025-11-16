"""Tests for distributed rate limiting."""

import time

import pytest


# Note: These tests primarily test the interface and logic.
# Redis-based tests require a Redis instance and are marked appropriately.


def test_redis_rate_limiter_creation():
    """Test creating Redis rate limiter (without actual Redis connection)."""
    try:
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        # Should be able to create instance (connection is lazy)
        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
        )

        assert limiter.requests_per_second == 10
        assert limiter.burst_size == 20  # Default is 2x requests_per_second
        assert limiter.namespace == "langchain"

    except ImportError:
        pytest.skip("Redis package not installed")


def test_redis_rate_limiter_custom_burst():
    """Test Redis rate limiter with custom burst size."""
    try:
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
            burst_size=50,
        )

        assert limiter.burst_size == 50

    except ImportError:
        pytest.skip("Redis package not installed")


def test_redis_rate_limiter_namespace():
    """Test Redis rate limiter with custom namespace."""
    try:
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
            namespace="langchain:tenant-123",
        )

        assert limiter.namespace == "langchain:tenant-123"
        assert limiter._key == "langchain:tenant-123:rate_limit"

    except ImportError:
        pytest.skip("Redis package not installed")


def test_redis_rate_limiter_strategies():
    """Test different rate limiting strategies."""
    try:
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        # Token bucket (default)
        limiter_token = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            strategy="token_bucket",
        )
        assert limiter_token.strategy == "token_bucket"

        # Other strategies should be creatable but not yet implemented
        limiter_sliding = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            strategy="sliding_window",
        )
        assert limiter_sliding.strategy == "sliding_window"

    except ImportError:
        pytest.skip("Redis package not installed")


def test_rate_limiter_import_error():
    """Test error when Redis is not installed."""
    import sys
    import importlib

    # Temporarily hide redis module
    redis_module = sys.modules.get('redis')
    redis_asyncio_module = sys.modules.get('redis.asyncio')

    try:
        if redis_module:
            sys.modules['redis'] = None
        if redis_asyncio_module:
            sys.modules['redis.asyncio'] = None

        # Reload the module to trigger ImportError
        from langchain_core.enterprise import rate_limiters
        importlib.reload(rate_limiters)

        # Should raise ImportError when trying to create Redis limiter
        with pytest.raises(ImportError, match="Redis rate limiter requires 'redis'"):
            from langchain_core.enterprise.rate_limiters import RedisRateLimiter
            RedisRateLimiter(redis_url="redis://localhost:6379")

    finally:
        # Restore modules
        if redis_module is not None:
            sys.modules['redis'] = redis_module
        if redis_asyncio_module is not None:
            sys.modules['redis.asyncio'] = redis_asyncio_module


@pytest.mark.skipif(
    not pytest.importorskip("redis", minversion="5.0"),
    reason="Redis not installed",
)
class TestRedisRateLimiterWithRedis:
    """Tests that require actual Redis connection."""

    @pytest.fixture(autouse=True)
    def setup_redis(self):
        """Check if Redis is available."""
        try:
            import redis
            client = redis.Redis.from_url("redis://localhost:6379")
            client.ping()
            # Cleanup any existing test keys
            client.delete("test_langchain:rate_limit")
            yield
            # Cleanup after tests
            client.delete("test_langchain:rate_limit")
        except Exception:
            pytest.skip("Redis not available")

    def test_acquire_sync(self):
        """Test synchronous acquire."""
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
            namespace="test_langchain",
        )

        # First acquire should succeed
        result = limiter.acquire(blocking=False)
        assert result is True

    def test_acquire_blocking(self):
        """Test blocking acquire."""
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=2,
            burst_size=2,
            namespace="test_langchain",
            timeout_seconds=1.0,
        )

        # Consume all tokens
        assert limiter.acquire(blocking=False) is True
        assert limiter.acquire(blocking=False) is True

        # Next one should block
        start = time.time()
        result = limiter.acquire(blocking=True)
        duration = time.time() - start

        # Should have waited for refill
        assert duration > 0.4  # At 2 RPS, wait at least 0.5s

    def test_get_current_usage(self):
        """Test getting current usage statistics."""
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
            burst_size=20,
            namespace="test_langchain",
        )

        usage = limiter.get_current_usage()

        assert "tokens" in usage
        assert "last_update" in usage
        assert "max_tokens" in usage
        assert "refill_rate" in usage
        assert usage["max_tokens"] == 20
        assert usage["refill_rate"] == 10

    def test_reset(self):
        """Test resetting rate limiter."""
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
            namespace="test_langchain",
        )

        # Consume some tokens
        limiter.acquire(blocking=False)
        limiter.acquire(blocking=False)

        # Reset
        limiter.reset()

        # Should be able to acquire again
        result = limiter.acquire(blocking=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_async(self):
        """Test asynchronous acquire."""
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=10,
            namespace="test_langchain",
        )

        # First acquire should succeed
        result = await limiter.aacquire(blocking=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_async_blocking(self):
        """Test async blocking acquire."""
        import asyncio
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=2,
            burst_size=2,
            namespace="test_langchain",
            timeout_seconds=1.0,
        )

        # Consume all tokens
        assert await limiter.aacquire(blocking=False) is True
        assert await limiter.aacquire(blocking=False) is True

        # Next one should block and wait
        start = time.time()
        result = await limiter.aacquire(blocking=True)
        duration = time.time() - start

        # Should have waited for refill
        assert duration > 0.4

    @pytest.mark.asyncio
    async def test_concurrent_async_acquires(self):
        """Test multiple concurrent async acquires."""
        import asyncio
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        limiter = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=5,
            namespace="test_langchain",
        )

        async def try_acquire():
            return await limiter.aacquire(blocking=False)

        # Try 10 concurrent acquires
        results = await asyncio.gather(*[try_acquire() for _ in range(10)])

        # Some should succeed, some should fail (depending on burst size)
        assert any(results)  # At least one should succeed


def test_distributed_rate_limiter_interface():
    """Test DistributedRateLimiter interface."""
    try:
        from langchain_core.enterprise.rate_limiters import DistributedRateLimiter

        # Should be abstract
        assert hasattr(DistributedRateLimiter, 'get_current_usage')

    except ImportError:
        pytest.skip("Redis package not installed")


def test_rate_limiter_configuration_options():
    """Test various configuration options."""
    try:
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        # Minimum configuration
        limiter1 = RedisRateLimiter(redis_url="redis://localhost:6379")
        assert limiter1.requests_per_second == 10.0  # Default

        # Custom configuration
        limiter2 = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            requests_per_second=100.0,
            burst_size=200,
            strategy="token_bucket",
            namespace="custom:namespace",
            timeout_seconds=5.0,
        )

        assert limiter2.requests_per_second == 100.0
        assert limiter2.burst_size == 200
        assert limiter2.strategy == "token_bucket"
        assert limiter2.namespace == "custom:namespace"
        assert limiter2.timeout_seconds == 5.0

    except ImportError:
        pytest.skip("Redis package not installed")


def test_multi_tenant_rate_limiting():
    """Test rate limiting with multiple tenant namespaces."""
    try:
        from langchain_core.enterprise.rate_limiters import RedisRateLimiter

        # Create separate limiters for different tenants
        limiter_tenant_a = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            namespace="langchain:tenant-a",
        )

        limiter_tenant_b = RedisRateLimiter(
            redis_url="redis://localhost:6379",
            namespace="langchain:tenant-b",
        )

        # Each should have independent rate limits
        assert limiter_tenant_a.namespace != limiter_tenant_b.namespace

    except ImportError:
        pytest.skip("Redis package not installed")
