"""
Unit tests for telemetry data sanitization.
Ensures sensitive user data is never exported to telemetry systems.
"""

import os
import pytest
from unittest.mock import patch

from agentproxy.telemetry_sanitizer import TelemetrySanitizer, get_sanitizer, reset_sanitizer


class TestTelemetrySanitizer:
    """Test telemetry sanitizer prevents sensitive data exposure."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_default_mode_is_hash(self):
        """By default, should use hash mode for safety."""
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = TelemetrySanitizer()
            assert sanitizer.export_task_descriptions == "hash"

    def test_none_mode_returns_none(self):
        """In 'none' mode, should not export task descriptions at all."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "none"}):
            sanitizer = TelemetrySanitizer()
            result = sanitizer.sanitize_task_description("Create a login page with password field")
            assert result is None

    def test_hash_mode_returns_hash_only(self):
        """In 'hash' mode, should return hash only, no actual content."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "hash"}):
            sanitizer = TelemetrySanitizer()
            task = "Fix authentication with API key abc123xyz"
            result = sanitizer.sanitize_task_description(task)

            # Should return a hash format
            assert result is not None
            assert result.startswith("task_")
            # Should not contain any part of the original task
            assert "authentication" not in result
            assert "API key" not in result.lower()
            assert "abc123xyz" not in result

    def test_hash_mode_consistent_for_same_input(self):
        """Hash mode should produce consistent hashes for same input."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "hash"}):
            sanitizer = TelemetrySanitizer()
            task = "Same task description"

            result1 = sanitizer.sanitize_task_description(task)
            result2 = sanitizer.sanitize_task_description(task)

            assert result1 == result2

    def test_hash_mode_different_for_different_input(self):
        """Hash mode should produce different hashes for different input."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "hash"}):
            sanitizer = TelemetrySanitizer()

            result1 = sanitizer.sanitize_task_description("Task A")
            result2 = sanitizer.sanitize_task_description("Task B")

            assert result1 != result2

    def test_sanitized_mode_redacts_api_keys(self):
        """In 'sanitized' mode, should redact API key patterns."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Update the API_KEY configuration"
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert "API_KEY" not in result
            assert "[REDACTED]" in result

    def test_sanitized_mode_redacts_passwords(self):
        """In 'sanitized' mode, should redact password patterns."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Fix the password reset flow"
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert "password" not in result.lower()
            assert "[REDACTED]" in result

    def test_sanitized_mode_redacts_secrets(self):
        """In 'sanitized' mode, should redact secret patterns."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Store the client_secret in the database"
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert "secret" not in result.lower()
            assert "[REDACTED]" in result

    def test_sanitized_mode_redacts_tokens(self):
        """In 'sanitized' mode, should redact token patterns."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Validate the auth_token before proceeding"
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert "token" not in result.lower()
            assert "[REDACTED]" in result

    def test_sanitized_mode_redacts_emails(self):
        """In 'sanitized' mode, should redact email addresses (PII)."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Send notification to user@example.com about the update"
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert "user@example.com" not in result
            assert "[REDACTED]" in result

    def test_sanitized_mode_redacts_ssn_patterns(self):
        """In 'sanitized' mode, should redact SSN-like patterns."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Verify SSN 123-45-6789 is valid"
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert "123-45-6789" not in result
            assert "[REDACTED]" in result

    def test_sanitized_mode_redacts_credit_card_patterns(self):
        """In 'sanitized' mode, should redact credit card-like numbers."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Process payment with card 4532123456789012"
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert "4532123456789012" not in result
            assert "[REDACTED]" in result

    def test_sanitized_mode_truncates_long_tasks(self):
        """In 'sanitized' mode, should truncate long task descriptions."""
        with patch.dict(os.environ, {
            "AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized",
            "AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH": "50"
        }):
            sanitizer = TelemetrySanitizer()
            task = "A" * 200  # Very long task
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert len(result) <= 53  # 50 + "..."
            assert result.endswith("...")

    def test_sanitized_mode_preserves_safe_content(self):
        """In 'sanitized' mode, should preserve non-sensitive content."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            task = "Create a new React component for the dashboard"
            result = sanitizer.sanitize_task_description(task)

            # This task has no sensitive patterns, should be preserved
            assert result is not None
            assert "React" in result
            assert "component" in result
            assert "dashboard" in result

    def test_full_mode_exports_everything(self):
        """In 'full' mode, should export everything (DANGEROUS)."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "full"}):
            sanitizer = TelemetrySanitizer()
            task = "Update API_KEY with password abc123 for user@example.com"
            result = sanitizer.sanitize_task_description(task)

            # Full mode exports everything, no redaction
            assert result is not None
            assert "API_KEY" in result
            assert "password" in result
            assert "user@example.com" in result

    def test_full_mode_still_truncates(self):
        """In 'full' mode, should still truncate very long content."""
        with patch.dict(os.environ, {
            "AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "full",
            "AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH": "50"
        }):
            sanitizer = TelemetrySanitizer()
            task = "A" * 200
            result = sanitizer.sanitize_task_description(task)

            assert result is not None
            assert len(result) <= 53  # 50 + "..."

    def test_invalid_mode_defaults_to_hash(self):
        """Invalid mode should default to safe 'hash' mode."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "invalid_mode"}):
            sanitizer = TelemetrySanitizer()
            assert sanitizer.export_task_descriptions == "hash"

    def test_sanitize_attributes_handles_task_description(self):
        """sanitize_attributes should sanitize task.description fields."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "hash"}):
            sanitizer = TelemetrySanitizer()
            attributes = {
                "pa.task.description": "Sensitive API_KEY data",
                "pa.working_dir": "/home/user/project",
                "pa.max_iterations": 100,
            }
            result = sanitizer.sanitize_attributes(attributes)

            # Task description should be hashed
            assert "pa.task.description" in result
            assert result["pa.task.description"].startswith("task_")
            assert "API_KEY" not in result["pa.task.description"]

            # Other attributes should pass through
            assert result["pa.working_dir"] == "/home/user/project"
            assert result["pa.max_iterations"] == 100

    def test_sanitize_attributes_removes_none_task_descriptions(self):
        """If task description sanitizes to None, should omit the attribute."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "none"}):
            sanitizer = TelemetrySanitizer()
            attributes = {
                "pa.task.description": "Some task",
                "pa.working_dir": "/home/user/project",
            }
            result = sanitizer.sanitize_attributes(attributes)

            # Task description should be removed
            assert "pa.task.description" not in result

            # Other attributes should remain
            assert result["pa.working_dir"] == "/home/user/project"

    def test_sanitize_attributes_redacts_sensitive_strings(self):
        """String attributes containing sensitive patterns should be redacted."""
        sanitizer = TelemetrySanitizer()
        attributes = {
            "pa.working_dir": "/home/user/api_key_config/project",
            "pa.argument": "Use password secret123 for auth",
            "pa.max_iterations": 100,
            "pa.user_input": "Contact user@example.com for details",
        }
        result = sanitizer.sanitize_attributes(attributes)

        # Sensitive patterns in strings should be redacted
        assert "api_key" not in result["pa.working_dir"].lower()
        assert "[REDACTED]" in result["pa.working_dir"]

        assert "password" not in result["pa.argument"].lower()
        assert "secret123" not in result["pa.argument"]
        assert "[REDACTED]" in result["pa.argument"]

        assert "user@example.com" not in result["pa.user_input"]
        assert "[REDACTED]" in result["pa.user_input"]

        # Non-string attributes should pass through unchanged
        assert result["pa.max_iterations"] == 100

    def test_sanitize_attributes_preserves_safe_strings(self):
        """String attributes without sensitive patterns should be preserved."""
        sanitizer = TelemetrySanitizer()
        attributes = {
            "pa.working_dir": "/home/user/project",
            "pa.function_name": "calculate_total",
            "pa.status": "completed",
        }
        result = sanitizer.sanitize_attributes(attributes)

        # Safe strings should be preserved exactly
        assert result["pa.working_dir"] == "/home/user/project"
        assert result["pa.function_name"] == "calculate_total"
        assert result["pa.status"] == "completed"

    def test_sanitize_string_value_redacts_patterns(self):
        """sanitize_string_value should redact sensitive patterns."""
        sanitizer = TelemetrySanitizer()

        # Test various sensitive patterns
        assert "[REDACTED]" in sanitizer.sanitize_string_value("my_api_key is secret")
        assert "api_key" not in sanitizer.sanitize_string_value("my_api_key is secret").lower()

        assert "[REDACTED]" in sanitizer.sanitize_string_value("password: abc123")
        assert "password" not in sanitizer.sanitize_string_value("password: abc123").lower()

        assert "[REDACTED]" in sanitizer.sanitize_string_value("email user@example.com")
        assert "user@example.com" not in sanitizer.sanitize_string_value("email user@example.com")

    def test_sanitize_string_value_preserves_safe_content(self):
        """sanitize_string_value should preserve non-sensitive content."""
        sanitizer = TelemetrySanitizer()

        safe_values = [
            "/home/user/project",
            "calculate_total",
            "completed",
            "React component dashboard",
        ]

        for value in safe_values:
            result = sanitizer.sanitize_string_value(value)
            assert result == value, f"Safe value was modified: {value} -> {result}"

    def test_sanitize_string_value_handles_empty_strings(self):
        """sanitize_string_value should handle empty/None strings."""
        sanitizer = TelemetrySanitizer()

        assert sanitizer.sanitize_string_value("") == ""
        assert sanitizer.sanitize_string_value(None) is None

    def test_empty_task_returns_none(self):
        """Empty task should return None."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()
            assert sanitizer.sanitize_task_description("") is None
            assert sanitizer.sanitize_task_description(None) is None

    def test_get_sanitizer_singleton(self):
        """get_sanitizer should return singleton instance."""
        sanitizer1 = get_sanitizer()
        sanitizer2 = get_sanitizer()
        assert sanitizer1 is sanitizer2

    def test_invalid_max_task_length_uses_default(self):
        """Invalid AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH should use default (100)."""
        with patch.dict(os.environ, {
            "AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized",
            "AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH": "not_a_number"
        }):
            # Should not raise ValueError, should use default
            sanitizer = TelemetrySanitizer()
            assert sanitizer.max_task_length == 100

            task = "A" * 200
            result = sanitizer.sanitize_task_description(task)
            assert result is not None
            assert len(result) <= 103  # 100 + "..."
            assert result.endswith("...")

    def test_empty_max_task_length_uses_default(self):
        """Empty AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH should use default (100)."""
        with patch.dict(os.environ, {
            "AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized",
            "AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH": ""
        }):
            # Should not raise ValueError, should use default
            sanitizer = TelemetrySanitizer()
            assert sanitizer.max_task_length == 100


