"""Tests for feature flags."""

import os

import pytest

from langchain_core.enterprise.feature_flags import FeatureFlags, FeatureFlagProvider


def test_local_provider_creation():
    """Test creating feature flags with local provider."""
    flags = FeatureFlags(provider="local")
    assert flags.provider == "local"


def test_local_provider_environment_variables():
    """Test local provider reads from environment variables."""
    # Set environment variables
    os.environ["FEATURE_FLAG_TEST_FEATURE"] = "true"
    os.environ["FEATURE_FLAG_ANOTHER_FEATURE"] = "false"

    flags = FeatureFlags(provider="local")

    assert flags.is_enabled("test_feature") is True
    assert flags.is_enabled("another_feature") is False

    # Cleanup
    del os.environ["FEATURE_FLAG_TEST_FEATURE"]
    del os.environ["FEATURE_FLAG_ANOTHER_FEATURE"]


def test_is_enabled_default_value():
    """Test is_enabled with default value."""
    flags = FeatureFlags(provider="local", default_value=False)

    # Non-existent flag should return default
    assert flags.is_enabled("nonexistent_flag") is False

    # Can override default
    assert flags.is_enabled("nonexistent_flag", default=True) is True


def test_is_enabled_with_user_context():
    """Test is_enabled with user/tenant context."""
    os.environ["FEATURE_FLAG_USER_FEATURE"] = "true"

    flags = FeatureFlags(provider="local")

    # Should work with user and tenant IDs
    assert flags.is_enabled(
        "user_feature",
        user_id="user123",
        tenant_id="tenant456",
    ) is True

    # Cleanup
    del os.environ["FEATURE_FLAG_USER_FEATURE"]


def test_is_enabled_with_tenant_context():
    """Test is_enabled using current tenant context."""
    from langchain_core.enterprise.tenancy import TenantContext, set_current_tenant

    os.environ["FEATURE_FLAG_CONTEXT_FEATURE"] = "false"

    # Create tenant with feature flag enabled
    tenant = TenantContext(
        tenant_id="test-tenant",
        feature_flags={"context_feature": True},
    )
    set_current_tenant(tenant)

    flags = FeatureFlags(provider="local")

    # Tenant-specific flag should override environment
    assert flags.is_enabled("context_feature") is True

    # Cleanup
    del os.environ["FEATURE_FLAG_CONTEXT_FEATURE"]


def test_get_variant_local_provider():
    """Test get_variant with local provider."""
    os.environ["FEATURE_FLAG_AB_TEST"] = "true"

    flags = FeatureFlags(provider="local")

    # Local provider maps boolean to treatment/control
    variant = flags.get_variant("ab_test")
    assert variant == "treatment"

    # Cleanup
    del os.environ["FEATURE_FLAG_AB_TEST"]


def test_get_variant_default():
    """Test get_variant with default value."""
    flags = FeatureFlags(provider="local")

    # Non-existent flag should return default
    variant = flags.get_variant("nonexistent", default="control")
    assert variant == "control"

    # Can override default
    variant = flags.get_variant("nonexistent", default="experimental")
    assert variant == "experimental"


def test_track_event():
    """Test tracking events (should not crash)."""
    flags = FeatureFlags(provider="local")

    # Should complete without error
    flags.track_event(
        "conversion",
        user_id="user123",
        tenant_id="tenant456",
        value=99.99,
        metadata={"source": "web"},
    )


def test_multiple_flags():
    """Test multiple feature flags."""
    os.environ["FEATURE_FLAG_FEATURE_A"] = "true"
    os.environ["FEATURE_FLAG_FEATURE_B"] = "false"
    os.environ["FEATURE_FLAG_FEATURE_C"] = "1"
    os.environ["FEATURE_FLAG_FEATURE_D"] = "yes"

    flags = FeatureFlags(provider="local")

    assert flags.is_enabled("feature_a") is True
    assert flags.is_enabled("feature_b") is False
    assert flags.is_enabled("feature_c") is True  # "1" is truthy
    assert flags.is_enabled("feature_d") is True  # "yes" is truthy

    # Cleanup
    del os.environ["FEATURE_FLAG_FEATURE_A"]
    del os.environ["FEATURE_FLAG_FEATURE_B"]
    del os.environ["FEATURE_FLAG_FEATURE_C"]
    del os.environ["FEATURE_FLAG_FEATURE_D"]


