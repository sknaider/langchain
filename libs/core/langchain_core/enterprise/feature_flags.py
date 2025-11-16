"""Feature flags for gradual rollouts and A/B testing.

Supports local and remote feature flag providers (LaunchDarkly, Split.io, etc.).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from enum import Enum
from typing import Any

from langchain_core.enterprise.observability import EnterpriseLogger
from langchain_core.enterprise.tenancy import get_current_tenant

logger = EnterpriseLogger(__name__)


class FeatureFlagProvider(str, Enum):
    """Feature flag providers."""

    LOCAL = "local"
    LAUNCHDARKLY = "launchdarkly"
    SPLIT = "split"
    UNLEASH = "unleash"


class FeatureFlags:
    """Feature flag system for gradual rollouts and experimentation.

    Example:
        ```python
        from langchain_core.enterprise import FeatureFlags

        # Local provider (uses environment variables)
        flags = FeatureFlags(provider="local")

        # Check feature flag
        if flags.is_enabled("new_rag_algorithm"):
            result = new_rag_search(query)
        else:
            result = legacy_rag_search(query)

        # With user/tenant context
        if flags.is_enabled("advanced_features", user_id="user123", tenant_id="acme"):
            # Feature enabled for this user/tenant
            pass

        # Get variant (for A/B testing)
        variant = flags.get_variant("ui_layout", default="control")
        if variant == "experimental":
            render_new_ui()
        ```
    """

    def __init__(
        self,
        *,
        provider: str = "local",
        sdk_key: str | None = None,
        default_value: bool = False,
    ):
        """Initialize feature flags.

        Args:
            provider: Feature flag provider (`'local'`, `'launchdarkly'`, `'split'`,
                `'unleash'`).
            sdk_key: SDK key for remote provider. If not provided, will try to read
                from environment variable.
            default_value: Default value when flag is not found.
        """
        self.provider = provider
        self.sdk_key = sdk_key
        self.default_value = default_value

        # Local feature flags from environment
        self._local_flags: dict[str, bool] = {}
        self._load_local_flags()

        # Remote client (lazy initialization)
        self._remote_client: Any = None

    def _load_local_flags(self) -> None:
        """Load feature flags from environment variables.

        Environment variables should be in format:
        FEATURE_FLAG_<NAME>=true|false
        """
        for key, value in os.environ.items():
            if key.startswith("FEATURE_FLAG_"):
                flag_name = key.replace("FEATURE_FLAG_", "").lower()
                self._local_flags[flag_name] = value.lower() in ("true", "1", "yes")

    def _get_remote_client(self) -> Any:
        """Get or create remote feature flag client.

        Returns:
            Remote client instance.

        Raises:
            ImportError: If provider SDK is not installed.
        """
        if self._remote_client is not None:
            return self._remote_client

        if self.provider == FeatureFlagProvider.LAUNCHDARKLY:
            try:
                import ldclient
                from ldclient.config import Config

                sdk_key = self.sdk_key or os.getenv("LAUNCHDARKLY_SDK_KEY")
                if not sdk_key:
                    msg = "LaunchDarkly SDK key not provided"
                    raise ValueError(msg)

                ldclient.set_config(Config(sdk_key))
                self._remote_client = ldclient.get()
                return self._remote_client

            except ImportError as e:
                msg = (
                    "LaunchDarkly provider requires 'launchdarkly-server-sdk' package. "
                    "Install with: pip install launchdarkly-server-sdk"
                )
                raise ImportError(msg) from e

        elif self.provider == FeatureFlagProvider.SPLIT:
            try:
                from splitio import get_factory

                sdk_key = self.sdk_key or os.getenv("SPLIT_SDK_KEY")
                if not sdk_key:
                    msg = "Split SDK key not provided"
                    raise ValueError(msg)

                factory = get_factory(sdk_key)
                self._remote_client = factory.client()
                return self._remote_client

            except ImportError as e:
                msg = (
                    "Split provider requires 'splitio-client' package. "
                    "Install with: pip install splitio-client"
                )
                raise ImportError(msg) from e

        else:
            msg = f"Provider '{self.provider}' not implemented"
            raise NotImplementedError(msg)

    def is_enabled(
        self,
        flag_name: str,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        default: bool | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> bool:
        """Check if a feature flag is enabled.

        Args:
            flag_name: Feature flag name.
            user_id: User identifier for personalized flags.
            tenant_id: Tenant identifier. If not provided, will try to get from
                current tenant context.
            default: Default value if flag not found. If `None`, uses instance default.
            attributes: Additional attributes for flag evaluation.

        Returns:
            `True` if feature is enabled, `False` otherwise.
        """
        if default is None:
            default = self.default_value

        # Get tenant from context if not provided
        if tenant_id is None:
            tenant = get_current_tenant()
            if tenant:
                tenant_id = tenant.tenant_id
                # Check tenant-specific feature flags
                if tenant.is_feature_enabled(flag_name):
                    return True

        # Local provider
        if self.provider == FeatureFlagProvider.LOCAL:
            enabled = self._local_flags.get(flag_name.lower(), default)
            logger.debug(
                "feature_flag_evaluated",
                flag_name=flag_name,
                enabled=enabled,
                provider="local",
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return enabled

        # Remote provider
        try:
            client = self._get_remote_client()

            if self.provider == FeatureFlagProvider.LAUNCHDARKLY:
                user = {
                    "key": user_id or "anonymous",
                    "custom": attributes or {},
                }
                if tenant_id:
                    user["custom"]["tenant_id"] = tenant_id

                enabled = client.variation(flag_name, user, default)

            elif self.provider == FeatureFlagProvider.SPLIT:
                key = user_id or tenant_id or "anonymous"
                attrs = attributes or {}
                if tenant_id:
                    attrs["tenant_id"] = tenant_id

                treatment = client.get_treatment(key, flag_name, attrs)
                enabled = treatment == "on"

            else:
                enabled = default

            logger.debug(
                "feature_flag_evaluated",
                flag_name=flag_name,
                enabled=enabled,
                provider=self.provider,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return enabled

        except Exception as e:
            logger.error(
                "feature_flag_error",
                flag_name=flag_name,
                error=str(e),
                provider=self.provider,
            )
            return default

    def get_variant(
        self,
        flag_name: str,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        default: str = "control",
        attributes: dict[str, Any] | None = None,
    ) -> str:
        """Get feature flag variant for A/B testing.

        Args:
            flag_name: Feature flag name.
            user_id: User identifier.
            tenant_id: Tenant identifier.
            default: Default variant if flag not found.
            attributes: Additional attributes for evaluation.

        Returns:
            Variant name (e.g., `'control'`, `'treatment'`, `'experimental'`).
        """
        # Get tenant from context if not provided
        if tenant_id is None:
            tenant = get_current_tenant()
            if tenant:
                tenant_id = tenant.tenant_id

        # Local provider (simple boolean mapping)
        if self.provider == FeatureFlagProvider.LOCAL:
            enabled = self.is_enabled(
                flag_name,
                user_id=user_id,
                tenant_id=tenant_id,
                attributes=attributes,
            )
            return "treatment" if enabled else default

        # Remote provider
        try:
            client = self._get_remote_client()

            if self.provider == FeatureFlagProvider.SPLIT:
                key = user_id or tenant_id or "anonymous"
                attrs = attributes or {}
                if tenant_id:
                    attrs["tenant_id"] = tenant_id

                variant = client.get_treatment(key, flag_name, attrs)
                return variant if variant != "control" else default

            else:
                # For LaunchDarkly and others, use is_enabled for now
                enabled = self.is_enabled(
                    flag_name,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    attributes=attributes,
                )
                return "treatment" if enabled else default

        except Exception as e:
            logger.error(
                "feature_flag_variant_error",
                flag_name=flag_name,
                error=str(e),
                provider=self.provider,
            )
            return default

    def track_event(
        self,
        event_name: str,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        value: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track an event for feature flag analytics.

        Args:
            event_name: Event name.
            user_id: User identifier.
            tenant_id: Tenant identifier.
            value: Optional numeric value.
            metadata: Additional event metadata.
        """
        try:
            if self.provider == FeatureFlagProvider.LOCAL:
                logger.info(
                    "feature_flag_event",
                    event_name=event_name,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    value=value,
                    metadata=metadata,
                )
                return

            client = self._get_remote_client()

            if self.provider == FeatureFlagProvider.LAUNCHDARKLY:
                user = {"key": user_id or "anonymous"}
                if tenant_id:
                    user["custom"] = {"tenant_id": tenant_id}

                if value is not None:
                    client.track(event_name, user, value, metadata)
                else:
                    client.track(event_name, user, metadata=metadata)

            elif self.provider == FeatureFlagProvider.SPLIT:
                key = user_id or tenant_id or "anonymous"
                client.track(key, "user", event_name, value, metadata)

        except Exception as e:
            logger.error(
                "feature_flag_track_error",
                event_name=event_name,
                error=str(e),
                provider=self.provider,
            )

    def __del__(self) -> None:
        """Cleanup remote client."""
        if self._remote_client is not None:
            try:
                if self.provider == FeatureFlagProvider.LAUNCHDARKLY:
                    self._remote_client.close()
                elif self.provider == FeatureFlagProvider.SPLIT:
                    self._remote_client.destroy()
            except Exception:
                pass
