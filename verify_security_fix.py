#!/usr/bin/env python3
"""
Verification script for the sanitize_attributes security fix.
Demonstrates that all string attributes are now properly sanitized.
"""

import os
from agentproxy.telemetry_sanitizer import TelemetrySanitizer

def main():
    print("=" * 70)
    print("SECURITY FIX VERIFICATION: sanitize_attributes()")
    print("=" * 70)
    print()

    # Create sanitizer instance
    sanitizer = TelemetrySanitizer()

    # Test case 1: Sensitive data in various string attributes
    print("Test 1: Sensitive data in string attributes")
    print("-" * 70)

    vulnerable_attributes = {
        "pa.task.description": "Fix login with API_KEY abc123",
        "pa.working_dir": "/home/alice/password_storage/project",
        "pa.user_input": "Use secret token xyz789 for auth",
        "pa.email_field": "Contact user@example.com",
        "pa.max_iterations": 100,
        "pa.status": "running",
    }

    print("BEFORE sanitization:")
    for key, value in vulnerable_attributes.items():
        print(f"  {key}: {value}")

    sanitized = sanitizer.sanitize_attributes(vulnerable_attributes)

    print("\nAFTER sanitization:")
    for key, value in sanitized.items():
        print(f"  {key}: {value}")

    print("\nVerification:")
    # Check that sensitive patterns are redacted
    all_values = " ".join(str(v) for v in sanitized.values())

    checks = [
        ("API_KEY", "API_KEY" not in all_values.upper()),
        ("password", "password" not in all_values.lower()),
        ("secret", "secret" not in all_values.lower()),
        ("token", "token" not in all_values.lower()),
        ("user@example.com", "user@example.com" not in all_values),
    ]

    for pattern, is_safe in checks:
        status = "✓ SAFE" if is_safe else "✗ LEAKED"
        print(f"  {status}: '{pattern}' {'not found' if is_safe else 'FOUND'}")

    print()

    # Test case 2: Safe strings are preserved
    print("Test 2: Safe strings are preserved")
    print("-" * 70)

    safe_attributes = {
        "pa.working_dir": "/home/user/project",
        "pa.function_name": "calculate_total",
        "pa.status": "completed",
        "pa.iteration": 5,
    }

    print("BEFORE sanitization:")
    for key, value in safe_attributes.items():
        print(f"  {key}: {value}")

    sanitized_safe = sanitizer.sanitize_attributes(safe_attributes)

    print("\nAFTER sanitization:")
    for key, value in sanitized_safe.items():
        print(f"  {key}: {value}")

    print("\nVerification:")
    # Check that safe values are preserved
    preserved = all(
        str(sanitized_safe.get(k)) == str(v)
        for k, v in safe_attributes.items()
    )

    status = "✓ PRESERVED" if preserved else "✗ MODIFIED"
    print(f"  {status}: All safe values {'preserved exactly' if preserved else 'were modified'}")

    print()
    print("=" * 70)

    # Overall result
    all_safe = all(check[1] for check in checks) and preserved

    if all_safe:
        print("✓ SECURITY FIX VERIFIED: All sensitive data properly sanitized!")
    else:
        print("✗ SECURITY ISSUE: Some sensitive data may have leaked!")

    print("=" * 70)

if __name__ == "__main__":
    main()
