"""
End-to-end integration tests for OpenTelemetry with docker compose stack.

Uses a fibonacci Python package task to exercise PA's full telemetry pipeline:
  - Tool use event processors (Bash, Write, Edit enrichment labels)
  - LOC tracking (code_lines_added, code_files_modified)
  - Task lifecycle metrics (tasks_started, tasks_completed, task_duration)
  - Context window and token metrics

Prerequisites:
  - Docker and docker compose installed
  - GEMINI_API_KEY set (or in examples/otel-stack/.env)
  - OTEL stack running (docker compose up -d in examples/otel-stack)
"""

import os
import shutil
import subprocess
import tempfile
import time

import pytest
import requests
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
OTEL_STACK_DIR = REPO_ROOT / "examples" / "otel-stack"
COMPOSE_FILE = OTEL_STACK_DIR / "docker-compose.yml"

PROMETHEUS_URL = "http://localhost:9090"
GRAFANA_URL = "http://localhost:3000"
JAEGER_URL = "http://localhost:16686"
OTEL_METRICS_URL = "http://localhost:8889/metrics"

# The fibonacci task prompt with explicit, numbered acceptance criteria.
FIB_TASK = (
    "Create a Python package project. "
    "Acceptance criteria -- task is DONE when ALL of these are true: "
    "(1) pyproject.toml exists with package name fibonacci using setuptools. "
    "(2) src/fibonacci/__init__.py exists with fib_iterative(n) and fib_recursive(n). "
    "(3) Both functions return nth Fibonacci number 0-indexed so fib(0)=0 fib(1)=1 fib(10)=55. "
    "(4) Both raise ValueError for negative n. "
    "(5) tests/test_fibonacci.py exists with pytest tests. "
    "(6) Running python -m pytest tests/ -v passes with exit code 0. "
    "Implementation: fib_iterative uses a loop, fib_recursive uses recursion. "
    "Tests cover base cases 0 and 1, known value 10 gives 55, negative input ValueError, "
    "and agreement between both implementations for n in range 21."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def otel_stack():
    """Start OTEL docker compose stack before tests, leave running after."""
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("Docker not available")

    if not COMPOSE_FILE.exists():
        pytest.skip(f"Docker compose file not found: {COMPOSE_FILE}")

    print("\n[Setup] Starting OTEL stack...")
    subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=OTEL_STACK_DIR,
        check=True,
        capture_output=True,
    )

    # Wait for services
    max_wait = 30
    services = {
        "prometheus": f"{PROMETHEUS_URL}/-/ready",
        "grafana": f"{GRAFANA_URL}/api/health",
        "jaeger": f"{JAEGER_URL}/",
    }

    print("[Setup] Waiting for services to be ready...")
    start = time.time()
    ready = {name: False for name in services}

    while time.time() - start < max_wait:
        for name, url in services.items():
            if ready[name]:
                continue
            try:
                resp = requests.get(url, timeout=1)
                if resp.status_code in (200, 204):
                    ready[name] = True
                    print(f"[Setup] {name} ready")
            except requests.RequestException:
                pass
        if all(ready.values()):
            break
        time.sleep(1)

    if not all(ready.values()):
        not_ready = [n for n, ok in ready.items() if not ok]
        print(f"[Setup] Warning: Services not ready: {not_ready}")

    time.sleep(3)
    print("[Setup] OTEL stack ready")
    yield

    # Leave stack running for dashboard viewing
    print("\n[Teardown] Leaving OTEL stack running for dashboard viewing")


@pytest.fixture(scope="module")
def fib_workdir():
    """Create a temporary directory for the fibonacci project."""
    d = tempfile.mkdtemp(prefix="pa-fib-test-")
    yield d
    # Clean up after all module tests run
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="module")
def telemetry_env():
    """Build environment dict with telemetry enabled.

    Loads GEMINI_API_KEY from the otel-stack .env file if not already
    in the environment, so that the test can run without the user
    having to export credentials separately.
    """
    env = os.environ.copy()

    # Load .env from otel-stack for GEMINI_API_KEY if missing
    dotenv_path = OTEL_STACK_DIR / ".env"
    if "GEMINI_API_KEY" not in env and dotenv_path.exists():
        for line in dotenv_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "GEMINI_API_KEY":
                env["GEMINI_API_KEY"] = v.strip()

    env.update({
        "AGENTPROXY_ENABLE_TELEMETRY": "1",
        "AGENTPROXY_TELEMETRY_VERBOSE": "1",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
        "OTEL_EXPORTER_OTLP_INSECURE": "true",
        "OTEL_TRACE_EXPORT_INTERVAL": "500",
        "OTEL_METRIC_EXPORT_INTERVAL": "1000",
        "AGENTPROXY_OWNER_ID": "test-user",
        "AGENTPROXY_PROJECT_ID": "test-fib",
        "OTEL_SERVICE_NAME": "agentproxy-test",
    })
    return env


