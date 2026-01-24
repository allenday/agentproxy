"""
Integration test demonstrating sensitive data protection in telemetry.
This test verifies that the security fix prevents sensitive data exposure.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from agentproxy.telemetry_sanitizer import get_sanitizer, reset_sanitizer


class TestSensitiveDataProtection:
    """End-to-end test showing sensitive data is protected."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_credentials_never_exported_in_default_mode(self):
        """
        SECURITY TEST: Verify credentials are never exported with default config.
        This test demonstrates the fix for the critical security vulnerability.
        """
        # Default mode (hash) should be used when env var is not set
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            # Simulate a user task with multiple sensitive data points
            dangerous_task = (
                "Fix authentication using API_KEY sk-abc123xyz, "
                "update password for user@company.com, "
                "store secret token xyz789 in config"
            )

            # Sanitize the task (this is what PA does internally)
            sanitized = sanitizer.sanitize_task_description(dangerous_task)

            # SECURITY ASSERTIONS: None of these should appear in output
            assert "API_KEY" not in sanitized
            assert "sk-abc123xyz" not in sanitized
            assert "password" not in sanitized
            assert "user@company.com" not in sanitized
            assert "secret" not in sanitized
            assert "token" not in sanitized
            assert "xyz789" not in sanitized
            assert "authentication" not in sanitized
            assert "config" not in sanitized

            # Only a hash should be present
            assert sanitized.startswith("task_")
            assert len(sanitized) == 21  # "task_" + 16 char hash

    def test_pii_never_exported_in_default_mode(self):
        """
        SECURITY TEST: Verify PII is never exported with default config.
        """
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            # Task with various PII
            pii_task = (
                "Send email to john.doe@example.com and jane@corp.com "
                "with SSN 123-45-6789 and credit card 4532123456789012"
            )

            sanitized = sanitizer.sanitize_task_description(pii_task)

            # SECURITY ASSERTIONS: No PII should leak
            assert "john.doe@example.com" not in sanitized
            assert "jane@corp.com" not in sanitized
            assert "123-45-6789" not in sanitized
            assert "4532123456789012" not in sanitized
            assert "@example.com" not in sanitized
            assert "@corp.com" not in sanitized

            # Only hash
            assert sanitized.startswith("task_")

    def test_business_logic_never_exported_in_default_mode(self):
        """
        SECURITY TEST: Verify proprietary business logic is not exported.
        """
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            # Task with confidential business logic
            confidential_task = (
                "Implement proprietary algorithm using our secret_key "
                "for auth_token generation with private_key RSA-2048"
            )

            sanitized = sanitizer.sanitize_task_description(confidential_task)

            # SECURITY ASSERTIONS: Sensitive business info should not leak
            assert "secret_key" not in sanitized
            assert "auth_token" not in sanitized
            assert "private_key" not in sanitized
            # General content also should not be present (hash mode)
            assert "proprietary" not in sanitized
            assert "algorithm" not in sanitized

            # Only hash
            assert sanitized.startswith("task_")

    def test_none_mode_exports_nothing(self):
        """
        SECURITY TEST: None mode should export nothing at all.
        """
        with patch.dict(os.environ, {"AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS": "none"}):
            sanitizer = get_sanitizer()

            dangerous_task = "Any task with API_KEY and password"
            sanitized = sanitizer.sanitize_task_description(dangerous_task)

            # Should export nothing
            assert sanitized is None

    def test_sanitize_attributes_protects_task_descriptions(self):
        """
        SECURITY TEST: Verify sanitize_attributes protects task.description fields.
        This mimics what PA.run_task() does.
        """
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            # Simulate PA's attribute dictionary with sensitive task
            raw_attributes = {
                "pa.task.description": "Fix auth with API_KEY secret123 and password xyz",
                "pa.working_dir": "/home/user/project",
                "pa.max_iterations": 100,
            }

            safe_attributes = sanitizer.sanitize_attributes(raw_attributes)

            # Task description should be sanitized (hashed)
            assert "pa.task.description" in safe_attributes
            task_desc = safe_attributes["pa.task.description"]

            # SECURITY ASSERTIONS: No sensitive data in exported attributes
            assert "API_KEY" not in task_desc
            assert "secret123" not in task_desc
            assert "password" not in task_desc
            assert "xyz" not in task_desc
            assert "auth" not in task_desc

            # Should be a hash
            assert task_desc.startswith("task_")

            # Other attributes should pass through unchanged
            assert safe_attributes["pa.working_dir"] == "/home/user/project"
            assert safe_attributes["pa.max_iterations"] == 100

    def test_demonstrates_vulnerability_fix(self):
        """
        SECURITY TEST: Demonstrate that the original vulnerability is fixed.

        BEFORE THE FIX:
        - User task: "Fix API_KEY abc123"
        - Exported: "Fix API_KEY abc123" (VULNERABLE!)

        AFTER THE FIX:
        - User task: "Fix API_KEY abc123"
        - Exported: "task_7f3a8c9d2e1b4f6a" (SAFE!)
        """
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            # The exact scenario from the vulnerability report
            vulnerable_task = "Fix API_KEY abc123"

            # What is actually exported now
            safe_export = sanitizer.sanitize_task_description(vulnerable_task)

            # BEFORE (vulnerable): Would export "Fix API_KEY abc123"
            # AFTER (fixed): Exports only hash
            assert safe_export != vulnerable_task
            assert "API_KEY" not in safe_export
            assert "abc123" not in safe_export
            assert safe_export.startswith("task_")

            print(f"\n[SECURITY FIX VERIFIED]")
            print(f"User task: '{vulnerable_task}'")
            print(f"Exported:  '{safe_export}'")
            print(f"✅ Sensitive data is protected!")


class TestComplianceScenarios:
    """Test compliance with various data protection regulations."""

    def setup_method(self):
        """Reset sanitizer before each test."""
        reset_sanitizer()

    def test_gdpr_compliance_no_pii_export(self):
        """
        GDPR COMPLIANCE: Ensure no PII is exported in default mode.
        """
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            task_with_pii = "Process order for user@example.com in EU region"
            sanitized = sanitizer.sanitize_task_description(task_with_pii)

            # GDPR: No personal data should be exported
            assert "user@example.com" not in sanitized
            assert "@example.com" not in sanitized

    def test_hipaa_compliance_no_health_data_export(self):
        """
        HIPAA COMPLIANCE: Ensure no health data or PII is exported.
        """
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            # Task with health-related PII
            health_task = "Update patient record SSN 123-45-6789 for john@hospital.com"
            sanitized = sanitizer.sanitize_task_description(health_task)

            # HIPAA: No PHI should be exported
            assert "123-45-6789" not in sanitized
            assert "john@hospital.com" not in sanitized
            assert "patient" not in sanitized  # Even non-PII context removed in hash mode

    def test_pci_compliance_no_payment_data_export(self):
        """
        PCI DSS COMPLIANCE: Ensure no payment card data is exported.
        """
        with patch.dict(os.environ, {}, clear=True):
            sanitizer = get_sanitizer()

            payment_task = "Process payment with card 4532123456789012 CVV 123"
            sanitized = sanitizer.sanitize_task_description(payment_task)

            # PCI DSS: No cardholder data
            assert "4532123456789012" not in sanitized
            assert "123" not in sanitized
            assert "card" not in sanitized  # Hash mode removes all content
