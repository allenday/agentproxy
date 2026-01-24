"""
Unit tests for OpenTelemetry telemetry module.
Tests conditional imports, initialization, and graceful degradation.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestTelemetryModule:
    """Test telemetry module conditional imports and initialization."""

    def test_telemetry_disabled_by_default(self):
        """Telemetry should be disabled if ENV var not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Re-import to get fresh instance
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()
                assert telemetry.enabled is False
                assert telemetry.tracer is None
                assert telemetry.meter is None

    def test_telemetry_disabled_with_zero(self):
        """Telemetry should be disabled when ENV var is 0."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "0"}):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()
                assert telemetry.enabled is False

    def test_telemetry_enabled_with_env(self):
        """Telemetry should initialize when enabled."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "1"}):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()
                assert telemetry.enabled is True
                assert telemetry.tracer is not None
                assert telemetry.meter is not None

    def test_get_telemetry_singleton(self):
        """get_telemetry() should return singleton instance."""
        from agentproxy.telemetry import get_telemetry

        telemetry1 = get_telemetry()
        telemetry2 = get_telemetry()

        assert telemetry1 is telemetry2

    def test_no_op_telemetry_when_not_available(self):
        """When OTEL packages not available, should return no-op telemetry."""
        from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

        telemetry = get_telemetry()

        # Should always have these attributes
        assert hasattr(telemetry, 'enabled')
        assert hasattr(telemetry, 'tracer')
        assert hasattr(telemetry, 'meter')

        # If OTEL not available, should be no-op
        if not OTEL_AVAILABLE:
            assert telemetry.enabled is False
            assert telemetry.tracer is None
            assert telemetry.meter is None

    def test_instrument_fastapi_no_op_when_disabled(self):
        """FastAPI instrumentation should be no-op when disabled."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "0"}):
            from agentproxy.telemetry import get_telemetry

            telemetry = get_telemetry()

            # Should not raise error even with None app
            telemetry.instrument_fastapi(None)

    def test_custom_endpoint_configuration(self):
        """Should configure exporters with custom endpoint from ENV."""
        with patch.dict(os.environ, {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://custom:4317",
            "OTEL_SERVICE_NAME": "test-service",
            "OTEL_SERVICE_NAMESPACE": "test-ns",
        }):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()
                assert telemetry.enabled is True
                # Telemetry should be initialized with custom config
                # (actual validation would require mocking exporters)

    def test_metric_export_interval_configuration(self):
        """Should configure metric export interval from ENV."""
        with patch.dict(os.environ, {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_METRIC_EXPORT_INTERVAL": "5000",
        }):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()
                assert telemetry.enabled is True

    def test_metric_export_interval_invalid_value(self):
        """Should handle invalid OTEL_METRIC_EXPORT_INTERVAL gracefully."""
        with patch.dict(os.environ, {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_METRIC_EXPORT_INTERVAL": "not-a-number",
        }):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE, reset_telemetry

            if OTEL_AVAILABLE:
                reset_telemetry()
                telemetry = AgentProxyTelemetry()
                # Should still initialize successfully with default value
                assert telemetry.enabled is True
                assert telemetry.meter is not None


class TestBackwardsCompatibility:
    """Test backwards compatibility when OTEL is not installed."""

    def test_pa_works_without_otel(self):
        """PA should work normally with telemetry disabled."""
        with patch.dict(os.environ, {}, clear=True):
            from agentproxy.telemetry import get_telemetry, reset_telemetry

            # Reset singleton to ensure fresh initialization
            reset_telemetry()
            telemetry = get_telemetry()

            # Should have enabled=False
            assert telemetry.enabled is False

            # Should not raise when trying to use telemetry methods
            telemetry.instrument_fastapi(None)


class TestMetricInstruments:
    """Test metric instruments are created correctly."""

    def test_metric_instruments_created_when_enabled(self):
        """All metric instruments should be created when telemetry enabled."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "1"}):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()

                # Check counter instruments exist
                assert hasattr(telemetry, 'tasks_started')
                assert hasattr(telemetry, 'tasks_completed')
                assert hasattr(telemetry, 'claude_iterations')
                assert hasattr(telemetry, 'verifications')
                assert hasattr(telemetry, 'pa_decisions')

                # Check histogram instruments exist
                assert hasattr(telemetry, 'task_duration')
                assert hasattr(telemetry, 'pa_reasoning_duration')
                assert hasattr(telemetry, 'gemini_api_duration')

                # Check gauge instruments exist
                assert hasattr(telemetry, 'active_sessions')

    def test_metrics_not_created_when_disabled(self):
        """Metric instruments should not be created when disabled."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "0"}):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()

                # Metrics should not be initialized
                assert not hasattr(telemetry, 'tasks_started') or telemetry.tasks_started is None