@pytest.fixture(scope="module")
def pa_result(otel_stack, fib_workdir, telemetry_env):
    """Run PA with the fibonacci task and return the subprocess result.

    This fixture is module-scoped so the (expensive) PA invocation runs
    once and all test methods share the same result + metrics.
    """
    if not telemetry_env.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set and not in examples/otel-stack/.env")

    print(f"\n[PA] Running fibonacci task in {fib_workdir} ...")
    result = subprocess.run(
        ["pa", "-d", fib_workdir, "--display", "simple", FIB_TASK],
        env=telemetry_env,
        capture_output=True,
        text=True,
        timeout=600,
    )

    print("[PA] STDOUT (last 40 lines):")
    for line in result.stdout.splitlines()[-40:]:
        print(f"  {line}")
    if result.stderr:
        print("[PA] STDERR (last 20 lines):")
        for line in result.stderr.splitlines()[-20:]:
            print(f"  {line}")

    # Wait for metric export + Prometheus scrape (15s scrape interval + buffer)
    time.sleep(20)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prom_query(expr: str) -> dict:
    """Execute an instant PromQL query and return the JSON response."""
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": expr},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def prom_value(expr: str) -> float | None:
    """Return the scalar value of a single-result PromQL query, or None."""
    data = prom_query(expr)
    results = data.get("data", {}).get("result", [])
    if results:
        return float(results[0]["value"][1])
    return None


def prom_metric_names() -> list[str]:
    """Return all metric names known to Prometheus."""
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/label/__name__/values",
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


# ---------------------------------------------------------------------------
# Tests: Infrastructure
# ---------------------------------------------------------------------------

class TestOTELInfrastructure:
    """Verify the OTEL stack is running and healthy."""

    def test_services_running(self, otel_stack):
        """All four core services respond to health checks."""
        assert requests.get(f"{PROMETHEUS_URL}/-/ready", timeout=2).status_code == 200
        assert requests.get(f"{GRAFANA_URL}/api/health", timeout=2).status_code == 200
        assert requests.get(f"{JAEGER_URL}/", timeout=2).status_code == 200
        assert requests.get(OTEL_METRICS_URL, timeout=2).status_code == 200

    def test_prometheus_scrapes_otel_collector(self, otel_stack):
        """Prometheus has an active, healthy otel-collector target."""
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/targets", timeout=5)
        data = resp.json()
        targets = data["data"]["activeTargets"]
        otel_targets = [
            t for t in targets
            if "otel-collector" in t.get("labels", {}).get("job", "")
        ]
        assert otel_targets, "OTEL collector target not found in Prometheus"
        for t in otel_targets:
            assert t["health"] == "up", f"OTEL collector target unhealthy: {t}"


# ---------------------------------------------------------------------------
# Tests: Fibonacci Task — PA Lifecycle
# ---------------------------------------------------------------------------

class TestFibonacciTask:
    """Run the fibonacci project task and verify telemetry end-to-end."""

    def test_pa_exits_cleanly(self, pa_result):
        """PA process exits with code 0."""
        assert pa_result.returncode == 0, (
            f"PA exited with code {pa_result.returncode}.\n"
            f"STDERR: {pa_result.stderr[-500:]}"
        )

    def test_task_marked_done(self, pa_result):
        """PA output contains a completion marker."""
        output = pa_result.stdout + pa_result.stderr
        markers = ["TASK COMPLETE", "Task completed", "tasks_completed", "DONE"]
        assert any(m in output for m in markers), (
            "No completion marker found in PA output"
        )

    def test_telemetry_enabled(self, pa_result):
        """Telemetry was initialised during the run."""
        output = pa_result.stdout + pa_result.stderr
        assert "Telemetry ENABLED" in output or "Telemetry initialization complete" in output

    # ------------------------------------------------------------------
    # Project artefacts
    # ------------------------------------------------------------------

    def test_fibonacci_files_created(self, fib_workdir):
        """The fibonacci package has the expected file layout."""
        root = Path(fib_workdir)
        assert (root / "pyproject.toml").exists()
        assert (root / "src" / "fibonacci" / "__init__.py").exists()
        assert (root / "tests" / "test_fibonacci.py").exists()

    def test_fibonacci_tests_pass(self, fib_workdir):
        """pytest passes inside the generated project."""
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-v"],
            cwd=fib_workdir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"pytest failed:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Tests: Prometheus Metrics
# ---------------------------------------------------------------------------