def test_case_insensitivity():
    """Test flag names are case insensitive."""
    os.environ["FEATURE_FLAG_CASE_TEST"] = "true"

    flags = FeatureFlags(provider="local")

    # Should work with different cases
    assert flags.is_enabled("case_test") is True
    assert flags.is_enabled("CASE_TEST") is True
    assert flags.is_enabled("Case_Test") is True

    # Cleanup
    del os.environ["FEATURE_FLAG_CASE_TEST"]


def test_feature_flag_with_attributes():
    """Test feature flags with additional attributes."""
    os.environ["FEATURE_FLAG_ATTRIBUTE_TEST"] = "true"

    flags = FeatureFlags(provider="local")

    # Should work with attributes
    assert flags.is_enabled(
        "attribute_test",
        attributes={"country": "US", "plan": "enterprise"},
    ) is True

    # Cleanup
    del os.environ["FEATURE_FLAG_ATTRIBUTE_TEST"]


def test_provider_enum():
    """Test FeatureFlagProvider enum."""
    assert FeatureFlagProvider.LOCAL == "local"
    assert FeatureFlagProvider.LAUNCHDARKLY == "launchdarkly"
    assert FeatureFlagProvider.SPLIT == "split"
    assert FeatureFlagProvider.UNLEASH == "unleash"


def test_unsupported_provider_error():
    """Test error for unsupported provider."""
    flags = FeatureFlags(provider="unsupported")

    # Should not raise on creation, but on usage
    with pytest.raises(NotImplementedError):
        flags.is_enabled("test")


def test_gradual_rollout_simulation():
    """Test simulating gradual rollout with local provider."""
    # Simulate 0% rollout
    flags_0 = FeatureFlags(provider="local", default_value=False)
    assert flags_0.is_enabled("new_feature") is False

    # Simulate 100% rollout
    os.environ["FEATURE_FLAG_NEW_FEATURE"] = "true"
    flags_100 = FeatureFlags(provider="local")
    assert flags_100.is_enabled("new_feature") is True

    # Cleanup
    del os.environ["FEATURE_FLAG_NEW_FEATURE"]


def test_ab_testing_variants():
    """Test A/B testing with variants."""
    flags = FeatureFlags(provider="local")

    # Control group (feature disabled)
    variant_control = flags.get_variant("ui_test", default="control")
    assert variant_control in ["control", "treatment"]

    # With feature enabled
    os.environ["FEATURE_FLAG_UI_TEST"] = "true"
    flags_enabled = FeatureFlags(provider="local")
    variant_treatment = flags_enabled.get_variant("ui_test")
    assert variant_treatment == "treatment"

    # Cleanup
    del os.environ["FEATURE_FLAG_UI_TEST"]


@pytest.mark.asyncio
async def test_feature_flags_async():
    """Test feature flags in async context."""
    import asyncio

    os.environ["FEATURE_FLAG_ASYNC_TEST"] = "true"

    flags = FeatureFlags(provider="local")

    async def check_feature():
        await asyncio.sleep(0.01)
        return flags.is_enabled("async_test")

    result = await check_feature()
    assert result is True

    # Cleanup
    del os.environ["FEATURE_FLAG_ASYNC_TEST"]


def test_boolean_conversions():
    """Test various boolean string conversions."""
    test_cases = [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
    ]

    for env_value, expected in test_cases:
        os.environ["FEATURE_FLAG_BOOL_TEST"] = env_value
        flags = FeatureFlags(provider="local")
        assert flags.is_enabled("bool_test") == expected
        del os.environ["FEATURE_FLAG_BOOL_TEST"]
