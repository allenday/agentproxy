"""
Data sanitization for telemetry exports.
Prevents sensitive user data (PII, credentials, business logic) from being exported.
"""

import os
import re
from typing import Any, Dict, Optional


class TelemetrySanitizer:
    """
    Sanitizes user-provided data before exporting to telemetry systems.

    This prevents sensitive information like PII, credentials, API keys,
    and confidential business logic from being exposed through telemetry.
    """

    # Patterns that indicate sensitive information
    SENSITIVE_PATTERNS = [
        # Credentials and API keys
        r'api[_-]?key',
        r'password',
        r'secret',
        r'token',
        r'auth',
        r'credential',
        r'private[_-]?key',

        # PII
        r'email',
        r'ssn',
        r'social[_-]?security',
        r'credit[_-]?card',
        r'passport',
        r'driver[_-]?license',

        # Common PII patterns
        r'\b\d{3}-\d{2}-\d{4}\b',  # SSN format
        r'\b\d{16}\b',  # Credit card-like numbers
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
    ]

    def __init__(self):
        """Initialize the sanitizer with configuration from environment."""
        # Allow users to completely disable task description export
        self.export_task_descriptions = os.getenv(
            "AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS", "hash"
        ).lower()

        # Valid values: "none" (don't export), "hash" (export hash only), "sanitized" (redact sensitive), "full" (export everything - DANGEROUS)
        if self.export_task_descriptions not in ["none", "hash", "sanitized", "full"]:
            self.export_task_descriptions = "hash"  # Safe default

        # Parse max task length with error handling
        self.max_task_length = self._parse_max_task_length()

    def _parse_max_task_length(self) -> int:
        """
        Safely parse AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH from environment.

        Returns:
            The parsed integer value, or 100 as default if invalid.
        """
        default_length = 100
        max_length_str = os.getenv("AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH", str(default_length))
        try:
            return int(max_length_str)
        except ValueError:
            # Invalid value - use safe default
            return default_length

    def sanitize_task_description(self, task: str) -> Optional[str]:
        """
        Sanitize a task description for safe export to telemetry.

        Args:
            task: The raw task description from user

        Returns:
            Sanitized version safe for export, or None if export is disabled
        """
        if not task:
            return None

        mode = self.export_task_descriptions

        if mode == "none":
            # Don't export task descriptions at all
            return None

        elif mode == "hash":
            # Export only a hash for task correlation, no actual content
            import hashlib
            task_hash = hashlib.sha256(task.encode()).hexdigest()[:16]
            return f"task_{task_hash}"

        elif mode == "sanitized":
            # Export with sensitive patterns redacted
            sanitized = task

            # Redact patterns that look sensitive
            for pattern in self.SENSITIVE_PATTERNS:
                sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)

            # Truncate to prevent excessive data export
            if len(sanitized) > self.max_task_length:
                sanitized = sanitized[:self.max_task_length] + "..."

            return sanitized

        elif mode == "full":
            # DANGEROUS: Export everything
            # Only use in trusted, internal telemetry systems
            if len(task) > self.max_task_length:
                return task[:self.max_task_length] + "..."
            return task

        return None

    def sanitize_string_value(self, value: str) -> str:
        """
        Sanitize a single string value by redacting sensitive patterns.

        This method applies pattern-based sanitization to any string value,
        useful for paths, arguments, and other string attributes that might
        inadvertently contain sensitive information.

        Args:
            value: The string value to sanitize

        Returns:
            Sanitized string with sensitive patterns redacted
        """
        if not value or not isinstance(value, str):
            return value

        sanitized = value

        # Apply all sensitive patterns
        for pattern in self.SENSITIVE_PATTERNS:
            sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)

        return sanitized

    def sanitize_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize all attributes in a dictionary.

        This method applies appropriate sanitization to all attribute values:
        - Task description attributes: Full task sanitization (hash/none/sanitized/full modes)
        - String values: Pattern-based sanitization to remove sensitive data
        - Other types: Passed through as-is

        Args:
            attributes: Dictionary of span/metric attributes

        Returns:
            Sanitized dictionary safe for export
        """
        sanitized = {}

        for key, value in attributes.items():
            # Check if this is a task description attribute
            if "task" in key.lower() and "description" in key.lower():
                if isinstance(value, str):
                    sanitized_value = self.sanitize_task_description(value)
                    if sanitized_value is not None:
                        sanitized[key] = sanitized_value
                    # If None, omit the attribute entirely
            elif isinstance(value, str):
                # For any other string attribute, apply pattern-based sanitization
                # This protects against sensitive data in paths, arguments, etc.
                sanitized[key] = self.sanitize_string_value(value)
            else:
                # For non-string attributes (numbers, booleans, etc.), keep as-is
                sanitized[key] = value

        return sanitized


# Global singleton
_sanitizer: Optional[TelemetrySanitizer] = None


def get_sanitizer() -> TelemetrySanitizer:
    """Get or create global sanitizer instance."""
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = TelemetrySanitizer()
    return _sanitizer


def reset_sanitizer():
    """Reset global sanitizer instance (for testing)."""
    global _sanitizer
    _sanitizer = None
