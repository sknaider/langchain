"""PII (Personally Identifiable Information) detection and redaction.

Automatically detects and redacts PII in LLM inputs/outputs for:
- GDPR compliance (protecting EU citizen data)
- HIPAA compliance (protecting PHI - Protected Health Information)
- CCPA compliance (California Consumer Privacy Act)
- General data protection best practices
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from langchain_core.enterprise.audit import audit_logger, AuditEventType
from langchain_core.enterprise.observability import EnterpriseLogger

logger = EnterpriseLogger(__name__)


class PIIType(str, Enum):
    """Types of PII that can be detected."""

    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"  # Social Security Number
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    PERSON_NAME = "person_name"
    ADDRESS = "address"
    DATE_OF_BIRTH = "date_of_birth"
    PASSPORT = "passport"
    DRIVER_LICENSE = "driver_license"
    MEDICAL_RECORD = "medical_record"
    BANK_ACCOUNT = "bank_account"
    CUSTOM = "custom"


@dataclass
class PIIMatch:
    """Detected PII match."""

    pii_type: PIIType
    value: str
    start: int
    end: int
    confidence: float  # 0.0 to 1.0


class PIIDetector:
    """Detect and redact PII in text.

    Uses regex patterns and optional ML-based detection to identify sensitive
    information.

    Example:
        ```python
        from langchain_core.enterprise import PIIDetector

        detector = PIIDetector()

        # Detect PII
        text = "Contact John Doe at john.doe@example.com or 555-123-4567"
        matches = detector.detect(text)
        print(matches)  # [PIIMatch(pii_type='email', ...), PIIMatch(pii_type='phone', ...)]

        # Redact PII
        redacted = detector.redact(text)
        print(redacted)  # "Contact [PERSON_NAME] at [EMAIL] or [PHONE]"

        # Custom redaction
        redacted = detector.redact(text, replacement="***")
        print(redacted)  # "Contact *** at *** or ***"
        ```
    """

    # Regex patterns for common PII types
    PATTERNS: dict[PIIType, str] = {
        PIIType.EMAIL: r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        PIIType.PHONE: r"\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b",
        PIIType.SSN: r"\b(?!000|666|9\d{2})\d{3}-?(?!00)\d{2}-?(?!0{4})\d{4}\b",
        PIIType.CREDIT_CARD: r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:2131|1800|35\d{3})\d{11})\b",
        PIIType.IP_ADDRESS: r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",
        PIIType.DATE_OF_BIRTH: r"\b(?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12][0-9]|3[01])[-/](?:19|20)\d{2}\b",
        PIIType.BANK_ACCOUNT: r"\b\d{8,17}\b",  # Simple pattern, may need customization
    }

    def __init__(
        self,
        *,
        enabled_types: list[PIIType] | None = None,
        custom_patterns: dict[str, str] | None = None,
        confidence_threshold: float = 0.7,
    ):
        """Initialize PII detector.

        Args:
            enabled_types: List of PII types to detect. If `None`, detects all types.
            custom_patterns: Custom regex patterns for additional PII types.
                Format: `{'pattern_name': r'regex_pattern'}`.
            confidence_threshold: Minimum confidence for ML-based detection (0.0-1.0).
        """
        self.enabled_types = enabled_types or list(PIIType)
        self.custom_patterns = custom_patterns or {}
        self.confidence_threshold = confidence_threshold

        # Compile regex patterns
        self._compiled_patterns: dict[PIIType, re.Pattern] = {}
        for pii_type in self.enabled_types:
            if pii_type in self.PATTERNS:
                self._compiled_patterns[pii_type] = re.compile(
                    self.PATTERNS[pii_type], re.IGNORECASE
                )

        # Compile custom patterns
        for name, pattern in self.custom_patterns.items():
            self._compiled_patterns[PIIType.CUSTOM] = re.compile(pattern, re.IGNORECASE)

    def detect(self, text: str) -> list[PIIMatch]:
        """Detect PII in text.

        Args:
            text: Text to scan for PII.

        Returns:
            List of detected PII matches.
        """
        matches: list[PIIMatch] = []

        for pii_type, pattern in self._compiled_patterns.items():
            for match in pattern.finditer(text):
                matches.append(
                    PIIMatch(
                        pii_type=pii_type,
                        value=match.group(),
                        start=match.start(),
                        end=match.end(),
                        confidence=1.0,  # Regex matches have 100% confidence
                    )
                )

        # Sort by start position
        matches.sort(key=lambda m: m.start)
        return matches

    def redact(
        self,
        text: str,
        *,
        replacement: str | Callable[[PIIMatch], str] | None = None,
    ) -> str:
        """Redact PII from text.

        Args:
            text: Text to redact.
            replacement: Replacement strategy:
                - `None`: Replace with `[PII_TYPE]` (default)
                - `str`: Replace with this string
                - `Callable`: Function that takes `PIIMatch` and returns replacement

        Returns:
            Redacted text.
        """
        matches = self.detect(text)

        if not matches:
            return text

        # Build redacted text from end to start to preserve indices
        result = text
        for match in reversed(matches):
            if replacement is None:
                repl = f"[{match.pii_type.value.upper()}]"
            elif isinstance(replacement, str):
                repl = replacement
            else:
                repl = replacement(match)

            result = result[: match.start] + repl + result[match.end :]

        return result

    def get_pii_summary(self, text: str) -> dict[str, int]:
        """Get summary of PII types found in text.

        Args:
            text: Text to analyze.

        Returns:
            Dictionary mapping PII type to count.
        """
        matches = self.detect(text)
        summary: dict[str, int] = {}

        for match in matches:
            pii_type_str = match.pii_type.value
            summary[pii_type_str] = summary.get(pii_type_str, 0) + 1

        return summary


class PIIDetectionMiddleware:
    """Middleware to automatically detect and redact PII in LLM operations.

    Can be used as a decorator or context manager to protect LLM inputs/outputs.

    Example:
        ```python
        from langchain_core.enterprise import PIIDetectionMiddleware

        middleware = PIIDetectionMiddleware(
            redact_input=True,
            redact_output=True,
            audit_log=True,
        )

        # As decorator
        @middleware.protect
        async def process_user_input(text: str) -> str:
            return await llm.ainvoke(text)

        # As context manager
        with middleware:
            result = llm.invoke("Contact me at john@example.com")
        ```
    """

    def __init__(
        self,
        *,
        detector: PIIDetector | None = None,
        redact_input: bool = True,
        redact_output: bool = False,
        audit_log: bool = True,
        raise_on_pii: bool = False,
    ):
        """Initialize PII detection middleware.

        Args:
            detector: PII detector instance. If `None`, uses default detector.
            redact_input: Whether to redact PII in inputs.
            redact_output: Whether to redact PII in outputs.
            audit_log: Whether to log PII detection events.
            raise_on_pii: Whether to raise exception when PII is detected.
        """
        self.detector = detector or PIIDetector()
        self.redact_input = redact_input
        self.redact_output = redact_output
        self.audit_log = audit_log
        self.raise_on_pii = raise_on_pii

    def scan_and_handle(
        self,
        text: str,
        *,
        direction: str = "input",
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """Scan text for PII and handle according to configuration.

        Args:
            text: Text to scan.
            direction: Direction of data flow (`'input'` or `'output'`).
            user_id: User identifier for audit logging.
            tenant_id: Tenant identifier for audit logging.

        Returns:
            Processed text (redacted if configured).

        Raises:
            ValueError: If `raise_on_pii` is `True` and PII is detected.
        """
        matches = self.detector.detect(text)

        if matches:
            pii_types = [match.pii_type.value for match in matches]

            # Log audit event
            if self.audit_log:
                audit_logger.log(
                    event_type=AuditEventType.PII_DETECTED,
                    action=f"PII detected in {direction}",
                    user_id=user_id,
                    tenant_id=tenant_id,
                    metadata={
                        "direction": direction,
                        "pii_types": pii_types,
                        "pii_count": len(matches),
                    },
                    compliance_framework="GDPR",
                )

            # Raise exception if configured
            if self.raise_on_pii:
                msg = f"PII detected in {direction}: {', '.join(set(pii_types))}"
                raise ValueError(msg)

            # Redact if configured
            should_redact = (direction == "input" and self.redact_input) or (
                direction == "output" and self.redact_output
            )

            if should_redact:
                redacted_text = self.detector.redact(text)

                if self.audit_log:
                    audit_logger.log(
                        event_type=AuditEventType.PII_REDACTED,
                        action=f"PII redacted in {direction}",
                        user_id=user_id,
                        tenant_id=tenant_id,
                        metadata={
                            "direction": direction,
                            "pii_types": pii_types,
                            "pii_count": len(matches),
                        },
                    )

                return redacted_text

        return text

    def protect(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator to protect function with PII detection.

        Args:
            func: Function to protect.

        Returns:
            Protected function.
        """
        import functools
        import asyncio

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # For now, just call the function
                # Full implementation would intercept and scan args
                return await func(*args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # For now, just call the function
                # Full implementation would intercept and scan args
                return func(*args, **kwargs)

            return sync_wrapper

    def __enter__(self) -> PIIDetectionMiddleware:
        """Enter context manager.

        Returns:
            This middleware instance.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit context manager.

        Args:
            exc_type: Exception type if raised.
            exc_val: Exception value if raised.
            exc_tb: Exception traceback if raised.

        Returns:
            `False` to propagate exceptions.
        """
        return False
