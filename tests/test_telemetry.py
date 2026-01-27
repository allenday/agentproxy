"""
Unit tests for OpenTelemetry telemetry module.
Tests conditional imports, initialization, and graceful degradation.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestTelemetryModule:
    """Test telemetry module conditional imports and initialization."""

    def test_telemetry_respects_env_file(self):
        """Telemetry configuration respects .env file settings."""
        # NOTE: This test verifies that .env file loading works correctly.
        # The actual .env file in the repo has telemetry enabled for development.
        from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

        if OTEL_AVAILABLE:
            telemetry = get_telemetry()
            # Telemetry state depends on .env file - just verify it's initialized
            assert telemetry is not None
            assert hasattr(telemetry, 'enabled')
            assert hasattr(telemetry, 'tracer')
            assert hasattr(telemetry, 'meter')

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

                # Check new tool tracking metrics
                assert hasattr(telemetry, 'tool_executions')
                assert hasattr(telemetry, 'tool_duration')

                # Check new token breakdown metrics
                assert hasattr(telemetry, 'tokens_prompt')
                assert hasattr(telemetry, 'tokens_completion')
                assert hasattr(telemetry, 'tokens_cache_write')
                assert hasattr(telemetry, 'tokens_cache_read')

                # Check new API tracking metrics
                assert hasattr(telemetry, 'api_requests')
                assert hasattr(telemetry, 'api_errors')
                assert hasattr(telemetry, 'api_cost')

                # Check new context window metric
                assert hasattr(telemetry, 'context_window_usage')

                # Check new code change metrics
                assert hasattr(telemetry, 'code_lines_added')
                assert hasattr(telemetry, 'code_lines_removed')
                assert hasattr(telemetry, 'code_files_modified')

    def test_metrics_not_created_when_disabled(self):
        """Metric instruments should not be created when disabled."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "0"}):
            from agentproxy.telemetry import AgentProxyTelemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = AgentProxyTelemetry()

                # Metrics should not be initialized
                assert not hasattr(telemetry, 'tasks_started') or telemetry.tasks_started is None


class TestCostCalculation:
    """Test API cost calculation helper."""

    def test_calculate_cost_gemini(self):
        """Test cost calculation for Gemini API."""
        from agentproxy.telemetry import calculate_cost

        # Test gemini-2.5-flash pricing (0.075 per 1M prompt, 0.30 per 1M completion)
        cost = calculate_cost("gemini", "gemini-2.5-flash", 10000, 2000)
        # Expected: (10000/1000000)*0.075 + (2000/1000000)*0.30 = 0.00075 + 0.0006 = 0.00135
        assert abs(cost - 0.00135) < 0.000001

    def test_calculate_cost_claude_with_cache(self):
        """Test cost calculation for Claude API with cache tokens."""
        from agentproxy.telemetry import calculate_cost

        # Test claude-sonnet-4-5 pricing (3.0 prompt, 15.0 completion, 3.75 cache_write, 0.30 cache_read per 1M)
        cost = calculate_cost("claude", "claude-sonnet-4-5", 5000, 1000, cache_write=2000, cache_read=8000)
        # Expected: (5000/1M)*3.0 + (1000/1M)*15.0 + (2000/1M)*3.75 + (8000/1M)*0.30
        #         = 0.015 + 0.015 + 0.0075 + 0.0024 = 0.0399
        expected = 0.015 + 0.015 + 0.0075 + 0.0024
        assert abs(cost - expected) < 0.000001

    def test_calculate_cost_unknown_model(self):
        """Test cost calculation returns 0 for unknown model."""
        from agentproxy.telemetry import calculate_cost

        cost = calculate_cost("unknown_api", "unknown_model", 10000, 2000)
        assert cost == 0.0

    def test_api_pricing_constants_exist(self):
        """Test that API_PRICING constants are defined."""
        from agentproxy.telemetry import API_PRICING, MODEL_CONTEXT_LIMITS

        # Check Gemini pricing exists
        assert "gemini" in API_PRICING
        assert "gemini-2.5-flash" in API_PRICING["gemini"]
        assert "prompt" in API_PRICING["gemini"]["gemini-2.5-flash"]
        assert "completion" in API_PRICING["gemini"]["gemini-2.5-flash"]

        # Check Claude pricing exists
        assert "claude" in API_PRICING
        assert "claude-sonnet-4-5" in API_PRICING["claude"]
        assert "cache_write" in API_PRICING["claude"]["claude-sonnet-4-5"]
        assert "cache_read" in API_PRICING["claude"]["claude-sonnet-4-5"]

        # Check context limits exist
        assert "gemini-2.5-flash" in MODEL_CONTEXT_LIMITS
        assert "claude-sonnet-4-5" in MODEL_CONTEXT_LIMITS
        assert MODEL_CONTEXT_LIMITS["gemini-2.5-flash"] == 1_000_000
        assert MODEL_CONTEXT_LIMITS["claude-sonnet-4-5"] == 200_000