class TestPrometheusMetrics:
    """Verify agentproxy metrics were exported to Prometheus."""

    def test_core_metrics_exist(self, pa_result, otel_stack):
        """All core agentproxy metric names are registered."""
        names = prom_metric_names()
        expected = [
            "agentproxy_tasks_started_total",
            "agentproxy_tasks_completed_total",
            "agentproxy_claude_iterations_total",
            "agentproxy_tokens_consumed_total",
            "agentproxy_sessions_active",
        ]
        for name in expected:
            assert name in names, (
                f"Metric {name} not in Prometheus. "
                f"Available agentproxy_* metrics: "
                f"{[m for m in names if m.startswith('agentproxy_')]}"
            )

    def test_enrichment_metrics_exist(self, pa_result, otel_stack):
        """Tool-enrichment metric names are registered."""
        names = prom_metric_names()
        enrichment = [
            "agentproxy_tools_executions_total",
            "agentproxy_code_lines_added_total",
            "agentproxy_code_files_modified_total",
        ]
        for name in enrichment:
            assert name in names, (
                f"Enrichment metric {name} not in Prometheus. "
                f"Available: {[m for m in names if 'tool' in m or 'code' in m]}"
            )

    def test_tasks_completed_positive(self, pa_result, otel_stack):
        """At least one task was completed."""
        val = prom_value("agentproxy_tasks_completed_total")
        assert val is not None and val >= 1, (
            f"Expected tasks_completed >= 1, got {val}"
        )

    def test_tool_executions_recorded(self, pa_result, otel_stack):
        """Tool executions counter is non-zero (fibonacci needs Bash+Write)."""
        val = prom_value("agentproxy_tools_executions_total")
        assert val is not None and val > 0, (
            f"Expected tool_executions > 0, got {val}"
        )

    def test_tool_enrichment_labels(self, pa_result, otel_stack):
        """Tool execution series carry enrichment labels from event processors.

        The fibonacci task uses at least Bash and Write tools, so we should
        see series with command_category or file_extension labels.
        """
        data = prom_query(
            '{__name__="agentproxy_tools_executions_total"}'
        )
        results = data.get("data", {}).get("result", [])
        assert results, "No tool_executions series found"

        # Collect all label keys across series
        all_keys = set()
        for r in results:
            all_keys.update(r["metric"].keys())

        # We expect at least one enrichment label to be present
        enrichment_keys = {
            "command_category", "subcommand",
            "file_extension", "operation",
        }
        found = all_keys & enrichment_keys
        assert found, (
            f"No enrichment labels found on tool_executions series. "
            f"Labels present: {all_keys}"
        )

    def test_lines_added_positive(self, pa_result, otel_stack):
        """Lines-of-code added counter is positive (fibonacci has >50 LOC)."""
        val = prom_value("agentproxy_code_lines_added_total")
        assert val is not None and val > 0, (
            f"Expected code_lines_added > 0, got {val}"
        )

    def test_files_modified_positive(self, pa_result, otel_stack):
        """Files modified counter is positive (at least pyproject + init + test)."""
        val = prom_value("agentproxy_code_files_modified_total")
        assert val is not None and val >= 3, (
            f"Expected code_files_modified >= 3, got {val}"
        )

    def test_tokens_consumed(self, pa_result, otel_stack):
        """Token consumption is recorded (Gemini calls happened)."""
        val = prom_value("agentproxy_tokens_consumed_total")
        assert val is not None and val > 0, (
            f"Expected tokens_consumed > 0, got {val}"
        )


# ---------------------------------------------------------------------------
# Tests: Metric Schema & Labels
# ---------------------------------------------------------------------------

class TestMetricSchema:
    """Verify agentproxy metrics have correct structure."""

    def test_histogram_metrics_exist(self, pa_result, otel_stack):
        """Histogram bucket metrics are registered."""
        names = prom_metric_names()
        histograms = [
            "agentproxy_context_window_usage_percent_bucket",
            "agentproxy_tools_duration_seconds_bucket",
        ]
        for name in histograms:
            assert name in names, f"Histogram {name} not found"

    def test_cost_and_api_metrics_exist(self, pa_result, otel_stack):
        """Cost and API metrics are registered."""
        names = prom_metric_names()
        expected = [
            "agentproxy_api_requests_total",
            "agentproxy_api_errors_total",
            "agentproxy_api_cost_usd_total",
            "agentproxy_tokens_prompt_total",
            "agentproxy_tokens_completion_total",
        ]
        for name in expected:
            assert name in names, f"Metric {name} not found"

    def test_service_labels(self, pa_result, otel_stack):
        """Metrics carry expected service-level labels."""
        data = prom_query("agentproxy_tasks_completed_total")
        results = data.get("data", {}).get("result", [])
        if results:
            labels = results[0]["metric"]
            # OTEL collector adds these via resource attributes
            assert "job" in labels or "exported_job" in labels or "service" in labels, (
                f"Missing service labels. Got: {labels}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
