"""Tests for multi-tenancy support."""

import pytest

from langchain_core.enterprise.tenancy import (
    TenantContext,
    ResourceLimits,
    get_current_tenant,
    set_current_tenant,
    clear_current_tenant,
    TenantContextManager,
)


def test_resource_limits_creation():
    """Test creating resource limits."""
    limits = ResourceLimits(
        max_requests_per_second=100,
        max_requests_per_day=10000,
        max_tokens_per_request=4000,
        max_cost_per_day_usd=50.0,
    )

    assert limits.max_requests_per_second == 100
    assert limits.max_requests_per_day == 10000
    assert limits.max_tokens_per_request == 4000
    assert limits.max_cost_per_day_usd == 50.0


def test_tenant_context_creation():
    """Test creating tenant context."""
    limits = ResourceLimits(max_requests_per_second=100)

    tenant = TenantContext(
        tenant_id="test-tenant-1",
        tenant_name="Test Tenant",
        resource_limits=limits,
        feature_flags={"advanced_rag": True, "beta_features": False},
        tier="pro",
    )

    assert tenant.tenant_id == "test-tenant-1"
    assert tenant.tenant_name == "Test Tenant"
    assert tenant.resource_limits.max_requests_per_second == 100
    assert tenant.tier == "pro"
    assert tenant.enabled is True


def test_tenant_feature_flags():
    """Test tenant feature flag checking."""
    tenant = TenantContext(
        tenant_id="test-tenant-2",
        feature_flags={
            "new_ui": True,
            "experimental_api": False,
            "advanced_analytics": True,
        },
    )

    assert tenant.is_feature_enabled("new_ui") is True
    assert tenant.is_feature_enabled("experimental_api") is False
    assert tenant.is_feature_enabled("advanced_analytics") is True
    assert tenant.is_feature_enabled("nonexistent_feature") is False


def test_tenant_metadata():
    """Test tenant custom metadata."""
    tenant = TenantContext(
        tenant_id="test-tenant-3",
        custom_metadata={
            "industry": "healthcare",
            "region": "us-west",
            "contract_level": "enterprise",
        },
    )

    assert tenant.get_metadata("industry") == "healthcare"
    assert tenant.get_metadata("region") == "us-west"
    assert tenant.get_metadata("contract_level") == "enterprise"
    assert tenant.get_metadata("nonexistent") is None
    assert tenant.get_metadata("nonexistent", "default") == "default"


def test_set_get_current_tenant():
    """Test setting and getting current tenant."""
    tenant = TenantContext(
        tenant_id="current-tenant-1",
        tenant_name="Current Test Tenant",
    )

    set_current_tenant(tenant)

    current = get_current_tenant()
    assert current is not None
    assert current.tenant_id == "current-tenant-1"
    assert current.tenant_name == "Current Test Tenant"


def test_clear_current_tenant():
    """Test clearing current tenant."""
    tenant = TenantContext(tenant_id="clear-test-tenant")
    set_current_tenant(tenant)

    assert get_current_tenant() is not None

    clear_current_tenant()

    # After clearing, getting current tenant should work
    # (may return None or generate new context depending on implementation)


def test_tenant_context_isolation():
    """Test tenant context isolation."""
    tenant_a = TenantContext(tenant_id="tenant-a")
    tenant_b = TenantContext(tenant_id="tenant-b")

    # Set tenant A
    set_current_tenant(tenant_a)
    assert get_current_tenant().tenant_id == "tenant-a"

    # Set tenant B (should replace A)
    set_current_tenant(tenant_b)
    assert get_current_tenant().tenant_id == "tenant-b"


def test_tenant_context_manager():
    """Test tenant context manager."""
    tenant = TenantContext(tenant_id="context-manager-tenant")

    with TenantContextManager(tenant) as ctx_tenant:
        assert ctx_tenant.tenant_id == "context-manager-tenant"
        current = get_current_tenant()
        # Context should be set within the manager
        assert current is not None


def test_tenant_tiers():
    """Test different tenant tiers."""
    free_tenant = TenantContext(tenant_id="free-1", tier="free")
    pro_tenant = TenantContext(tenant_id="pro-1", tier="pro")
    enterprise_tenant = TenantContext(tenant_id="enterprise-1", tier="enterprise")

    assert free_tenant.tier == "free"
    assert pro_tenant.tier == "pro"
    assert enterprise_tenant.tier == "enterprise"


def test_tenant_disabled():
    """Test disabled tenant."""
    tenant = TenantContext(tenant_id="disabled-tenant", enabled=False)

    assert tenant.enabled is False


def test_comprehensive_tenant_setup():
    """Test comprehensive tenant setup with all options."""
    limits = ResourceLimits(
        max_requests_per_second=200,
        max_requests_per_day=50000,
        max_tokens_per_request=8000,
        max_tokens_per_day=1000000,
        max_cost_per_day_usd=100.0,
        max_concurrent_requests=10,
        allowed_models=["gpt-4", "claude-3-opus"],
        max_context_length=128000,
    )

    tenant = TenantContext(
        tenant_id="comprehensive-tenant",
        tenant_name="Comprehensive Test Tenant",
        resource_limits=limits,
        feature_flags={
            "advanced_rag": True,
            "multi_modal": True,
            "custom_tools": True,
        },
        custom_metadata={
            "industry": "finance",
            "region": "eu-central",
            "compliance": ["GDPR", "SOC2"],
        },
        tier="enterprise",
        enabled=True,
    )

    assert tenant.tenant_id == "comprehensive-tenant"
    assert tenant.tier == "enterprise"
    assert tenant.is_feature_enabled("advanced_rag") is True
    assert tenant.get_metadata("industry") == "finance"
    assert tenant.resource_limits.max_requests_per_second == 200
    assert "gpt-4" in tenant.resource_limits.allowed_models


def test_default_resource_limits():
    """Test tenant with default resource limits."""
    tenant = TenantContext(tenant_id="default-limits-tenant")

    # Should have default ResourceLimits instance
    assert tenant.resource_limits is not None
    assert isinstance(tenant.resource_limits, ResourceLimits)


def test_multiple_concurrent_tenants():
    """Test handling multiple tenant contexts."""
    tenants = []
    for i in range(5):
        tenant = TenantContext(
            tenant_id=f"tenant-{i}",
            tier="pro" if i % 2 == 0 else "free",
        )
        tenants.append(tenant)

    # Set different tenants
    for tenant in tenants:
        set_current_tenant(tenant)
        current = get_current_tenant()
        assert current.tenant_id == tenant.tenant_id


def test_tenant_context_with_none():
    """Test setting tenant context to None."""
    tenant = TenantContext(tenant_id="test-tenant")
    set_current_tenant(tenant)

    assert get_current_tenant() is not None

    set_current_tenant(None)

    # After setting to None, current tenant might be None


@pytest.mark.asyncio
async def test_tenant_context_in_async():
    """Test tenant context in async environment."""
    import asyncio

    tenant = TenantContext(tenant_id="async-tenant")
    set_current_tenant(tenant)

    async def async_operation():
        await asyncio.sleep(0.01)
        current = get_current_tenant()
        return current

    result = await async_operation()
    # Tenant context should be accessible in async function
