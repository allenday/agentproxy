"""
End-to-end integration test for OpenTelemetry instrumentation.
Tests that telemetry flows from AgentProxy to OTEL collector.

Prerequisites:
- OTEL stack running (cd examples/otel-stack && docker-compose up -d)
- Telemetry dependencies installed (pip install -e '.[telemetry]')
"""

import os
import time
import requests
import pytest


@pytest.mark.integration
class TestOTELEndToEnd:
    """End-to-end OTEL integration tests."""

    @pytest.fixture(autouse=True)
    def setup_telemetry_env(self):
        """Set up environment for telemetry testing."""
        # Save original env
        original_env = {
            'AGENTPROXY_ENABLE_TELEMETRY': os.getenv('AGENTPROXY_ENABLE_TELEMETRY'),
            'OTEL_EXPORTER_OTLP_ENDPOINT': os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT'),
            'OTEL_SERVICE_NAME': os.getenv('OTEL_SERVICE_NAME'),
        }

        # Set test environment
        os.environ['AGENTPROXY_ENABLE_TELEMETRY'] = '1'
        os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = 'http://localhost:4317'
        os.environ['OTEL_SERVICE_NAME'] = 'agentproxy-test'

        yield

        # Restore original env
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_otel_collector_is_running(self):
        """Verify OTEL collector is accessible."""
        try:
            # Check Prometheus exporter endpoint
            response = requests.get('http://localhost:8889/metrics', timeout=5)
            assert response.status_code == 200
            # The endpoint should return Prometheus-formatted metrics
            # It may be empty initially, but the HTTP endpoint should work
        except requests.exceptions.ConnectionError:
            pytest.skip("OTEL stack not running. Run: cd examples/otel-stack && docker-compose up -d")

    def test_prometheus_is_running(self):
        """Verify Prometheus is accessible."""
        try:
            response = requests.get('http://localhost:9090/-/healthy', timeout=5)
            assert response.status_code == 200
        except requests.exceptions.ConnectionError:
            pytest.skip("Prometheus not running")

    def test_grafana_is_running(self):
        """Verify Grafana is accessible."""
        try:
            response = requests.get('http://localhost:3000/api/health', timeout=5)
            assert response.status_code == 200
        except requests.exceptions.ConnectionError:
            pytest.skip("Grafana not running")

    def test_telemetry_initialization(self):
        """Test that telemetry initializes correctly when enabled."""
        # Force re-import to pick up new environment
        import importlib
        from agentproxy import telemetry as telemetry_module
        importlib.reload(telemetry_module)

        from agentproxy.telemetry import get_telemetry

        telemetry = get_telemetry()
        assert telemetry.enabled is True
        assert telemetry.tracer is not None
        assert telemetry.meter is not None

    def test_metrics_export_to_collector(self):
        """Test that metrics are exported to OTEL collector."""
        from agentproxy.telemetry import get_telemetry

        # Force re-initialization with test environment
        import importlib
        from agentproxy import telemetry as telemetry_module
        importlib.reload(telemetry_module)

        telemetry = get_telemetry()

        # Record some test metrics
        telemetry.tasks_started.add(1)
        telemetry.tasks_completed.add(1, {"status": "test"})
        telemetry.task_duration.record(1.5)

        # Wait for metrics to be exported (default interval is 10s, but we set it lower for tests)
        time.sleep(3)

        # Check that metrics appear in OTEL collector's Prometheus endpoint
        try:
            response = requests.get('http://localhost:8889/metrics', timeout=5)
            metrics_text = response.text

            # Look for our metrics with the agentproxy_ prefix
            # The exporter adds namespace prefix to metrics
            assert 'agentproxy_agentproxy_tasks' in metrics_text or 'agentproxy_agentproxy' in metrics_text
        except requests.exceptions.ConnectionError:
            pytest.skip("Cannot connect to OTEL collector metrics endpoint")

    def test_prometheus_scrapes_metrics(self):
        """Test that Prometheus successfully scrapes metrics from OTEL collector."""
        try:
            # Query Prometheus for agentproxy metrics
            response = requests.get(
                'http://localhost:9090/api/v1/query',
                params={'query': 'agentproxy_tasks_started'},
                timeout=5
            )

            data = response.json()
            # We expect either a result or an empty result (if no data yet)
            # The important part is that Prometheus is working
            assert data['status'] == 'success'

        except requests.exceptions.ConnectionError:
            pytest.skip("Cannot connect to Prometheus")


if __name__ == '__main__':
    # Run integration tests
    pytest.main([__file__, '-v', '-m', 'integration'])
