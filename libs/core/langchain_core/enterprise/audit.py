"""Enterprise audit logging for compliance and security.

Provides comprehensive audit logging for:
- GDPR compliance (data access, deletion, portability)
- SOC2 controls (access control, change tracking)
- HIPAA requirements (PHI access logging)
- ISO 27001 (security event logging)
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict

from langchain_core.enterprise.observability import EnterpriseLogger, get_correlation_id

logger = EnterpriseLogger(__name__)


class AuditEventType(str, Enum):
    """Types of audit events."""

    # Data access
    DATA_ACCESS = "data_access"
    DATA_READ = "data_read"
    DATA_WRITE = "data_write"
    DATA_DELETE = "data_delete"
    DATA_EXPORT = "data_export"

    # Authentication & Authorization
    AUTH_LOGIN = "auth_login"
    AUTH_LOGOUT = "auth_logout"
    AUTH_FAILED = "auth_failed"
    AUTHZ_GRANTED = "authz_granted"
    AUTHZ_DENIED = "authz_denied"

    # LLM Operations
    LLM_INVOKE = "llm_invoke"
    LLM_STREAM = "llm_stream"
    TOOL_USE = "tool_use"
    AGENT_RUN = "agent_run"

    # Configuration
    CONFIG_CHANGE = "config_change"
    SECRET_ACCESS = "secret_access"
    SECRET_ROTATION = "secret_rotation"

    # Compliance
    GDPR_DATA_REQUEST = "gdpr_data_request"
    GDPR_DATA_DELETION = "gdpr_data_deletion"
    GDPR_CONSENT_CHANGE = "gdpr_consent_change"
    PII_DETECTED = "pii_detected"
    PII_REDACTED = "pii_redacted"


class AuditEventSeverity(str, Enum):
    """Severity levels for audit events."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AuditEvent(TypedDict, total=False):
    """Structured audit event."""

    # Core fields
    event_id: str
    timestamp: str
    event_type: str
    severity: str
    correlation_id: str

    # Actor (who)
    user_id: str | None
    tenant_id: str | None
    service_name: str | None
    ip_address: str | None
    user_agent: str | None

    # Action (what)
    action: str
    resource_type: str | None
    resource_id: str | None
    operation: str | None

    # Context (how/why)
    success: bool
    error_message: str | None
    metadata: dict[str, Any]

    # Compliance
    compliance_framework: str | None  # GDPR, SOC2, HIPAA
    data_classification: str | None  # public, internal, confidential, restricted


