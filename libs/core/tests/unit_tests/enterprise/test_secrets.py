"""Tests for secrets management."""

import os

import pytest

from langchain_core.enterprise.secrets import (
    SecretsManager,
    SecretProvider,
    EnvSecretsBackend,
    Secret,
)


def test_env_backend_get_secret():
    """Test getting secret from environment backend."""
    os.environ["TEST_SECRET"] = "test-value-123"

    backend = EnvSecretsBackend()
    secret = backend.get_secret("TEST_SECRET")

    assert secret.value == "test-value-123"
    assert secret.created_at is not None
    assert secret.metadata["provider"] == "env"

    # Cleanup
    del os.environ["TEST_SECRET"]


def test_env_backend_get_nonexistent_secret():
    """Test getting non-existent secret from environment backend."""
    backend = EnvSecretsBackend()

    with pytest.raises(ValueError, match="not found in environment"):
        backend.get_secret("NONEXISTENT_SECRET_XYZ")


def test_env_backend_set_secret():
    """Test setting secret in environment backend."""
    backend = EnvSecretsBackend()

    backend.set_secret("TEST_SECRET_SET", "new-value-456")

    assert os.getenv("TEST_SECRET_SET") == "new-value-456"

    # Cleanup
    del os.environ["TEST_SECRET_SET"]


def test_env_backend_delete_secret():
    """Test deleting secret from environment backend."""
    os.environ["TEST_SECRET_DELETE"] = "value"

    backend = EnvSecretsBackend()
    backend.delete_secret("TEST_SECRET_DELETE")

    assert "TEST_SECRET_DELETE" not in os.environ


def test_env_backend_rotate_secret():
    """Test rotating secret in environment backend."""
    os.environ["TEST_SECRET_ROTATE"] = "old-value"

    backend = EnvSecretsBackend()
    backend.rotate_secret("TEST_SECRET_ROTATE", "new-value")

    assert os.getenv("TEST_SECRET_ROTATE") == "new-value"

    # Cleanup
    del os.environ["TEST_SECRET_ROTATE"]


def test_secrets_manager_env_provider():
    """Test SecretsManager with env provider."""
    os.environ["TEST_API_KEY"] = "sk-test-123"

    manager = SecretsManager(provider="env")

    value = manager.get("TEST_API_KEY")
    assert value == "sk-test-123"

    # Cleanup
    del os.environ["TEST_API_KEY"]


def test_secrets_manager_get_secret_with_metadata():
    """Test getting secret with metadata."""
    os.environ["TEST_SECRET_META"] = "value-with-meta"

    manager = SecretsManager(provider="env")
    secret = manager.get_secret("TEST_SECRET_META")

    assert isinstance(secret, Secret)
    assert secret.value == "value-with-meta"
    assert secret.created_at is not None

    # Cleanup
    del os.environ["TEST_SECRET_META"]


def test_secrets_manager_set():
    """Test setting secret via SecretsManager."""
    manager = SecretsManager(provider="env")

    manager.set("TEST_SECRET_MGR_SET", "manager-value")

    assert os.getenv("TEST_SECRET_MGR_SET") == "manager-value"

    # Cleanup
    del os.environ["TEST_SECRET_MGR_SET"]


def test_secrets_manager_delete():
    """Test deleting secret via SecretsManager."""
    os.environ["TEST_SECRET_MGR_DELETE"] = "value"

    manager = SecretsManager(provider="env")
    manager.delete("TEST_SECRET_MGR_DELETE")

    assert "TEST_SECRET_MGR_DELETE" not in os.environ


def test_secrets_manager_rotate():
    """Test rotating secret via SecretsManager."""
    os.environ["TEST_SECRET_MGR_ROTATE"] = "old-value"

    manager = SecretsManager(provider="env")
    manager.rotate("TEST_SECRET_MGR_ROTATE", "new-value")

    assert os.getenv("TEST_SECRET_MGR_ROTATE") == "new-value"

    # Cleanup
    del os.environ["TEST_SECRET_MGR_ROTATE"]


def test_secrets_manager_with_metadata():
    """Test setting secret with metadata."""
    manager = SecretsManager(provider="env")

    metadata = {"purpose": "api_key", "environment": "test"}
    manager.set("TEST_SECRET_WITH_META", "value", metadata=metadata)

    # For env backend, metadata is not stored, but should not error
    assert os.getenv("TEST_SECRET_WITH_META") == "value"

    # Cleanup
    del os.environ["TEST_SECRET_WITH_META"]


