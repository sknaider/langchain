"""Enterprise secrets management integration.

Integrates with enterprise secret stores:
- HashiCorp Vault
- AWS Secrets Manager
- Azure Key Vault
- Google Cloud Secret Manager
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from langchain_core.enterprise.observability import EnterpriseLogger

logger = EnterpriseLogger(__name__)


class SecretProvider(str, Enum):
    """Secret provider backends."""

    ENV = "env"  # Environment variables (default)
    VAULT = "vault"  # HashiCorp Vault
    AWS = "aws"  # AWS Secrets Manager
    AZURE = "azure"  # Azure Key Vault
    GCP = "gcp"  # Google Cloud Secret Manager


@dataclass
class Secret:
    """Secret value with metadata."""

    value: str
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    version: str | None = None


class BaseSecretsBackend(ABC):
    """Base class for secrets backends."""

    @abstractmethod
    def get_secret(self, secret_name: str) -> Secret:
        """Retrieve a secret.

        Args:
            secret_name: Secret identifier.

        Returns:
            Secret value with metadata.

        Raises:
            ValueError: If secret not found.
        """

    @abstractmethod
    def set_secret(
        self,
        secret_name: str,
        secret_value: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a secret.

        Args:
            secret_name: Secret identifier.
            secret_value: Secret value.
            metadata: Optional metadata.
        """

    @abstractmethod
    def delete_secret(self, secret_name: str) -> None:
        """Delete a secret.

        Args:
            secret_name: Secret identifier.
        """

    @abstractmethod
    def rotate_secret(
        self,
        secret_name: str,
        new_value: str,
    ) -> None:
        """Rotate a secret to a new value.

        Args:
            secret_name: Secret identifier.
            new_value: New secret value.
        """


class EnvSecretsBackend(BaseSecretsBackend):
    """Environment variables backend (default)."""

    def get_secret(self, secret_name: str) -> Secret:
        """Get secret from environment variable.

        Args:
            secret_name: Secret identifier.

        Returns:
            Secret value.

        Raises:
            ValueError: If secret not found.
        """
        value = os.getenv(secret_name)
        if value is None:
            msg = f"Secret '{secret_name}' not found in environment"
            raise ValueError(msg)

        return Secret(
            value=value,
            created_at=datetime.utcnow(),
            metadata={"provider": "env"},
        )

    def set_secret(
        self,
        secret_name: str,
        secret_value: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set environment variable.

        Args:
            secret_name: Secret identifier.
            secret_value: Secret value.
            metadata: Optional metadata (ignored for env backend).
        """
        os.environ[secret_name] = secret_value

    def delete_secret(self, secret_name: str) -> None:
        """Delete environment variable.

        Args:
            secret_name: Secret identifier.
        """
        if secret_name in os.environ:
            del os.environ[secret_name]

    def rotate_secret(self, secret_name: str, new_value: str) -> None:
        """Rotate secret.

        Args:
            secret_name: Secret identifier.
            new_value: New secret value.
        """
        self.set_secret(secret_name, new_value)


class VaultSecretsBackend(BaseSecretsBackend):
    """HashiCorp Vault backend."""

    def __init__(self, vault_url: str, token: str, *, mount_point: str = "secret"):
        """Initialize Vault backend.

        Args:
            vault_url: Vault server URL.
            token: Vault token.
            mount_point: KV secrets engine mount point.
        """
        try:
            import hvac

            self.client = hvac.Client(url=vault_url, token=token)
            self.mount_point = mount_point

            if not self.client.is_authenticated():
                msg = "Failed to authenticate with Vault"
                raise ValueError(msg)

        except ImportError as e:
            msg = (
                "Vault backend requires 'hvac' package. "
                "Install with: pip install hvac"
            )
            raise ImportError(msg) from e

    def get_secret(self, secret_name: str) -> Secret:
        """Get secret from Vault.

        Args:
            secret_name: Secret path in Vault.

        Returns:
            Secret value with metadata.

        Raises:
            ValueError: If secret not found.
        """
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=secret_name, mount_point=self.mount_point
            )

            data = response["data"]["data"]
            metadata = response["data"]["metadata"]

            return Secret(
                value=data.get("value", ""),
                created_at=datetime.fromisoformat(
                    metadata["created_time"].replace("Z", "+00:00")
                ),
                version=str(metadata["version"]),
                metadata=data,
            )

        except Exception as e:
            msg = f"Failed to retrieve secret '{secret_name}' from Vault: {e}"
            raise ValueError(msg) from e

    def set_secret(
        self,
        secret_name: str,
        secret_value: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store secret in Vault.

        Args:
            secret_name: Secret path in Vault.
            secret_value: Secret value.
            metadata: Optional metadata to store with secret.
        """
        data = {"value": secret_value}
        if metadata:
            data.update(metadata)

        self.client.secrets.kv.v2.create_or_update_secret(
            path=secret_name,
            secret=data,
            mount_point=self.mount_point,
        )

    def delete_secret(self, secret_name: str) -> None:
        """Delete secret from Vault.

        Args:
            secret_name: Secret path in Vault.
        """
        self.client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=secret_name, mount_point=self.mount_point
        )

    def rotate_secret(self, secret_name: str, new_value: str) -> None:
        """Rotate secret in Vault.

        Args:
            secret_name: Secret path in Vault.
            new_value: New secret value.
        """
        # Vault KV v2 automatically versions secrets
        self.set_secret(secret_name, new_value)