class AuditLogger:
    """Enterprise audit logger for compliance and security.

    Records security-relevant events in a structured, immutable format suitable
    for compliance audits and forensic analysis.

    Example:
        ```python
        from langchain_core.enterprise import AuditLogger, AuditEventType

        audit = AuditLogger()

        # Log data access
        audit.log(
            event_type=AuditEventType.DATA_ACCESS,
            action="retrieve_customer_records",
            user_id="user123",
            tenant_id="acme-corp",
            resource_type="customer_database",
            resource_id="db_main",
            success=True,
            metadata={"query": "SELECT * FROM customers WHERE id=?"},
        )

        # Log LLM invocation with PII
        audit.log(
            event_type=AuditEventType.LLM_INVOKE,
            action="process_customer_request",
            user_id="user123",
            tenant_id="acme-corp",
            metadata={
                "model": "gpt-4",
                "tokens": 150,
                "pii_detected": True,
                "pii_types": ["email", "phone"],
            },
            compliance_framework="GDPR",
            data_classification="confidential",
        )
        ```
    """

    def __init__(
        self,
        *,
        sink: Callable[[AuditEvent], None] | None = None,
        enable_console_output: bool = True,
    ):
        """Initialize audit logger.

        Args:
            sink: Optional custom sink for audit events (e.g., write to database,
                SIEM system, etc.). If not provided, logs are written via the
                standard logger.
            enable_console_output: Whether to log to console via standard logger.
        """
        self.sink = sink
        self.enable_console_output = enable_console_output
        self._lock = threading.Lock()

    def log(
        self,
        event_type: AuditEventType | str,
        action: str,
        *,
        severity: AuditEventSeverity = AuditEventSeverity.INFO,
        user_id: str | None = None,
        tenant_id: str | None = None,
        service_name: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        operation: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        compliance_framework: str | None = None,
        data_classification: str | None = None,
    ) -> None:
        """Log an audit event.

        Args:
            event_type: Type of audit event.
            action: Human-readable action description.
            severity: Event severity level.
            user_id: User identifier who performed the action.
            tenant_id: Tenant/organization identifier.
            service_name: Service or component name.
            ip_address: IP address of the actor.
            user_agent: User agent string.
            resource_type: Type of resource being accessed.
            resource_id: Identifier of the specific resource.
            operation: Operation performed (e.g., `'read'`, `'write'`, `'delete'`).
            success: Whether the operation succeeded.
            error_message: Error message if operation failed.
            metadata: Additional structured metadata.
            compliance_framework: Relevant compliance framework (`'GDPR'`,
                `'SOC2'`, `'HIPAA'`, `'ISO27001'`).
            data_classification: Data classification level.
        """
        import uuid

        event: AuditEvent = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type.value if isinstance(event_type, AuditEventType) else event_type,
            "severity": severity.value if isinstance(severity, AuditEventSeverity) else severity,
            "correlation_id": get_correlation_id(),
            "action": action,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "service_name": service_name,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "operation": operation,
            "success": success,
            "error_message": error_message,
            "metadata": metadata or {},
            "compliance_framework": compliance_framework,
            "data_classification": data_classification,
        }

        with self._lock:
            # Send to custom sink
            if self.sink:
                try:
                    self.sink(event)
                except Exception as e:
                    logger.error(
                        "audit_sink_error",
                        error=str(e),
                        event_type=event_type,
                    )

            # Log to console
            if self.enable_console_output:
                log_method = logger.info
                if severity == AuditEventSeverity.WARNING:
                    log_method = logger.warning
                elif severity == AuditEventSeverity.CRITICAL:
                    log_method = logger.critical

                log_method(
                    f"AUDIT: {action}",
                    **{k: v for k, v in event.items() if v is not None},
                )

    def log_data_access(
        self,
        resource_type: str,
        resource_id: str,
        *,
        operation: str = "read",
        user_id: str | None = None,
        tenant_id: str | None = None,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log data access event (convenience method).

        Args:
            resource_type: Type of resource accessed.
            resource_id: Resource identifier.
            operation: Operation performed.
            user_id: User identifier.
            tenant_id: Tenant identifier.
            success: Whether access succeeded.
            metadata: Additional metadata.
        """
        self.log(
            event_type=AuditEventType.DATA_ACCESS,
            action=f"{operation} {resource_type}",
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            operation=operation,
            success=success,
            metadata=metadata,
        )

    def log_llm_invocation(
        self,
        model: str,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        tokens_used: int | None = None,
        cost_usd: float | None = None,
        pii_detected: bool = False,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log LLM invocation event (convenience method).

        Args:
            model: Model name.
            user_id: User identifier.
            tenant_id: Tenant identifier.
            tokens_used: Number of tokens consumed.
            cost_usd: Cost in USD.
            pii_detected: Whether PII was detected in input/output.
            success: Whether invocation succeeded.
            metadata: Additional metadata.
        """
        event_metadata = metadata or {}
        event_metadata.update(
            {
                "model": model,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
                "pii_detected": pii_detected,
            }
        )

        severity = AuditEventSeverity.WARNING if pii_detected else AuditEventSeverity.INFO

        self.log(
            event_type=AuditEventType.LLM_INVOKE,
            action=f"invoke {model}",
            severity=severity,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type="llm",
            resource_id=model,
            operation="invoke",
            success=success,
            metadata=event_metadata,
            data_classification="confidential" if pii_detected else "internal",
        )

    def log_gdpr_event(
        self,
        gdpr_action: str,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        subject_id: str,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log GDPR compliance event (convenience method).

        Args:
            gdpr_action: GDPR action (`'data_request'`, `'data_deletion'`,
                `'consent_change'`).
            user_id: User identifier who initiated the action.
            tenant_id: Tenant identifier.
            subject_id: Data subject identifier.
            success: Whether action succeeded.
            metadata: Additional metadata.
        """
        event_type_map = {
            "data_request": AuditEventType.GDPR_DATA_REQUEST,
            "data_deletion": AuditEventType.GDPR_DATA_DELETION,
            "consent_change": AuditEventType.GDPR_CONSENT_CHANGE,
        }

        event_metadata = metadata or {}
        event_metadata["subject_id"] = subject_id

        self.log(
            event_type=event_type_map.get(gdpr_action, AuditEventType.DATA_ACCESS),
            action=f"GDPR {gdpr_action} for subject {subject_id}",
            severity=AuditEventSeverity.CRITICAL,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type="gdpr_data",
            resource_id=subject_id,
            operation=gdpr_action,
            success=success,
            metadata=event_metadata,
            compliance_framework="GDPR",
        )


# Global audit logger instance
audit_logger = AuditLogger()
