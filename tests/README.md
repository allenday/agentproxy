# AgentProxy Tests

This directory contains unit and integration tests for agentproxy.

## Test Organization

```
tests/
├── test_*.py              # Unit tests (fast, no external dependencies)
└── integration/
    └── test_*_e2e.py      # Integration tests (require docker compose)
```

## Running Tests

### Unit Tests Only (Fast)

```bash
# Run all unit tests
pytest tests/ -m "not integration"

# Run specific test file
pytest tests/test_telemetry.py

# Run with coverage
pytest tests/ -m "not integration" --cov=agentproxy --cov-report=html
```

### Integration Tests (Require Docker)

Integration tests start the OTEL stack via docker compose and verify end-to-end functionality.

**Prerequisites:**
- Docker and docker compose installed
- `GEMINI_API_KEY` environment variable set

```bash
# Run all integration tests
pytest tests/integration/ -v -s

# Run specific integration test
pytest tests/integration/test_telemetry_e2e.py::TestTelemetryIntegration::test_gemini_api_call_creates_span -v -s
```

### All Tests

```bash
# Run everything (unit + integration)
pytest tests/ -v

# Run with markers
pytest tests/ -m unit           # Only unit tests
pytest tests/ -m integration    # Only integration tests
pytest tests/ -m "not slow"     # Skip slow tests
```

## Test Dependencies

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

Required packages:
- `pytest` - Test framework
- `pytest-cov` (optional) - Coverage reporting
- `pytest-timeout` (optional) - Test timeouts
- `requests` - For integration tests (API calls to Prometheus/Tempo)

## Writing Tests

### Unit Tests

Unit tests should be fast, isolated, and not depend on external services:

```python
def test_my_feature():
    """Test description."""
    # Arrange
    input_data = "test"

    # Act
    result = my_function(input_data)

    # Assert
    assert result == expected_output
```

### Integration Tests

Integration tests verify end-to-end functionality with real services:

```python
@pytest.mark.integration
def test_telemetry_e2e(otel_stack):
    """Test telemetry with real OTEL stack."""
    # Run PA
    # Verify data in Prometheus/Tempo
```

## Continuous Integration

Tests are run automatically on:
- Pull requests
- Pushes to main branch

CI runs:
1. Unit tests (always)
2. Integration tests (if docker available)

## Troubleshooting

### Integration tests failing

**"Docker not available"**
- Install Docker Desktop
- Ensure docker daemon is running: `docker ps`

**"Services not ready"**
- Increase wait time in `otel_stack` fixture
- Check docker compose logs: `cd examples/otel-stack && docker compose logs`

**"GEMINI_API_KEY not set"**
- Export your API key: `export GEMINI_API_KEY=your-key-here`

### Unit tests failing

**"ModuleNotFoundError"**
- Install agentproxy: `pip install -e .`
- Install test dependencies: `pip install -r requirements-test.txt`

**"OTEL packages not installed"**
- Optional for unit tests - tests will skip if not available
- Install: `pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc`

## Test Coverage

Generate coverage report:

```bash
pytest tests/ --cov=agentproxy --cov-report=html
open htmlcov/index.html
```

Target coverage: >80% for core modules
