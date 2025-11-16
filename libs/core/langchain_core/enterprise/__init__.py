"""Enterprise-grade features for LangChain.

This module provides production-ready enterprise features including:
- Structured logging and observability
- Audit logging and compliance
- PII detection and data protection
- Distributed rate limiting
- Circuit breakers and resilience
- Multi-tenancy support
- Cost management and tracking
- Feature flags
- Secrets management
"""

from langchain_core.enterprise.audit import AuditLogger, AuditEvent
from langchain_core.enterprise.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
)
from langchain_core.enterprise.cost_management import (
    CostTracker,
    CostLimitExceededError,
)
from langchain_core.enterprise.feature_flags import FeatureFlags
from langchain_core.enterprise.observability import (
    EnterpriseLogger,
    MetricsCollector,
    get_correlation_id,
    set_correlation_id,
)
from langchain_core.enterprise.pii_detection import PIIDetector, PIIDetectionMiddleware
from langchain_core.enterprise.rate_limiters import (
    DistributedRateLimiter,
    RedisRateLimiter,
)
from langchain_core.enterprise.secrets import SecretsManager
from langchain_core.enterprise.tenancy import TenantContext, get_current_tenant

__all__ = [
    # Audit
    "AuditLogger",
    "AuditEvent",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerError",
    "CircuitState",
    # Cost Management
    "CostTracker",
    "CostLimitExceededError",
    # Feature Flags
    "FeatureFlags",
    # Observability
    "EnterpriseLogger",
    "MetricsCollector",
    "get_correlation_id",
    "set_correlation_id",
    # PII Detection
    "PIIDetector",
    "PIIDetectionMiddleware",
    # Rate Limiting
    "DistributedRateLimiter",
    "RedisRateLimiter",
    # Secrets
    "SecretsManager",
    # Tenancy
    "TenantContext",
    "get_current_tenant",
]
