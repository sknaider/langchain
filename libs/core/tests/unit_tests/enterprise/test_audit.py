"""Tests for audit logging."""

import pytest
from datetime import datetime

from langchain_core.enterprise.audit import (
    AuditLogger,
    AuditEventType,
    AuditEventSeverity,
    AuditEvent,
)


def test_audit_logger_basic_log():
    """Test basic audit logging."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    audit.log(
        event_type=AuditEventType.DATA_ACCESS,
        action="read customer data",
        user_id="user123",
        tenant_id="acme-corp",
        resource_type="database",
        resource_id="customers",
        success=True,
    )

    assert len(events_captured) == 1
    event = events_captured[0]

    assert event["event_type"] == "data_access"
    assert event["action"] == "read customer data"
    assert event["user_id"] == "user123"
    assert event["tenant_id"] == "acme-corp"
    assert event["resource_type"] == "database"
    assert event["resource_id"] == "customers"
    assert event["success"] is True
    assert "event_id" in event
    assert "timestamp" in event
    assert "correlation_id" in event


def test_audit_logger_severity_levels():
    """Test different severity levels."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    # Info level
    audit.log(
        event_type=AuditEventType.DATA_READ,
        action="test info",
        severity=AuditEventSeverity.INFO,
    )

    # Warning level
    audit.log(
        event_type=AuditEventType.PII_DETECTED,
        action="test warning",
        severity=AuditEventSeverity.WARNING,
    )

    # Critical level
    audit.log(
        event_type=AuditEventType.GDPR_DATA_DELETION,
        action="test critical",
        severity=AuditEventSeverity.CRITICAL,
    )

    assert len(events_captured) == 3
    assert events_captured[0]["severity"] == "info"
    assert events_captured[1]["severity"] == "warning"
    assert events_captured[2]["severity"] == "critical"


def test_audit_logger_data_access():
    """Test data access logging convenience method."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    audit.log_data_access(
        resource_type="customer_database",
        resource_id="db_main",
        operation="read",
        user_id="user123",
        tenant_id="acme-corp",
    )

    assert len(events_captured) == 1
    event = events_captured[0]

    assert event["event_type"] == "data_access"
    assert event["resource_type"] == "customer_database"
    assert event["resource_id"] == "db_main"
    assert event["operation"] == "read"
    assert event["user_id"] == "user123"
    assert event["tenant_id"] == "acme-corp"


def test_audit_logger_llm_invocation():
    """Test LLM invocation logging."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    audit.log_llm_invocation(
        model="gpt-4",
        user_id="user123",
        tenant_id="acme-corp",
        tokens_used=150,
        cost_usd=0.003,
        pii_detected=True,
    )

    assert len(events_captured) == 1
    event = events_captured[0]

    assert event["event_type"] == "llm_invoke"
    assert event["resource_type"] == "llm"
    assert event["resource_id"] == "gpt-4"
    assert event["metadata"]["model"] == "gpt-4"
    assert event["metadata"]["tokens_used"] == 150
    assert event["metadata"]["cost_usd"] == 0.003
    assert event["metadata"]["pii_detected"] is True
    assert event["severity"] == "warning"  # Because PII detected
    assert event["data_classification"] == "confidential"


def test_audit_logger_gdpr_event():
    """Test GDPR event logging."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    audit.log_gdpr_event(
        gdpr_action="data_deletion",
        subject_id="user456",
        user_id="admin123",
        tenant_id="acme-corp",
    )

    assert len(events_captured) == 1
    event = events_captured[0]

    assert event["event_type"] == "gdpr_data_deletion"
    assert event["severity"] == "critical"
    assert event["compliance_framework"] == "GDPR"
    assert event["metadata"]["subject_id"] == "user456"
    assert event["user_id"] == "admin123"


def test_audit_logger_metadata():
    """Test custom metadata in audit logs."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    audit.log(
        event_type=AuditEventType.CONFIG_CHANGE,
        action="update settings",
        metadata={
            "old_value": "foo",
            "new_value": "bar",
            "field": "api_endpoint",
        },
    )

    assert len(events_captured) == 1
    event = events_captured[0]

    assert event["metadata"]["old_value"] == "foo"
    assert event["metadata"]["new_value"] == "bar"
    assert event["metadata"]["field"] == "api_endpoint"


def test_audit_logger_compliance_frameworks():
    """Test compliance framework tagging."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    # GDPR
    audit.log(
        event_type=AuditEventType.DATA_EXPORT,
        action="export user data",
        compliance_framework="GDPR",
    )

    # SOC2
    audit.log(
        event_type=AuditEventType.SECRET_ACCESS,
        action="access api key",
        compliance_framework="SOC2",
    )

    # HIPAA
    audit.log(
        event_type=AuditEventType.DATA_ACCESS,
        action="access medical records",
        compliance_framework="HIPAA",
    )

    assert len(events_captured) == 3
    assert events_captured[0]["compliance_framework"] == "GDPR"
    assert events_captured[1]["compliance_framework"] == "SOC2"
    assert events_captured[2]["compliance_framework"] == "HIPAA"


def test_audit_logger_failure():
    """Test logging of failed operations."""
    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    audit.log(
        event_type=AuditEventType.AUTH_FAILED,
        action="login attempt",
        user_id="user123",
        success=False,
        error_message="Invalid credentials",
    )

    assert len(events_captured) == 1
    event = events_captured[0]

    assert event["success"] is False
    assert event["error_message"] == "Invalid credentials"
    assert event["event_type"] == "auth_failed"


def test_audit_logger_correlation_id():
    """Test correlation ID in audit logs."""
    from langchain_core.enterprise.observability import set_correlation_id

    events_captured = []

    def test_sink(event: AuditEvent) -> None:
        events_captured.append(event)

    audit = AuditLogger(sink=test_sink, enable_console_output=False)

    # Set correlation ID
    set_correlation_id("test-correlation-123")

    audit.log(
        event_type=AuditEventType.DATA_READ,
        action="test correlation",
    )

    assert len(events_captured) == 1
    event = events_captured[0]

    assert event["correlation_id"] == "test-correlation-123"