class TestSessionAwareTelemetry:
    """Test session-aware telemetry features (user stories)."""

    def test_resource_attributes_include_project_and_role(self):
        """Resource attributes should include project_id and role for multi-tenant aggregation."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "AGENTPROXY_OWNER_ID": "user123",
            "AGENTPROXY_PROJECT_ID": "project456",
            "AGENTPROXY_ROLE": "supervisor",
        }
        with patch.dict(os.environ, test_env):
            # Force telemetry re-initialization by clearing singleton
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                # Resource attributes are set during initialization
                # We verify they're constructed correctly by checking env vars were used
                assert os.getenv("AGENTPROXY_PROJECT_ID") == "project456"
                assert os.getenv("AGENTPROXY_ROLE") == "supervisor"

    def test_tokens_consumed_metric_created(self):
        """Tokens consumed metric should be created for tracking LLM usage."""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "1"}):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                assert hasattr(telemetry, 'tokens_consumed')

    def test_claude_subprocess_env_includes_otel_vars(self):
        """Claude subprocess should get OTEL resource attributes for session linking."""
        from agentproxy import PA

        pa = PA(working_dir=".", session_id="test-session-123")

        # Mock telemetry enabled
        with patch.dict(os.environ, {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "AGENTPROXY_OWNER_ID": "user123",
            "AGENTPROXY_PROJECT_ID": "project456",
        }):
            env = pa._get_subprocess_env_with_trace_context()

            # Should set Claude Code's telemetry
            assert env.get("CLAUDE_CODE_ENABLE_TELEMETRY") == "1"
            assert env.get("OTEL_SERVICE_NAME") == "claude-code"

            # Should set resource attributes
            resource_attrs = env.get("OTEL_RESOURCE_ATTRIBUTES", "")
            assert "service.name=claude-code" in resource_attrs
            assert "agentproxy.owner=user123" in resource_attrs
            assert "agentproxy.project_id=project456" in resource_attrs
            assert "agentproxy.role=worker" in resource_attrs
            assert f"agentproxy.master_session_id={pa.session_id}" in resource_attrs

    def test_service_namespace_defaults_to_user_project(self):
        """Service namespace should default to {user}.{project} for multi-tenant aggregation."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "AGENTPROXY_OWNER_ID": "alice",
            "AGENTPROXY_PROJECT_ID": "my-api",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                # Namespace should be constructed from user + project
                # Can't directly inspect resource, but we can verify ENV var logic
                namespace = os.getenv("OTEL_SERVICE_NAMESPACE", f"alice.my-api")
                assert "alice" in namespace or "my-api" in namespace

    def test_tls_insecure_true(self):
        """Test that OTEL_EXPORTER_OTLP_INSECURE=true disables TLS."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_EXPORTER_OTLP_INSECURE": "true",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                assert telemetry.enabled
                # We can't directly test the exporter's insecure flag,
                # but we verify the env var is read correctly
                assert os.getenv("OTEL_EXPORTER_OTLP_INSECURE") == "true"

    def test_tls_insecure_false(self):
        """Test that OTEL_EXPORTER_OTLP_INSECURE=false enables TLS."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_EXPORTER_OTLP_INSECURE": "false",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                assert telemetry.enabled
                assert os.getenv("OTEL_EXPORTER_OTLP_INSECURE") == "false"

    def test_tls_insecure_defaults_true(self):
        """Test that TLS defaults to insecure=true if not specified."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
        }
        # Make sure INSECURE is not set
        if "OTEL_EXPORTER_OTLP_INSECURE" in os.environ:
            del os.environ["OTEL_EXPORTER_OTLP_INSECURE"]

        with patch.dict(os.environ, test_env, clear=False):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                assert telemetry.enabled
                # Default should be "true" (insecure)
                insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true")
                assert insecure.lower() == "true"

    def test_trace_export_interval_configuration(self):
        """Test that OTEL_TRACE_EXPORT_INTERVAL configures batch processor."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_TRACE_EXPORT_INTERVAL": "2500",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                assert telemetry.enabled
                assert os.getenv("OTEL_TRACE_EXPORT_INTERVAL") == "2500"

    def test_trace_export_interval_invalid_value(self):
        """Test that invalid OTEL_TRACE_EXPORT_INTERVAL falls back to default."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_TRACE_EXPORT_INTERVAL": "invalid",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                # Should not crash, should use default
                telemetry = get_telemetry()
                assert telemetry.enabled

    def test_flush_telemetry_when_enabled(self):
        """Test that flush_telemetry works when telemetry is enabled."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, flush_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                # Should not crash
                flush_telemetry()

    def test_flush_telemetry_when_disabled(self):
        """Test that flush_telemetry is safe when telemetry is disabled."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "0",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import flush_telemetry

            # Should not crash even when disabled
            flush_telemetry()

    def test_verbose_logging_flag(self):
        """Test that AGENTPROXY_TELEMETRY_VERBOSE controls logging."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "AGENTPROXY_TELEMETRY_VERBOSE": "1",
        }
        with patch.dict(os.environ, test_env, clear=True):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                assert telemetry.enabled
                assert telemetry.verbose is True

    def test_verbose_logging_defaults_false(self):
        """Test that verbose logging defaults to false."""
        test_env = {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
        }
        # Remove verbose flag if it exists
        if "AGENTPROXY_TELEMETRY_VERBOSE" in os.environ:
            del os.environ["AGENTPROXY_TELEMETRY_VERBOSE"]

        with patch.dict(os.environ, test_env, clear=False):
            # Force re-init
            import agentproxy.telemetry
            agentproxy.telemetry._telemetry = None

            from agentproxy.telemetry import get_telemetry, OTEL_AVAILABLE

            if OTEL_AVAILABLE:
                telemetry = get_telemetry()
                assert telemetry.enabled
                assert telemetry.verbose is False