class SecretsManager:
    """Enterprise secrets manager with multiple backend support.

    Example:
        ```python
        from langchain_core.enterprise import SecretsManager

        # Environment variables (default)
        secrets = SecretsManager()
        api_key = secrets.get("OPENAI_API_KEY")

        # HashiCorp Vault
        secrets = SecretsManager(
            provider="vault",
            vault_url="https://vault.example.com",
            vault_token="s.xxxxx",
        )

        # Get secret
        secret = secrets.get("openai/api_key")
        print(secret.value)

        # Rotate secret
        secrets.rotate("openai/api_key", new_value="sk-new-key")

        # Auto-rotation monitoring
        secrets.check_rotation_needed("openai/api_key", max_age_days=90)
        ```
    """

    def __init__(
        self,
        provider: str = "env",
        *,
        vault_url: str | None = None,
        vault_token: str | None = None,
        vault_mount_point: str = "secret",
        on_rotation_needed: Callable[[str], None] | None = None,
    ):
        """Initialize secrets manager.

        Args:
            provider: Secrets provider backend.
            vault_url: Vault server URL (for Vault provider).
            vault_token: Vault token (for Vault provider).
            vault_mount_point: Vault KV mount point.
            on_rotation_needed: Callback when secret rotation is needed.
        """
        self.provider = provider
        self.on_rotation_needed = on_rotation_needed

        # Initialize backend
        if provider == SecretProvider.ENV:
            self._backend = EnvSecretsBackend()
        elif provider == SecretProvider.VAULT:
            if not vault_url or not vault_token:
                msg = "vault_url and vault_token required for Vault provider"
                raise ValueError(msg)
            self._backend = VaultSecretsBackend(
                vault_url=vault_url,
                token=vault_token,
                mount_point=vault_mount_point,
            )
        else:
            msg = f"Provider '{provider}' not yet implemented"
            raise NotImplementedError(msg)

    def get(self, secret_name: str) -> str:
        """Get secret value.

        Args:
            secret_name: Secret identifier.

        Returns:
            Secret value.
        """
        secret = self._backend.get_secret(secret_name)
        logger.debug("secret_retrieved", secret_name=secret_name, provider=self.provider)
        return secret.value

    def get_secret(self, secret_name: str) -> Secret:
        """Get secret with metadata.

        Args:
            secret_name: Secret identifier.

        Returns:
            Secret object with metadata.
        """
        return self._backend.get_secret(secret_name)

    def set(
        self,
        secret_name: str,
        secret_value: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set secret value.

        Args:
            secret_name: Secret identifier.
            secret_value: Secret value.
            metadata: Optional metadata.
        """
        self._backend.set_secret(secret_name, secret_value, metadata=metadata)
        logger.info("secret_set", secret_name=secret_name, provider=self.provider)

    def delete(self, secret_name: str) -> None:
        """Delete secret.

        Args:
            secret_name: Secret identifier.
        """
        self._backend.delete_secret(secret_name)
        logger.warning("secret_deleted", secret_name=secret_name, provider=self.provider)

    def rotate(self, secret_name: str, new_value: str) -> None:
        """Rotate secret to new value.

        Args:
            secret_name: Secret identifier.
            new_value: New secret value.
        """
        self._backend.rotate_secret(secret_name, new_value)
        logger.warning("secret_rotated", secret_name=secret_name, provider=self.provider)

    def check_rotation_needed(
        self,
        secret_name: str,
        *,
        max_age_days: int = 90,
    ) -> bool:
        """Check if secret rotation is needed.

        Args:
            secret_name: Secret identifier.
            max_age_days: Maximum age in days before rotation is recommended.

        Returns:
            `True` if rotation is needed, `False` otherwise.
        """
        secret = self._backend.get_secret(secret_name)

        age = datetime.utcnow() - secret.created_at
        if age > timedelta(days=max_age_days):
            logger.warning(
                "secret_rotation_needed",
                secret_name=secret_name,
                age_days=age.days,
                max_age_days=max_age_days,
            )

            if self.on_rotation_needed:
                self.on_rotation_needed(secret_name)

            return True

        return False