class TestSensitivePatterns:
    """Test detection of various sensitive patterns."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_detects_various_credential_patterns(self):
        """Should detect various credential-related terms."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "sanitized"}):
            sanitizer = TelemetrySanitizer()

            patterns = [
                "api_key",
                "api-key",
                "apikey",
                "password",
                "secret",
                "token",
                "auth",
                "credential",
                "private_key",
                "private-key",
            ]

            for pattern in patterns:
                task = f"Update the {pattern} configuration"
                result = sanitizer.sanitize_task_description(task)
                assert "[REDACTED]" in result, f"Failed to redact: {pattern}"
                assert pattern not in result.lower(), f"Pattern leaked: {pattern}"


class TestIntegrationWithPA:
    """Test sanitizer integration with PA telemetry."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_pa_uses_sanitizer_by_default(self):
        """PA should use sanitizer by default to protect user data."""
        # This is a mock test - actual integration test would require full PA setup
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "hash"}):
            sanitizer = get_sanitizer()

            # Simulate what PA does
            raw_task = "Fix login with API_KEY abc123 and password xyz789"
            sanitized = sanitizer.sanitize_task_description(raw_task)

            # Should be hashed, not contain sensitive data
            assert sanitized is not None
            assert "API_KEY" not in sanitized
            assert "password" not in sanitized
            assert "abc123" not in sanitized
            assert "xyz789" not in sanitized