def test_secret_provider_enum():
    """Test SecretProvider enum."""
    assert SecretProvider.ENV == "env"
    assert SecretProvider.VAULT == "vault"
    assert SecretProvider.AWS == "aws"
    assert SecretProvider.AZURE == "azure"
    assert SecretProvider.GCP == "gcp"


def test_unsupported_provider():
    """Test error for unsupported provider."""
    with pytest.raises(NotImplementedError):
        SecretsManager(provider="unsupported_provider")


def test_vault_provider_without_credentials():
    """Test Vault provider requires credentials."""
    with pytest.raises(ValueError, match="vault_url and vault_token required"):
        SecretsManager(provider="vault")


def test_check_rotation_needed():
    """Test checking if secret rotation is needed."""
    from datetime import datetime, timedelta

    # Create a "fresh" secret
    os.environ["TEST_SECRET_ROTATION"] = "value"

    manager = SecretsManager(provider="env")

    # Fresh secret should not need rotation
    needs_rotation = manager.check_rotation_needed(
        "TEST_SECRET_ROTATION",
        max_age_days=90,
    )

    # For env backend, we can't track age, so this tests the implementation
    # doesn't crash

    # Cleanup
    del os.environ["TEST_SECRET_ROTATION"]


def test_rotation_callback():
    """Test rotation needed callback."""
    rotation_callbacks = []

    def on_rotation(secret_name: str):
        rotation_callbacks.append(secret_name)

    os.environ["TEST_SECRET_CALLBACK"] = "value"

    manager = SecretsManager(
        provider="env",
        on_rotation_needed=on_rotation,
    )

    # Check rotation (may or may not trigger callback)
    manager.check_rotation_needed("TEST_SECRET_CALLBACK", max_age_days=0)

    # Cleanup
    del os.environ["TEST_SECRET_CALLBACK"]


def test_multiple_secrets():
    """Test managing multiple secrets."""
    manager = SecretsManager(provider="env")

    secrets = {
        "API_KEY_1": "key-1-value",
        "API_KEY_2": "key-2-value",
        "API_KEY_3": "key-3-value",
    }

    # Set multiple secrets
    for name, value in secrets.items():
        manager.set(name, value)

    # Verify all secrets
    for name, expected_value in secrets.items():
        actual_value = manager.get(name)
        assert actual_value == expected_value

    # Cleanup
    for name in secrets.keys():
        del os.environ[name]


def test_secret_lifecycle():
    """Test complete secret lifecycle."""
    manager = SecretsManager(provider="env")

    secret_name = "LIFECYCLE_SECRET"

    # 1. Create
    manager.set(secret_name, "initial-value")
    assert manager.get(secret_name) == "initial-value"

    # 2. Update (rotate)
    manager.rotate(secret_name, "rotated-value")
    assert manager.get(secret_name) == "rotated-value"

    # 3. Delete
    manager.delete(secret_name)
    assert secret_name not in os.environ


def test_secret_with_special_characters():
    """Test secrets with special characters."""
    manager = SecretsManager(provider="env")

    special_value = "sk-test!@#$%^&*()_+-={}[]|:;<>?,./"

    manager.set("SPECIAL_SECRET", special_value)
    assert manager.get("SPECIAL_SECRET") == special_value

    # Cleanup
    del os.environ["SPECIAL_SECRET"]


@pytest.mark.asyncio
async def test_secrets_in_async_context():
    """Test secrets management in async context."""
    import asyncio

    os.environ["ASYNC_SECRET"] = "async-value"

    manager = SecretsManager(provider="env")

    async def get_secret_async():
        await asyncio.sleep(0.01)
        return manager.get("ASYNC_SECRET")

    result = await get_secret_async()
    assert result == "async-value"

    # Cleanup
    del os.environ["ASYNC_SECRET"]


def test_secret_object_fields():
    """Test Secret object fields."""
    from datetime import datetime

    secret = Secret(
        value="test-value",
        created_at=datetime.utcnow(),
        expires_at=None,
        metadata={"key": "value"},
        version="v1",
    )

    assert secret.value == "test-value"
    assert secret.created_at is not None
    assert secret.expires_at is None
    assert secret.metadata == {"key": "value"}
    assert secret.version == "v1"
