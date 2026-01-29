# AgentProxy Documentation

This directory contains comprehensive documentation for the AgentProxy (PA) system.

## Architecture & Implementation

### Error Handling
- [Gemini Error Flow Diagram](gemini_error_flow.md) - Visual flow of error handling logic

### Privacy & Telemetry
- [Telemetry Privacy](TELEMETRY_PRIVACY.md) - Privacy considerations for telemetry data collection

## Quick Start

For information on getting started with AgentProxy, see the main [README](../README.md).

## Testing

Test files are organized in the `tests/` directory:
- `tests/unit/` - Unit tests for individual components
- `tests/integration/` - Integration tests for complete workflows

Run tests with:
```bash
pytest tests/
```

## Contributing

When adding new features:
1. Document implementation details in this directory
2. Add tests to the appropriate `tests/` subdirectory
3. Update relevant documentation files
