# Telemetry Privacy and Security

## Overview

AgentProxy's telemetry system includes robust privacy controls to prevent sensitive user data from being exported to external telemetry systems. This document describes the security measures and configuration options available.

## The Problem

User-provided task descriptions can contain highly sensitive information:
- **Personal Identifiable Information (PII)**: emails, SSNs, credit card numbers
- **Credentials**: API keys, passwords, tokens, secrets
- **Confidential Business Logic**: proprietary algorithms, trade secrets

Without proper controls, this data could be exposed through telemetry exports to external systems.

## The Solution

AgentProxy implements a **multi-layered data sanitization system** that protects sensitive information before it reaches telemetry exporters.

### Default Behavior: Hash Mode

**By default, task descriptions are hashed before export.** This provides:
- **Zero sensitive data exposure**: Only a hash is exported, not actual content
- **Task correlation**: Same tasks produce same hashes for metrics
- **Complete privacy**: Original task content cannot be recovered from hash

Example:
```python
# User task (never exported)
"Fix login with API_KEY abc123 and password xyz789"

# What telemetry sees
"task_7f3a8c9d2e1b4f6a"
```

## Configuration Options

Control telemetry data export via the `AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS` environment variable:

### 1. `none` - No Export (Maximum Privacy)
```bash
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=none
```
- Task descriptions are **not exported at all**
- Use when compliance requires no user data in telemetry
- Provides maximum privacy but loses task correlation

### 2. `hash` - Hash Only (Default, Recommended)
```bash
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=hash
```
- Only a cryptographic hash is exported
- **No sensitive data can leak**
- Allows correlation of same tasks
- **This is the default and recommended setting**

### 3. `sanitized` - Redacted Export
```bash
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=sanitized
```
- Exports task description with sensitive patterns redacted
- Automatically detects and redacts:
  - Credentials: `api_key`, `password`, `secret`, `token`, `auth`
  - PII: emails, SSNs, credit card numbers
  - Private keys and certificates
- Useful for debugging while maintaining privacy

Example:
```python
# User task
"Update API_KEY for user@example.com with password abc123"

# What telemetry sees
"Update [REDACTED] for [REDACTED] with [REDACTED] abc123"
```

### 4. `full` - Full Export (⚠️ DANGEROUS)
```bash
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=full
```
- Exports complete task descriptions **without redaction**
- **Only use in trusted, internal telemetry systems**
- **Never use when exporting to third-party services**
- Still respects max length truncation

## Additional Privacy Controls

### Maximum Task Length
```bash
AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH=100
```
Limits the length of exported task descriptions (default: 100 characters).
Prevents excessive data export even in `sanitized` or `full` modes.

### Complete Telemetry Disable
```bash
AGENTPROXY_ENABLE_TELEMETRY=0
```
Disables all telemetry collection and export.

## Sensitive Pattern Detection

The sanitizer automatically detects and redacts these patterns:

### Credentials
- `api_key`, `api-key`, `apikey`
- `password`, `passwd`, `pwd`
- `secret`, `client_secret`
- `token`, `auth_token`, `access_token`
- `credential`, `credentials`
- `private_key`, `private-key`

### PII (Personal Identifiable Information)
- Email addresses: `user@example.com`
- SSN format: `123-45-6789`
- Credit card-like numbers: 16-digit sequences
- Other PII keywords: `ssn`, `social_security`, `passport`, `driver_license`

## Best Practices

### For Production Environments
1. **Always use `hash` mode (default)** unless you have specific requirements
2. **Never use `full` mode** when exporting to third-party telemetry services
3. Review your telemetry configuration before deployment
4. Ensure `AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS` is not set to `full`

### For Development Environments
1. Use `sanitized` mode for debugging task-related issues
2. Review redacted output to ensure sensitive patterns are caught
3. Consider `none` mode when working with highly sensitive data

### For Compliance (GDPR, HIPAA, etc.)
1. Use `none` mode to completely prevent PII export
2. Document your telemetry configuration in compliance audits
3. Review telemetry exports regularly to verify no PII leakage

## Example Configurations

### Maximum Privacy (Compliance-Focused)
```bash
AGENTPROXY_ENABLE_TELEMETRY=0
```
or
```bash
AGENTPROXY_ENABLE_TELEMETRY=1
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=none
```

### Balanced (Production-Recommended)
```bash
AGENTPROXY_ENABLE_TELEMETRY=1
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=hash
AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH=100
```

### Debug-Friendly (Development Only)
```bash
AGENTPROXY_ENABLE_TELEMETRY=1
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=sanitized
AGENTPROXY_TELEMETRY_MAX_TASK_LENGTH=200
```

### Internal Telemetry (Trusted Systems Only)
```bash
AGENTPROXY_ENABLE_TELEMETRY=1
AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS=full
OTEL_EXPORTER_OTLP_ENDPOINT=http://internal-telemetry.company.local:4317
```

## Testing Privacy Controls

Run the sanitizer test suite to verify privacy protections:
```bash
pytest tests/test_telemetry_sanitizer.py -v
```

The test suite verifies:
- ✅ Credentials are never exported in sanitized mode
- ✅ PII is redacted correctly
- ✅ Hash mode produces no readable data
- ✅ Configuration modes work as expected

## Security Audit Checklist

Before deploying with telemetry enabled:

- [ ] Review `AGENTPROXY_TELEMETRY_EXPORT_TASK_DESCRIPTIONS` setting
- [ ] Verify it's NOT set to `full` (unless using trusted internal systems)
- [ ] Confirm telemetry endpoint is trusted and secure
- [ ] Test with sample sensitive data to verify redaction
- [ ] Document telemetry configuration for compliance
- [ ] Review exported telemetry data to verify no PII leaks

## Questions?

If you have questions about telemetry privacy or need custom sanitization rules, please:
1. Review this documentation
2. Check the sanitizer source code: `agentproxy/telemetry_sanitizer.py`
3. Review test cases: `tests/test_telemetry_sanitizer.py`
4. Open an issue on GitHub

## Summary

🔒 **Default behavior is secure**: Task descriptions are hashed by default, preventing sensitive data exposure.

⚙️ **Configurable privacy levels**: Choose from `none`, `hash`, `sanitized`, or `full` based on your needs.

🛡️ **Automatic pattern detection**: Credentials, PII, and sensitive patterns are automatically redacted.

✅ **Tested and verified**: Comprehensive test suite ensures privacy controls work correctly.
