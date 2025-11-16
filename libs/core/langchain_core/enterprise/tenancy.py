"""Multi-tenancy support for SaaS and enterprise deployments.

Provides tenant isolation, resource limits, and context management for
multi-tenant applications.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any

from langchain_core.enterprise.observability import EnterpriseLogger

logger = EnterpriseLogger(__name__)


@dataclass
class ResourceLimits:
    """Resource limits for a tenant."""

    max_requests_per_second: float | None = None
    max_requests_per_day: int | None = None
    max_tokens_per_request: int | None = None
    max_tokens_per_day: int | None = None
    max_cost_per_day_usd: float | None = None
    max_concurrent_requests: int | None = None
    allowed_models: list[str] | None = None
    max_context_length: int | None = None


@dataclass
class TenantContext:
    """Context for a tenant in a multi-tenant system.

    Provides tenant-specific configuration, limits, and metadata that can be
    accessed throughout the request lifecycle.

    Example:
        ```python
        from langchain_core.enterprise import TenantContext, set_current_tenant

        # Set tenant context
        tenant = TenantContext(
            tenant_id="acme-corp",
            tenant_name="ACME Corporation",
            resource_limits=ResourceLimits(
                max_requests_per_second=100,
                max_cost_per_day_usd=1000.0,
            ),
            feature_flags={"advanced_rag": True},
        )

        set_current_tenant(tenant)

        # Access anywhere in the code
        current = get_current_tenant()
        print(current.tenant_id)  # "acme-corp"
        ```
    """

    tenant_id: str
    tenant_name: str | None = None
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    feature_flags: dict[str, bool] = field(default_factory=dict)
    custom_metadata: dict[str, Any] = field(default_factory=dict)
    tier: str = "free"  # free, pro, enterprise
    enabled: bool = True

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled for this tenant.

        Args:
            feature: Feature flag name.

        Returns:
            `True` if feature is enabled, `False` otherwise.
        """
        return self.feature_flags.get(feature, False)

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get custom metadata value.

        Args:
            key: Metadata key.
            default: Default value if key not found.

        Returns:
            Metadata value or default.
        """
        return self.custom_metadata.get(key, default)


# Context variable for current tenant (thread-safe)
_current_tenant: contextvars.ContextVar[TenantContext | None] = (
    contextvars.ContextVar("current_tenant", default=None)
)


def get_current_tenant() -> TenantContext | None:
    """Get the current tenant context.

    Returns:
        Current tenant context, or `None` if not set.
    """
    return _current_tenant.get()


def set_current_tenant(tenant: TenantContext | None) -> None:
    """Set the current tenant context.

    Args:
        tenant: Tenant context to set.
    """
    _current_tenant.set(tenant)

    if tenant:
        logger.debug(
            "tenant_context_set",
            tenant_id=tenant.tenant_id,
            tier=tenant.tier,
        )


def clear_current_tenant() -> None:
    """Clear the current tenant context."""
    tenant = _current_tenant.get()
    if tenant:
        logger.debug("tenant_context_cleared", tenant_id=tenant.tenant_id)
    _current_tenant.set(None)


class TenantContextManager:
    """Context manager for tenant context.

    Example:
        ```python
        from langchain_core.enterprise import TenantContext, TenantContextManager

        tenant = TenantContext(tenant_id="acme-corp")

        with TenantContextManager(tenant):
            # Tenant context is available here
            result = llm.invoke("Hello")
        # Tenant context is cleared after exiting
        ```
    """

    def __init__(self, tenant: TenantContext):
        """Initialize tenant context manager.

        Args:
            tenant: Tenant context to set.
        """
        self.tenant = tenant
        self._token = None

    def __enter__(self) -> TenantContext:
        """Enter context manager.

        Returns:
            The tenant context.
        """
        self._token = _current_tenant.set(self.tenant)
        logger.debug(
            "tenant_context_entered",
            tenant_id=self.tenant.tenant_id,
        )
        return self.tenant

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context manager.

        Args:
            exc_type: Exception type if raised.
            exc_val: Exception value if raised.
            exc_tb: Exception traceback if raised.

        Returns:
            `False` to propagate exceptions.
        """
        if self._token is not None:
            _current_tenant.reset(self._token)
        logger.debug(
            "tenant_context_exited",
            tenant_id=self.tenant.tenant_id,
        )
        return False
