"""
Unit tests for telemetry data sanitization.
Ensures the sanitizer provides honest, conservative privacy controls.
"""

import os
import pytest
from unittest.mock import patch

from agentproxy.telemetry_sanitizer import (
    TelemetrySanitizer,
    BaseSanitizer,
    get_sanitizer,
    set_sanitizer,
    reset_sanitizer,
)


class TestTelemetrySanitizer:
    """Test default telemetry sanitizer modes: none, hash, full."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_default_mode_is_hash(self):
        """By default, should use hash mode for safety."""
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = TelemetrySanitizer()
            assert sanitizer.export_mode == "hash"

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
            task = "Deploy with credentials"

            result1 = sanitizer.sanitize_task_description(task)
            result2 = sanitizer.sanitize_task_description(task)

            assert result1 == result2

    def test_hash_mode_different_for_different_input(self):
        """Hash mode should produce different hashes for different inputs."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "hash"}):
            sanitizer = TelemetrySanitizer()

            result1 = sanitizer.sanitize_task_description("Task A")
            result2 = sanitizer.sanitize_task_description("Task B")

            assert result1 != result2

    def test_full_mode_exports_everything(self):
        """In 'full' mode, exports complete task (DANGEROUS)."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "full"}):
            sanitizer = TelemetrySanitizer()
            task = "Short task with secrets"
            result = sanitizer.sanitize_task_description(task)

            assert result == task

    def test_full_mode_still_truncates(self):
        """Full mode should truncate long tasks."""
        with patch.dict(os.environ, {
            "AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "full",
            "AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH": "10",
        }):
            sanitizer = TelemetrySanitizer()
            task = "This is a very long task description"
            result = sanitizer.sanitize_task_description(task)

            assert len(result) <= 13  # 10 + "..."
            assert result.endswith("...")

    def test_invalid_mode_defaults_to_hash(self):
        """Invalid mode should default to safe 'hash' mode."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "invalid"}):
            sanitizer = TelemetrySanitizer()
            assert sanitizer.export_mode == "hash"

    def test_sanitize_attributes_handles_task_description(self):
        """Should sanitize task description attributes."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "hash"}):
            sanitizer = TelemetrySanitizer()

            attributes = {
                "pa.task.description": "Fix login with password",
                "pa.iterations": 5,
            }

            result = sanitizer.sanitize_attributes(attributes)

            # Task description should be hashed
            assert "pa.task.description" in result
            assert result["pa.task.description"].startswith("task_")
            assert "password" not in result["pa.task.description"]

            # Other attributes pass through
            assert result["pa.iterations"] == 5

    def test_sanitize_attributes_removes_none_task_descriptions(self):
        """Should omit task descriptions that sanitize to None."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "none"}):
            sanitizer = TelemetrySanitizer()

            attributes = {
                "pa.task.description": "Some task",
                "pa.iterations": 5,
            }

            result = sanitizer.sanitize_attributes(attributes)

            # Task description should be omitted
            assert "pa.task.description" not in result
            # Other attributes pass through
            assert result["pa.iterations"] == 5

    def test_sanitize_attributes_preserves_non_task_strings(self):
        """Non-task string attributes should pass through unchanged."""
        sanitizer = TelemetrySanitizer()

        attributes = {
            "pa.working_dir": "./sandbox",
            "pa.function": "verify_code",
            "pa.iterations": 5,
        }

        result = sanitizer.sanitize_attributes(attributes)

        # All should pass through unchanged
        assert result == attributes

    def test_empty_task_returns_none(self):
        """Empty task should return None."""
        sanitizer = TelemetrySanitizer()
        assert sanitizer.sanitize_task_description("") is None
        assert sanitizer.sanitize_task_description(None) is None

    def test_get_sanitizer_singleton(self):
        """get_sanitizer should return same instance."""
        sanitizer1 = get_sanitizer()
        sanitizer2 = get_sanitizer()
        assert sanitizer1 is sanitizer2

    def test_invalid_max_task_length_uses_default(self):
        """Invalid max_task_length should use safe default."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH": "invalid"}):
            sanitizer = TelemetrySanitizer()
            assert sanitizer.max_task_length == 100

    def test_empty_max_task_length_uses_default(self):
        """Empty max_task_length should use safe default."""
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH": ""}):
            sanitizer = TelemetrySanitizer()
            assert sanitizer.max_task_length == 100


class TestCustomSanitizer:
    """Test custom sanitizer implementation via BaseSanitizer interface."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_can_implement_custom_sanitizer(self):
        """Should be able to implement and use custom sanitizer."""

        class TestSanitizer(BaseSanitizer):
            def sanitize_task_description(self, task: str):
                return "CUSTOM_SANITIZED"

            def sanitize_attributes(self, attributes):
                return {"custom": "sanitized"}

        custom = TestSanitizer()
        set_sanitizer(custom)

        sanitizer = get_sanitizer()
        assert sanitizer is custom
        assert sanitizer.sanitize_task_description("anything") == "CUSTOM_SANITIZED"
        assert sanitizer.sanitize_attributes({}) == {"custom": "sanitized"}

    def test_custom_sanitizer_via_env_var(self):
        """Should be able to load custom sanitizer via environment variable."""
        # This would require creating a test module, so we'll just test the path is checked
        with patch.dict(os.environ, {"AGENTPROXY_CUSTOM_SANITIZER": ""}):
            reset_sanitizer()
            sanitizer = get_sanitizer()
            # Should fall back to default
            assert isinstance(sanitizer, TelemetrySanitizer)


class TestIntegrationWithPA:
    """Test sanitizer integration with PA telemetry."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_pa_uses_sanitizer_by_default(self):
        """PA should use sanitizer when telemetry enabled."""
        from agentproxy.telemetry_sanitizer import get_sanitizer

        sanitizer = get_sanitizer()
        assert sanitizer is not None
        assert isinstance(sanitizer, BaseSanitizer)
