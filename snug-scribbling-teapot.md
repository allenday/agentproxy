# Implementation Plan: OTEL Telemetry + Plugin Architecture for agentproxy

## Executive Summary

**Goal:** Add OpenTelemetry instrumentation and plugin architecture to agentproxy OSS

**Context:**
- Upstream feedback: "Absolutely. Appreciated! Make sure 1, it's backwards compatible of the older simple mode. 2, updated readme so people know how to easily get start"
- Existing: claude-code-otel.sh works for Claude Code CLI
- Gap: No telemetry from agentproxy PA operations (reasoning, task management, verification)

**Phases:**
- **Phase 1:** OTEL Telemetry (traces, metrics, logs)
- **Phase 2:** Plugin Architecture (extensibility foundation)

**Non-Goals:**
- Fleet-specific features (hooks, coordinator, docker) - Phase 3-5, separate from upstream
- Prometheus/Loki direct integration - use OTEL collector as bridge

---

# Phase 0: Package Structure Reorganization

## Overview

Reorganize agentproxy as a proper Python package with pyproject.toml to enable:
- Optional dependencies for OTEL, plugins, etc.
- Proper CLI entry points (`pa` command)
- Modern Python packaging (PEP 621, PEP 660)
- Easier installation and distribution

**Current Structure:**
```
agentproxy/
  ├── pa.py
  ├── cli.py
  ├── server.py
  ├── requirements.txt
  └── ... (other modules)
```

**Target Structure:**
```
agentproxy/
  ├── pyproject.toml          # NEW: Modern package config
  ├── setup.py                # Optional: for editable installs
  ├── agentproxy/
  │   ├── __init__.py
  │   ├── __main__.py         # CLI entry point
  │   ├── pa.py
  │   ├── pa_agent.py
  │   ├── cli.py
  │   ├── server.py
  │   └── ... (other modules)
  └── tests/
```

---

## 0.1 Create pyproject.toml

**New file: `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "agentproxy"
version = "0.2.0"
description = "AI supervisor layer for orchestrating coding agents"
readme = "README.md"
requires-python = ">=3.9"
license = {text = "MIT"}
authors = [
    {name = "agentproxy contributors"}
]
keywords = ["ai", "agent", "supervisor", "claude", "llm", "devops"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

# Core dependencies (always installed)
dependencies = [
    "python-dotenv>=1.0.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
# Server dependencies
server = [
    "fastapi>=0.104.0",
    "uvicorn>=0.24.0",
]

# Telemetry dependencies (OTEL)
telemetry = [
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
    "opentelemetry-exporter-otlp>=1.20.0",
    "opentelemetry-instrumentation-fastapi>=0.41b0",
]

# Plugin system dependencies (future)
plugins = [
    # No extra deps initially, may add later
]

# Development dependencies
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "flake8>=6.0.0",
    "mypy>=1.0.0",
]

# All optional dependencies
all = [
    "agentproxy[server,telemetry,plugins,dev]",
]

[project.scripts]
pa = "agentproxy.cli:main"
pa-server = "agentproxy.server:main"

[project.urls]
Homepage = "https://github.com/agentproxy/agentproxy"
Repository = "https://github.com/agentproxy/agentproxy"
Issues = "https://github.com/agentproxy/agentproxy/issues"

[tool.setuptools.packages.find]
where = ["."]
include = ["agentproxy*"]
exclude = ["tests*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"

[tool.black]
line-length = 100
target-version = ["py39"]

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false
```

**Benefits:**
- ✅ Optional OTEL deps: `pip install agentproxy[telemetry]`
- ✅ CLI auto-installed: `pa` command in $PATH
- ✅ Server command: `pa-server` for API mode
- ✅ Modern, maintainable package structure
- ✅ Easier for upstream to accept (follows Python standards)

---

## 0.2 Entry Points

### Update `agentproxy/__main__.py`
```python
"""
Entry point for 'python -m agentproxy' and 'pa' command.
"""
from agentproxy.cli import main

if __name__ == "__main__":
    main()
```

### Update `agentproxy/cli.py`
```python
def main():
    """CLI entry point"""
    # ... existing CLI logic ...
    pass

if __name__ == "__main__":
    main()
```

### Update `agentproxy/server.py`
```python
def main():
    """Server entry point"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
```

---

## 0.3 Installation Methods

### Editable Install (Development)
```bash
# Basic install
pip install -e .

# With OTEL telemetry
pip install -e '.[telemetry]'

# With server
pip install -e '.[server]'

# With everything
pip install -e '.[all]'

# Now `pa` command is in PATH
pa "Write a hello world script"
```

### User Install
```bash
# From PyPI (when published)
pip install agentproxy

# With telemetry support
pip install agentproxy[telemetry]

# With all features
pip install agentproxy[all]
```

---

## 0.4 Dependency Management

### Make OTEL imports conditional

**In `agentproxy/telemetry.py`:**
```python
"""OpenTelemetry instrumentation (optional dependency)"""

try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    # ... other OTEL imports
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    # Provide stub classes/functions
    class _NoOpTelemetry:
        enabled = False
        tracer = None
        meter = None

    def get_telemetry():
        return _NoOpTelemetry()


if OTEL_AVAILABLE:
    class AgentProxyTelemetry:
        # ... real implementation ...
        pass

    _telemetry = None
    def get_telemetry():
        global _telemetry
        if _telemetry is None:
            _telemetry = AgentProxyTelemetry()
        return _telemetry
```

**This ensures:**
- No ImportError if OTEL not installed
- Telemetry gracefully disabled if deps missing
- Users can choose: basic install vs full install

---

## 0.5 README Updates

Add installation section:

````markdown
## Installation

### Basic Installation
```bash
pip install agentproxy
```

### With OpenTelemetry Support
```bash
pip install agentproxy[telemetry]
```

### With Server API
```bash
pip install agentproxy[server]
```

### Development Install
```bash
git clone https://github.com/agentproxy/agentproxy
cd agentproxy
pip install -e '.[all]'
```

## Usage

### CLI
```bash
# After installation, use the `pa` command
pa "Create a REST API with FastAPI"

# Or use python -m
python -m agentproxy "Create a REST API"
```

### Server
```bash
# Start API server
pa-server

# Or
python -m agentproxy.server
```
````

---

## 0.6 Migration Notes

**Changes for upstream PR:**
1. Keep `requirements.txt` for backwards compatibility
2. Add `pyproject.toml` as primary package config
3. Update README with new installation methods
4. Entry points (`pa` command) work after install
5. OTEL dependencies optional, no breaking changes

**For users:**
- Old way still works: `python cli.py` or `python server.py`
- New way preferred: `pa` command after install
- Optional deps reduce installation size

---

# Phase 1: OpenTelemetry Telemetry

## Overview

Add OTEL instrumentation to agentproxy to provide visibility into:
- PA reasoning loop iterations
- Task lifecycle (start, completion, duration)
- Function execution (verify, test, guide)
- Gemini API calls
- File modifications
- Errors and decisions

**Design Principles:**
1. **Backwards compatible:** Opt-in via environment variables, zero impact if disabled
2. **Follows existing pattern:** Extends claude-code-otel.sh approach
3. **Non-invasive:** No behavioral changes, pure observability
4. **Standard OTEL:** Uses semantic conventions where applicable
5. **Optional dependencies:** OTEL deps only needed if using telemetry

---

## 1.1 Dependencies (Already in pyproject.toml)

**In `pyproject.toml` (from Phase 0):**
```toml
[project.optional-dependencies]
telemetry = [
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
    "opentelemetry-exporter-otlp>=1.20.0",
    "opentelemetry-instrumentation-fastapi>=0.41b0",
]
```

**Installation:**
```bash
# Install with telemetry support
pip install -e '.[telemetry]'
```

**Why these packages:**
- `opentelemetry-api` - Core API for creating spans, metrics, logs
- `opentelemetry-sdk` - SDK implementation for processing telemetry
- `opentelemetry-exporter-otlp` - OTLP exporter for gRPC/HTTP
- `opentelemetry-instrumentation-fastapi` - Auto-instrument FastAPI server

---

## 1.2 Configuration (Environment Variables)

**Follow claude-code-otel.sh pattern:**

### Primary Control
```bash
# Enable/disable telemetry (default: disabled for backwards compatibility)
AGENTPROXY_ENABLE_TELEMETRY=1  # or 0

# Service identification
OTEL_SERVICE_NAME=agentproxy  # default
OTEL_SERVICE_NAMESPACE=dev    # or prod, staging
```

### OTLP Exporter Configuration
```bash
# Protocol: grpc or http/protobuf
OTEL_EXPORTER_OTLP_PROTOCOL=grpc  # default

# Endpoint (all signals)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Per-signal endpoints (optional overrides)
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4317

# Export intervals
OTEL_METRIC_EXPORT_INTERVAL=10000  # milliseconds (10s default)
OTEL_LOGS_EXPORT_INTERVAL=5000     # milliseconds (5s default)
```

### Resource Attributes
```bash
# Auto-populated
OTEL_RESOURCE_ATTRIBUTES=service.name=agentproxy,service.namespace=dev,host.name=${HOSTNAME}

# Can add custom attributes
AGENTPROXY_OWNER_ID=alice  # Optional: owner/user identification
```

**Backwards Compatibility:**
- If `AGENTPROXY_ENABLE_TELEMETRY` is unset or 0, telemetry is completely disabled
- No OTEL code runs, zero overhead
- All existing functionality works unchanged

---

## 1.3 Code Architecture

### New File: `agentproxy/telemetry.py`

```python
"""
OpenTelemetry instrumentation for agentproxy.
Provides traces, metrics, and logs for PA operations.
"""

import os
from typing import Optional
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import socket


class AgentProxyTelemetry:
    """Manages OTEL instrumentation for agentproxy"""

    def __init__(self):
        self.enabled = os.getenv("AGENTPROXY_ENABLE_TELEMETRY", "0") == "1"
        self.tracer: Optional[trace.Tracer] = None
        self.meter: Optional[metrics.Meter] = None

        if self.enabled:
            self._init_telemetry()

    def _init_telemetry(self):
        """Initialize OTEL providers and exporters"""
        # Build resource attributes
        resource = Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "agentproxy"),
            "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "default"),
            "host.name": os.getenv("HOSTNAME", socket.gethostname()),
            "agentproxy.owner": os.getenv("AGENTPROXY_OWNER_ID", os.getenv("USER", "unknown")),
        })

        # Traces
        trace_provider = TracerProvider(resource=resource)
        otlp_trace_exporter = OTLPSpanExporter(
            endpoint=os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or
                     os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
        )
        trace_provider.add_span_processor(BatchSpanProcessor(otlp_trace_exporter))
        trace.set_tracer_provider(trace_provider)
        self.tracer = trace.get_tracer("agentproxy", version="0.2.0")

        # Metrics
        otlp_metric_exporter = OTLPMetricExporter(
            endpoint=os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") or
                     os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
        )
        metric_reader = PeriodicExportingMetricReader(
            otlp_metric_exporter,
            export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "10000")),
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
        self.meter = metrics.get_meter("agentproxy", version="0.2.0")

        # Initialize metrics
        self._init_metrics()

    def _init_metrics(self):
        """Create metric instruments"""
        # Counters
        self.tasks_started = self.meter.create_counter(
            "agentproxy.tasks.started",
            description="Number of tasks started",
            unit="1",
        )
        self.tasks_completed = self.meter.create_counter(
            "agentproxy.tasks.completed",
            description="Number of tasks completed",
            unit="1",
        )
        self.claude_iterations = self.meter.create_counter(
            "agentproxy.claude.iterations",
            description="Number of Claude invocations",
            unit="1",
        )
        self.verifications = self.meter.create_counter(
            "agentproxy.verifications",
            description="Number of verifications run",
            unit="1",
        )
        self.pa_decisions = self.meter.create_counter(
            "agentproxy.pa.decisions",
            description="PA decisions made",
            unit="1",
        )

        # Histograms
        self.task_duration = self.meter.create_histogram(
            "agentproxy.task.duration",
            description="Task duration",
            unit="s",
        )
        self.pa_reasoning_duration = self.meter.create_histogram(
            "agentproxy.pa.reasoning.duration",
            description="PA reasoning cycle duration",
            unit="s",
        )
        self.gemini_api_duration = self.meter.create_histogram(
            "agentproxy.gemini.api.duration",
            description="Gemini API call duration",
            unit="s",
        )

        # Gauges
        self.active_sessions = self.meter.create_up_down_counter(
            "agentproxy.sessions.active",
            description="Number of active sessions",
            unit="1",
        )

    def instrument_fastapi(self, app):
        """Auto-instrument FastAPI if telemetry enabled"""
        if self.enabled:
            FastAPIInstrumentor.instrument_app(app)


# Global singleton
_telemetry = None

def get_telemetry() -> AgentProxyTelemetry:
    """Get or create global telemetry instance"""
    global _telemetry
    if _telemetry is None:
        _telemetry = AgentProxyTelemetry()
    return _telemetry
```

---

## 1.4 Instrumentation Points

### File: `agentproxy/pa.py`

**Add at top:**
```python
from .telemetry import get_telemetry
```

**Instrument `run()` method:**
```python
def run(self, prompt: str, working_dir: str = "./sandbox", timeout: int = None) -> SessionInfo:
    """Run PA with optional OTEL instrumentation"""
    telemetry = get_telemetry()

    # Start trace span if enabled
    if telemetry.enabled:
        with telemetry.tracer.start_as_current_span(
            "pa.run",
            attributes={
                "pa.task.description": prompt[:100],  # Truncate for readability
                "pa.working_dir": working_dir,
            }
        ) as span:
            telemetry.tasks_started.add(1)
            telemetry.active_sessions.add(1)

            try:
                result = self._run_internal(prompt, working_dir, timeout)

                # Record completion
                telemetry.tasks_completed.add(1, {"status": result.status})
                telemetry.task_duration.record(result.duration)
                span.set_attribute("pa.status", result.status)
                span.set_attribute("pa.iterations", result.iteration_count)

                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise
            finally:
                telemetry.active_sessions.add(-1)
    else:
        # No telemetry, run directly (backwards compatible)
        return self._run_internal(prompt, working_dir, timeout)

def _run_internal(self, prompt: str, working_dir: str, timeout: int) -> SessionInfo:
    """Original run logic (extracted for instrumentation)"""
    # ... existing run() code moved here ...
```

---

### File: `agentproxy/pa_agent.py`

**Instrument reasoning loop:**
```python
def reasoning_loop(self, claude_output: str, file_changes: List[str]) -> PAReasoning:
    """PA reasoning with OTEL instrumentation"""
    telemetry = get_telemetry()

    if telemetry.enabled:
        with telemetry.tracer.start_as_current_span(
            "pa.reasoning_loop",
            attributes={
                "pa.file_changes": len(file_changes),
                "pa.output_length": len(claude_output),
            }
        ) as span:
            start_time = time.time()

            try:
                # Call Gemini for reasoning
                reasoning = self._call_gemini_reasoning(claude_output, file_changes)

                # Record metrics
                duration = time.time() - start_time
                telemetry.pa_reasoning_duration.record(duration)
                telemetry.pa_decisions.add(1, {"decision": reasoning.decision})

                # Add span attributes
                span.set_attribute("pa.decision", reasoning.decision)
                span.set_attribute("pa.function", reasoning.function_to_call.value if reasoning.function_to_call else "none")

                return reasoning
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR))
                raise
    else:
        return self._call_gemini_reasoning(claude_output, file_changes)
```

**Instrument Gemini API calls:**
```python
# In gemini_client.py

def complete(self, prompt: str, images: List[str] = None) -> str:
    """Gemini API call with OTEL instrumentation"""
    telemetry = get_telemetry()

    if telemetry.enabled:
        with telemetry.tracer.start_as_current_span(
            "gemini.api.complete",
            attributes={
                "gemini.model": "gemini-2.5-flash",
                "gemini.has_images": bool(images),
            }
        ) as span:
            start_time = time.time()

            try:
                response = self._do_api_call(prompt, images)

                duration = time.time() - start_time
                telemetry.gemini_api_duration.record(duration)
                span.set_attribute("gemini.response_length", len(response))

                return response
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR))
                raise
    else:
        return self._do_api_call(prompt, images)
```

---

### File: `agentproxy/function_executor.py`

**Instrument verification functions:**
```python
def execute_function(self, function_name: FunctionName, args: Dict) -> FunctionResult:
    """Execute function with OTEL instrumentation"""
    telemetry = get_telemetry()

    if telemetry.enabled:
        with telemetry.tracer.start_as_current_span(
            f"pa.function.{function_name.value}",
            attributes={"pa.function.name": function_name.value}
        ) as span:
            result = self._execute_internal(function_name, args)

            # Record verification metrics
            if function_name in [FunctionName.VERIFY_CODE, FunctionName.RUN_TESTS]:
                telemetry.verifications.add(1, {
                    "type": function_name.value,
                    "result": "pass" if result.success else "fail"
                })

            span.set_attribute("pa.function.success", result.success)
            return result
    else:
        return self._execute_internal(function_name, args)
```

---

### File: `agentproxy/process_manager.py`

**Instrument Claude subprocess invocations:**
```python
def stream_output(self, prompt: str) -> Iterator[OutputEvent]:
    """Stream Claude output with OTEL instrumentation"""
    telemetry = get_telemetry()

    if telemetry.enabled:
        with telemetry.tracer.start_as_current_span(
            "claude.subprocess",
            attributes={
                "claude.prompt_length": len(prompt),
            }
        ) as span:
            telemetry.claude_iterations.add(1)

            # Propagate trace context to Claude subprocess via environment
            env = self._get_subprocess_env_with_trace_context()

            for event in self._stream_internal(prompt, env):
                yield event

            span.set_attribute("claude.completed", True)
    else:
        for event in self._stream_internal(prompt, os.environ.copy()):
            yield event

def _get_subprocess_env_with_trace_context(self) -> Dict[str, str]:
    """Get environment with trace context propagated"""
    from opentelemetry.propagate import inject

    env = os.environ.copy()

    # Inject trace context into environment for Claude subprocess
    # This allows Claude's OTEL spans to link to PA's spans
    carrier = {}
    inject(carrier)

    for key, value in carrier.items():
        env[key] = value

    return env
```

---

### File: `agentproxy/server.py`

**Auto-instrument FastAPI:**
```python
from .telemetry import get_telemetry

app = FastAPI()

# Auto-instrument if telemetry enabled
telemetry = get_telemetry()
telemetry.instrument_fastapi(app)
```

---

## 1.5 Verification Steps

### Test 1: Telemetry Disabled (Backwards Compatibility)
```bash
# Unset telemetry ENV vars
unset AGENTPROXY_ENABLE_TELEMETRY

# Run agentproxy normally
python -m agentproxy "Write a hello world script"

# Expected: Works exactly as before, no OTEL code runs
```

### Test 2: Telemetry Enabled with Local OTEL Collector
```bash
# Start OTEL collector
docker run -d --name otel-collector \
  -p 4317:4317 \
  -p 4318:4318 \
  -v $(pwd)/otel-collector-config.yaml:/etc/otel-collector-config.yaml \
  otel/opentelemetry-collector:latest \
  --config=/etc/otel-collector-config.yaml

# Enable telemetry
export AGENTPROXY_ENABLE_TELEMETRY=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=agentproxy
export OTEL_SERVICE_NAMESPACE=dev

# Run agentproxy
python -m agentproxy "Write a hello world script"

# Expected: Traces and metrics exported to collector
```

**Example `otel-collector-config.yaml`:**
```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  logging:
    loglevel: debug
  prometheus:
    endpoint: "0.0.0.0:8889"

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [logging]
    metrics:
      receivers: [otlp]
      exporters: [logging, prometheus]
```

### Test 3: Verify Trace Hierarchy
```bash
# Query traces from backend (e.g., Jaeger, Tempo)
# Should see hierarchy:
# pa.run (root span)
#   ├─ pa.reasoning_loop
#   │   └─ gemini.api.complete
#   ├─ claude.subprocess
#   ├─ pa.reasoning_loop
#   │   └─ gemini.api.complete
#   ├─ pa.function.verify_code
#   └─ pa.function.mark_done
```

### Test 4: Verify Metrics
```bash
# Query Prometheus (if collector exports to Prometheus)
curl http://localhost:8889/metrics | grep agentproxy

# Expected metrics:
# agentproxy_tasks_started_total{} 1
# agentproxy_tasks_completed_total{status="completed"} 1
# agentproxy_task_duration_seconds_bucket{le="10"} 1
# agentproxy_pa_decisions_total{decision="CONTINUE"} 2
# agentproxy_pa_decisions_total{decision="VERIFY"} 1
# agentproxy_verifications_total{type="verify_code",result="pass"} 1
```

### Test 5: Verify Trace Context Propagation to Claude
```bash
# With both agentproxy and Claude Code instrumented
# Traces should link: PA span -> Claude Code span
# Check trace ID matches between agentproxy and Claude Code spans
```

---

## 1.6 Documentation Updates

### README.md Changes

**Add section: "Observability with OpenTelemetry"**

````markdown
## Observability with OpenTelemetry

agentproxy supports OpenTelemetry for traces, metrics, and logs. This is **opt-in** and disabled by default.

### Quick Start

1. **Run an OTEL collector** (or use existing one):
   ```bash
   docker run -d -p 4317:4317 otel/opentelemetry-collector:latest
   ```

2. **Enable telemetry**:
   ```bash
   export AGENTPROXY_ENABLE_TELEMETRY=1
   export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
   ```

3. **Run agentproxy normally**:
   ```bash
   python -m agentproxy "Your task here"
   ```

4. **View telemetry** in your backend (Grafana, Jaeger, etc.)

### Configuration

All configuration is via environment variables (follows [OTEL spec](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)):

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTPROXY_ENABLE_TELEMETRY` | `0` | Set to `1` to enable telemetry |
| `OTEL_SERVICE_NAME` | `agentproxy` | Service name in traces |
| `OTEL_SERVICE_NAMESPACE` | `default` | Service namespace (e.g., `dev`, `prod`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP collector endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | Protocol: `grpc` or `http/protobuf` |
| `OTEL_METRIC_EXPORT_INTERVAL` | `10000` | Metric export interval (ms) |
| `AGENTPROXY_OWNER_ID` | `$USER` | Owner/user ID for multi-tenant tracking |

### What's Instrumented

**Traces:**
- Task lifecycle (`pa.run`)
- PA reasoning loops (`pa.reasoning_loop`)
- Gemini API calls (`gemini.api.complete`)
- Claude subprocess invocations (`claude.subprocess`)
- Function executions (`pa.function.*`)

**Metrics:**
- `agentproxy.tasks.started` - Tasks started (counter)
- `agentproxy.tasks.completed` - Tasks completed (counter with status label)
- `agentproxy.task.duration` - Task duration (histogram)
- `agentproxy.pa.decisions` - PA decisions (counter with decision type)
- `agentproxy.pa.reasoning.duration` - PA reasoning duration (histogram)
- `agentproxy.verifications` - Verifications run (counter with type and result)
- `agentproxy.sessions.active` - Active sessions (gauge)

### Example: Full Stack with Grafana

See `examples/otel-stack/` for docker-compose setup with:
- OTEL Collector
- Tempo (traces)
- Prometheus (metrics)
- Grafana (visualization)

```bash
cd examples/otel-stack
docker-compose up -d
```

Dashboard available at http://localhost:3000

### Linking with Claude Code Telemetry

If you use `claude-code-otel.sh` to instrument Claude Code, traces will automatically link:

```bash
# agentproxy creates parent spans
# Claude Code creates child spans
# Full distributed trace across both!
```

### Backwards Compatibility

Telemetry is **completely opt-in**:
- If `AGENTPROXY_ENABLE_TELEMETRY` is not set or `0`, zero OTEL code runs
- No performance impact when disabled
- No behavioral changes

````

---

### New File: `examples/otel-stack/docker-compose.yml`

```yaml
version: "3.8"

services:
  # OTEL Collector
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    command: ["--config=/etc/otel-collector-config.yaml"]
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml
    ports:
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
      - "8889:8889"   # Prometheus exporter

  # Tempo (traces)
  tempo:
    image: grafana/tempo:latest
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ./tempo.yaml:/etc/tempo.yaml
      - tempo-data:/tmp/tempo
    ports:
      - "3200:3200"   # Tempo HTTP
      - "4317"        # OTLP gRPC (internal)

  # Prometheus (metrics)
  prometheus:
    image: prom/prometheus:latest
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"

  # Grafana (visualization)
  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Admin
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - ./grafana/dashboards:/var/lib/grafana/dashboards
      - grafana-data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
      - tempo

volumes:
  tempo-data:
  prometheus-data:
  grafana-data:
```

**With config files:**
- `otel-collector-config.yaml` - Routes to Tempo + Prometheus
- `tempo.yaml` - Tempo configuration
- `prometheus.yml` - Scrapes OTEL collector
- `grafana/provisioning/` - Auto-configure datasources
- `grafana/dashboards/agentproxy.json` - Pre-built dashboard

---

## 1.7 Testing

### Unit Tests

**New file: `tests/test_telemetry.py`**

```python
import os
import pytest
from unittest.mock import patch, MagicMock
from agentproxy.telemetry import AgentProxyTelemetry, get_telemetry


class TestTelemetry:
    def test_telemetry_disabled_by_default(self):
        """Telemetry should be disabled if ENV var not set"""
        with patch.dict(os.environ, {}, clear=True):
            telemetry = AgentProxyTelemetry()
            assert telemetry.enabled is False
            assert telemetry.tracer is None
            assert telemetry.meter is None

    def test_telemetry_enabled_with_env(self):
        """Telemetry should initialize when enabled"""
        with patch.dict(os.environ, {"AGENTPROXY_ENABLE_TELEMETRY": "1"}):
            telemetry = AgentProxyTelemetry()
            assert telemetry.enabled is True
            assert telemetry.tracer is not None
            assert telemetry.meter is not None

    def test_backwards_compatibility(self):
        """PA should run normally with telemetry disabled"""
        from agentproxy import PA

        with patch.dict(os.environ, {}, clear=True):
            pa = PA()
            # Should not raise, should work as before
            # (mock out actual execution for test)

    @patch("agentproxy.telemetry.OTLPSpanExporter")
    @patch("agentproxy.telemetry.OTLPMetricExporter")
    def test_exporter_configuration(self, mock_metric_exporter, mock_span_exporter):
        """Should configure exporters from ENV vars"""
        with patch.dict(os.environ, {
            "AGENTPROXY_ENABLE_TELEMETRY": "1",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://custom:4317",
        }):
            telemetry = AgentProxyTelemetry()

            # Verify exporters were created with correct endpoint
            mock_span_exporter.assert_called_once()
            mock_metric_exporter.assert_called_once()
```

### Integration Tests

**New file: `tests/integration/test_otel_integration.py`**

```python
import subprocess
import time
import requests
import pytest


@pytest.mark.integration
class TestOTELIntegration:
    def test_end_to_end_with_collector(self):
        """Test full OTEL flow with real collector"""
        # Start OTEL collector
        collector = subprocess.Popen([
            "docker", "run", "--rm", "-p", "4317:4317", "-p", "8889:8889",
            "otel/opentelemetry-collector:latest"
        ])

        time.sleep(5)  # Wait for collector to start

        try:
            # Run agentproxy with telemetry enabled
            result = subprocess.run([
                "python", "-m", "agentproxy", "Write hello world"
            ], env={
                "AGENTPROXY_ENABLE_TELEMETRY": "1",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
            }, capture_output=True, timeout=60)

            assert result.returncode == 0

            # Verify metrics were exported
            time.sleep(2)  # Wait for export
            metrics = requests.get("http://localhost:8889/metrics").text
            assert "agentproxy_tasks_started" in metrics

        finally:
            collector.terminate()
```

---

## 1.8 Pull Request Checklist

Before submitting PR to agentproxy:

- [ ] All tests pass (`pytest tests/`)
- [ ] Backwards compatibility verified (telemetry disabled by default)
- [ ] README updated with OTEL section
- [ ] Example OTEL stack in `examples/otel-stack/`
- [ ] Grafana dashboard template included
- [ ] Code follows existing style (black, flake8)
- [ ] Type hints added where appropriate
- [ ] No breaking changes to existing APIs
- [ ] ENV var configuration documented
- [ ] Trace context propagation to Claude subprocess working
- [ ] PR description includes:
  - What: Add OpenTelemetry instrumentation
  - Why: Visibility into PA operations for production deployments
  - How: Opt-in via ENV vars, follows claude-code-otel.sh pattern
  - Testing: Unit + integration tests, example stack

---

# Phase 2: Plugin Architecture

## Overview

Add plugin system to enable extensibility without modifying core code.

**Goals:**
1. Enable third-party extensions (fleet hooks, custom functions, etc.)
2. Clean separation between core and extensions
3. Backwards compatible (no plugins = works as before)
4. Simple API for plugin developers

**Use Cases:**
- Fleet-specific hooks (pre/postflight validation)
- Custom verification functions
- Alternative LLM providers
- Custom telemetry backends
- Team-specific prompts and rules

---

## 2.1 Plugin Architecture Design

### Plugin Lifecycle Hooks

```python
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from enum import Enum


class PluginHookPhase(str, Enum):
    """Lifecycle phases where plugins can hook"""

    # Initialization
    ON_INIT = "on_init"

    # Task lifecycle
    ON_TASK_START = "on_task_start"
    ON_TASK_COMPLETE = "on_task_complete"
    ON_TASK_ERROR = "on_task_error"

    # PA lifecycle
    ON_PA_REASONING_START = "on_pa_reasoning_start"
    ON_PA_REASONING_COMPLETE = "on_pa_reasoning_complete"
    ON_PA_DECISION = "on_pa_decision"

    # Function execution
    ON_FUNCTION_PRE = "on_function_pre"
    ON_FUNCTION_POST = "on_function_post"

    # Claude interaction
    ON_CLAUDE_START = "on_claude_start"
    ON_CLAUDE_OUTPUT = "on_claude_output"

    # File operations
    ON_FILE_CHANGE = "on_file_change"


class PluginResult:
    """Result from plugin hook execution"""

    def __init__(self,
                 action: str = "continue",  # continue, block, modify
                 message: Optional[str] = None,
                 data: Optional[Dict[str, Any]] = None):
        self.action = action
        self.message = message
        self.data = data or {}

    @staticmethod
    def ok():
        return PluginResult("continue")

    @staticmethod
    def block(message: str):
        return PluginResult("block", message)

    @staticmethod
    def modify(data: Dict[str, Any], message: Optional[str] = None):
        return PluginResult("modify", message, data)


class PluginContext:
    """Context passed to plugin hooks"""

    def __init__(self, phase: PluginHookPhase, **kwargs):
        self.phase = phase
        self.data = kwargs
        self._storage = {}  # Plugin-specific storage

    def store(self, key: str, value: Any):
        """Store data for later retrieval"""
        self._storage[key] = value

    def retrieve(self, key: str, default: Any = None) -> Any:
        """Retrieve stored data"""
        return self._storage.get(key, default)


class AgentProxyPlugin(ABC):
    """Base class for all agentproxy plugins"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier"""
        pass

    @property
    def version(self) -> str:
        """Plugin version"""
        return "0.1.0"

    def on_init(self, pa: 'PA') -> None:
        """Called when PA initializes. Override to setup plugin."""
        pass

    def supports_hook(self, phase: PluginHookPhase) -> bool:
        """Check if plugin implements a hook"""
        hook_method = f"hook_{phase.value}"
        return hasattr(self, hook_method)

    def execute_hook(self, context: PluginContext) -> PluginResult:
        """Execute hook for given phase"""
        hook_method = f"hook_{context.phase.value}"

        if hasattr(self, hook_method):
            return getattr(self, hook_method)(context)

        return PluginResult.ok()

    # Optional hook methods (plugins override what they need)

    def hook_on_task_start(self, context: PluginContext) -> PluginResult:
        """Called when task starts"""
        return PluginResult.ok()

    def hook_on_task_complete(self, context: PluginContext) -> PluginResult:
        """Called when task completes"""
        return PluginResult.ok()

    def hook_on_pa_decision(self, context: PluginContext) -> PluginResult:
        """Called after PA makes a decision"""
        return PluginResult.ok()

    def hook_on_function_pre(self, context: PluginContext) -> PluginResult:
        """Called before function execution"""
        return PluginResult.ok()

    def hook_on_file_change(self, context: PluginContext) -> PluginResult:
        """Called when file is modified"""
        return PluginResult.ok()
```

---

## 2.2 Plugin Manager

**New file: `agentproxy/plugin_manager.py`**

```python
import os
import importlib
import importlib.util
from pathlib import Path
from typing import List, Dict, Any
import logging

from .plugins.base import AgentProxyPlugin, PluginContext, PluginResult, PluginHookPhase


logger = logging.getLogger(__name__)


class PluginManager:
    """Manages plugin lifecycle and execution"""

    def __init__(self):
        self.plugins: List[AgentProxyPlugin] = []
        self._enabled = os.getenv("AGENTPROXY_PLUGINS_ENABLED", "1") == "1"

        if self._enabled:
            self._load_plugins()

    def _load_plugins(self):
        """Discover and load plugins"""
        # Load from multiple sources

        # 1. Built-in plugins (optional)
        self._load_builtin_plugins()

        # 2. Plugins directory (./plugins/)
        plugins_dir = os.getenv("AGENTPROXY_PLUGINS_DIR", "./plugins")
        if os.path.exists(plugins_dir):
            self._load_from_directory(plugins_dir)

        # 3. Individual plugin modules (comma-separated ENV var)
        plugin_modules = os.getenv("AGENTPROXY_PLUGINS", "")
        if plugin_modules:
            for module_path in plugin_modules.split(","):
                self._load_plugin_module(module_path.strip())

        logger.info(f"Loaded {len(self.plugins)} plugins: {[p.name for p in self.plugins]}")

    def _load_builtin_plugins(self):
        """Load built-in plugins (e.g., OTEL plugin)"""
        try:
            from .plugins.otel_plugin import OTELPlugin
            if os.getenv("AGENTPROXY_ENABLE_TELEMETRY") == "1":
                self.plugins.append(OTELPlugin())
        except ImportError:
            pass  # OTEL plugin not available

    def _load_from_directory(self, directory: str):
        """Load all plugins from directory"""
        plugin_path = Path(directory)

        for file in plugin_path.glob("*.py"):
            if file.name.startswith("_"):
                continue

            try:
                module_name = file.stem
                spec = importlib.util.spec_from_file_location(module_name, file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find plugin classes
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                        issubclass(attr, AgentProxyPlugin) and
                        attr is not AgentProxyPlugin):
                        self.plugins.append(attr())
                        logger.info(f"Loaded plugin from {file}: {attr_name}")

            except Exception as e:
                logger.error(f"Failed to load plugin from {file}: {e}")

    def _load_plugin_module(self, module_path: str):
        """Load plugin from module path (e.g., 'mypackage.myplugin')"""
        try:
            module = importlib.import_module(module_path)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and
                    issubclass(attr, AgentProxyPlugin) and
                    attr is not AgentProxyPlugin):
                    self.plugins.append(attr())
                    logger.info(f"Loaded plugin from module {module_path}: {attr_name}")

        except Exception as e:
            logger.error(f"Failed to load plugin module {module_path}: {e}")

    def initialize_plugins(self, pa: 'PA'):
        """Initialize all plugins with PA instance"""
        for plugin in self.plugins:
            try:
                plugin.on_init(pa)
                logger.debug(f"Initialized plugin: {plugin.name}")
            except Exception as e:
                logger.error(f"Failed to initialize plugin {plugin.name}: {e}")

    def trigger_hook(self, phase: PluginHookPhase, **context_data) -> List[PluginResult]:
        """Trigger hook on all plugins that support it"""
        if not self._enabled:
            return [PluginResult.ok()]

        results = []
        context = PluginContext(phase, **context_data)

        for plugin in self.plugins:
            if plugin.supports_hook(phase):
                try:
                    result = plugin.execute_hook(context)
                    results.append(result)

                    # If any plugin blocks, stop processing
                    if result.action == "block":
                        logger.warning(f"Plugin {plugin.name} blocked at {phase.value}: {result.message}")
                        break

                except Exception as e:
                    logger.error(f"Plugin {plugin.name} failed at {phase.value}: {e}")
                    results.append(PluginResult.ok())  # Continue on plugin error

        return results

    def check_blocked(self, results: List[PluginResult]) -> tuple[bool, Optional[str]]:
        """Check if any plugin blocked"""
        for result in results:
            if result.action == "block":
                return True, result.message
        return False, None
```

---

## 2.3 Integration into PA

### File: `agentproxy/pa.py`

**Add at top:**
```python
from .plugin_manager import PluginManager
from .plugins.base import PluginHookPhase
```

**Add to `PA.__init__()`:**
```python
class PA:
    def __init__(self, ...):
        # ... existing init ...

        # Initialize plugin system
        self.plugin_manager = PluginManager()
        self.plugin_manager.initialize_plugins(self)
```

**Add hooks in `run()`:**
```python
def run(self, prompt: str, working_dir: str = "./sandbox", timeout: int = None) -> SessionInfo:
    # Hook: on_task_start
    results = self.plugin_manager.trigger_hook(
        PluginHookPhase.ON_TASK_START,
        prompt=prompt,
        working_dir=working_dir,
    )

    blocked, message = self.plugin_manager.check_blocked(results)
    if blocked:
        raise RuntimeError(f"Task blocked by plugin: {message}")

    try:
        # ... existing run logic ...

        # Hook: on_task_complete
        self.plugin_manager.trigger_hook(
            PluginHookPhase.ON_TASK_COMPLETE,
            session=session,
            status="completed",
        )

        return session

    except Exception as e:
        # Hook: on_task_error
        self.plugin_manager.trigger_hook(
            PluginHookPhase.ON_TASK_ERROR,
            error=e,
        )
        raise
```

**Add hooks in PA agent reasoning:**
```python
# In pa_agent.py

def reasoning_loop(self, claude_output: str, file_changes: List[str]) -> PAReasoning:
    # Hook: on_pa_reasoning_start
    self.pa.plugin_manager.trigger_hook(
        PluginHookPhase.ON_PA_REASONING_START,
        claude_output=claude_output,
        file_changes=file_changes,
    )

    reasoning = self._do_reasoning(claude_output, file_changes)

    # Hook: on_pa_decision
    self.pa.plugin_manager.trigger_hook(
        PluginHookPhase.ON_PA_DECISION,
        decision=reasoning.decision,
        function=reasoning.function_to_call,
    )

    return reasoning
```

---

## 2.4 Example Plugin: OTEL Plugin

**Refactor Phase 1 OTEL code as a plugin:**

**New file: `agentproxy/plugins/otel_plugin.py`**

```python
from .base import AgentProxyPlugin, PluginContext, PluginResult
from ..telemetry import get_telemetry
import time


class OTELPlugin(AgentProxyPlugin):
    """OpenTelemetry instrumentation plugin"""

    @property
    def name(self) -> str:
        return "otel"

    def on_init(self, pa):
        """Initialize telemetry"""
        self.telemetry = get_telemetry()
        self.task_start_time = None

    def hook_on_task_start(self, context: PluginContext) -> PluginResult:
        """Record task start"""
        if self.telemetry.enabled:
            self.telemetry.tasks_started.add(1)
            self.telemetry.active_sessions.add(1)
            self.task_start_time = time.time()

        return PluginResult.ok()

    def hook_on_task_complete(self, context: PluginContext) -> PluginResult:
        """Record task completion"""
        if self.telemetry.enabled:
            duration = time.time() - self.task_start_time
            status = context.data.get("status", "unknown")

            self.telemetry.tasks_completed.add(1, {"status": status})
            self.telemetry.task_duration.record(duration)
            self.telemetry.active_sessions.add(-1)

        return PluginResult.ok()

    def hook_on_pa_decision(self, context: PluginContext) -> PluginResult:
        """Record PA decision"""
        if self.telemetry.enabled:
            decision = context.data.get("decision")
            self.telemetry.pa_decisions.add(1, {"decision": decision})

        return PluginResult.ok()
```

---

## 2.5 Example Plugin: Fleet Hooks Plugin

**Show what a fleet-specific plugin looks like:**

**New file: `plugins/fleet_hooks.py` (user's repo, not agentproxy)**

```python
from agentproxy.plugins.base import AgentProxyPlugin, PluginContext, PluginResult
import subprocess
import os


class FleetHooksPlugin(AgentProxyPlugin):
    """Fleet-specific safety hooks"""

    @property
    def name(self) -> str:
        return "fleet_hooks"

    def on_init(self, pa):
        """Load fleet-specific configuration"""
        self.require_signed_commits = os.getenv("FLEET_REQUIRE_SIGNED_COMMITS", "1") == "1"
        self.git_snapshot = None

    def hook_on_task_start(self, context: PluginContext) -> PluginResult:
        """Pre-flight: Capture git state"""
        working_dir = context.data.get("working_dir")

        # Verify clean git state
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_dir,
            capture_output=True,
            text=True,
        )

        if result.stdout.strip():
            return PluginResult.block("Git working directory is not clean. Commit or stash changes first.")

        # Capture snapshot for rollback
        snapshot = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=working_dir,
            capture_output=True,
            text=True,
        )
        context.store("git_head", snapshot.stdout.strip())

        return PluginResult.ok()

    def hook_on_task_error(self, context: PluginContext) -> PluginResult:
        """Post-flight: Rollback on error"""
        git_head = context.retrieve("git_head")

        if git_head:
            # Rollback to snapshot
            subprocess.run(["git", "reset", "--hard", git_head])
            print(f"[FleetHooks] Rolled back to {git_head[:7]}")

        return PluginResult.ok()

    def hook_on_file_change(self, context: PluginContext) -> PluginResult:
        """Validate file changes"""
        file_path = context.data.get("file_path")

        # Block changes to sensitive files
        if file_path.startswith("/etc/") or file_path == "/.env":
            return PluginResult.block(f"Blocked modification to sensitive file: {file_path}")

        return PluginResult.ok()
```

**Usage:**
```bash
# Enable plugin
export AGENTPROXY_PLUGINS=fleet_hooks
export AGENTPROXY_PLUGINS_DIR=./plugins

# Run agentproxy
python -m agentproxy "Deploy new feature"

# Plugin will:
# - Check git is clean before starting
# - Block sensitive file modifications
# - Rollback git on error
```

---

## 2.6 Configuration

### Environment Variables

```bash
# Enable/disable plugin system (default: enabled)
AGENTPROXY_PLUGINS_ENABLED=1

# Plugins directory (default: ./plugins)
AGENTPROXY_PLUGINS_DIR=/path/to/plugins

# Specific plugins to load (comma-separated module paths)
AGENTPROXY_PLUGINS=fleet_hooks,mycompany.custom_plugin

# Plugin-specific config (example)
FLEET_REQUIRE_SIGNED_COMMITS=1
```

### Config File (Optional Enhancement)

**New file: `.agentproxy/config.yaml`**

```yaml
plugins:
  enabled: true
  directory: ./plugins
  load:
    - name: fleet_hooks
      module: fleet_hooks
      config:
        require_signed_commits: true
        rollback_on_error: true

    - name: custom_verifier
      module: mycompany.custom_verifier
      config:
        endpoint: https://verifier.internal.corp
```

---

## 2.7 Documentation

### README.md Updates

**Add section: "Plugins & Extensibility"**

````markdown
## Plugins & Extensibility

agentproxy supports plugins for custom behavior and integrations.

### Quick Start

1. **Create a plugin file** (`plugins/my_plugin.py`):
   ```python
   from agentproxy.plugins.base import AgentProxyPlugin, PluginContext, PluginResult

   class MyPlugin(AgentProxyPlugin):
       @property
       def name(self) -> str:
           return "my_plugin"

       def hook_on_task_start(self, context: PluginContext) -> PluginResult:
           print(f"Task starting: {context.data['prompt']}")
           return PluginResult.ok()
   ```

2. **Enable the plugin**:
   ```bash
   export AGENTPROXY_PLUGINS_DIR=./plugins
   python -m agentproxy "Your task"
   ```

### Plugin Hooks

Plugins can hook into these lifecycle phases:

- `on_task_start` - Before task execution begins
- `on_task_complete` - After task completes successfully
- `on_task_error` - When task fails
- `on_pa_reasoning_start` - Before PA reasoning cycle
- `on_pa_decision` - After PA makes a decision
- `on_function_pre` - Before function execution
- `on_function_post` - After function execution
- `on_file_change` - When file is modified

### Plugin API

See `agentproxy/plugins/base.py` for full API documentation.

**Key methods:**
- `PluginResult.ok()` - Continue normally
- `PluginResult.block(message)` - Block operation
- `PluginResult.modify(data)` - Modify context data

### Example Plugins

**Built-in:**
- `otel_plugin` - OpenTelemetry instrumentation (auto-loaded if telemetry enabled)

**Community:**
- See `examples/plugins/` for more examples:
  - `fleet_hooks` - Fleet management safety hooks
  - `custom_prompts` - Load custom prompts
  - `slack_notifier` - Send notifications to Slack

### Configuration

```bash
# Enable/disable plugins (default: enabled)
AGENTPROXY_PLUGINS_ENABLED=1

# Plugins directory
AGENTPROXY_PLUGINS_DIR=./plugins

# Load specific plugins
AGENTPROXY_PLUGINS=my_plugin,another_plugin
```

### Creating a Plugin

1. Subclass `AgentProxyPlugin`
2. Implement `name` property
3. Override hook methods you need
4. Return `PluginResult` from hooks

See [Plugin Development Guide](docs/plugins.md) for details.
````

---

### New File: `docs/plugins.md`

**Comprehensive plugin development guide:**

```markdown
# Plugin Development Guide

## Overview

Plugins extend agentproxy with custom behavior without modifying core code.

## Plugin Structure

### Minimal Plugin

```python
from agentproxy.plugins.base import AgentProxyPlugin, PluginContext, PluginResult

class MyPlugin(AgentProxyPlugin):
    @property
    def name(self) -> str:
        """Unique plugin identifier"""
        return "my_plugin"

    @property
    def version(self) -> str:
        """Plugin version (optional)"""
        return "1.0.0"

    def on_init(self, pa):
        """Called once when PA initializes"""
        self.pa = pa
        print("MyPlugin initialized!")
```

## Hook Methods

### Task Lifecycle

```python
def hook_on_task_start(self, context: PluginContext) -> PluginResult:
    """Called before task execution"""
    prompt = context.data.get("prompt")
    working_dir = context.data.get("working_dir")

    # Example: Block tasks with certain keywords
    if "dangerous" in prompt.lower():
        return PluginResult.block("Task contains dangerous keyword")

    return PluginResult.ok()

def hook_on_task_complete(self, context: PluginContext) -> PluginResult:
    """Called after successful task completion"""
    session = context.data.get("session")
    print(f"Task completed: {session.id}")
    return PluginResult.ok()

def hook_on_task_error(self, context: PluginContext) -> PluginResult:
    """Called when task fails"""
    error = context.data.get("error")
    print(f"Task failed: {error}")
    return PluginResult.ok()
```

### PA Reasoning

```python
def hook_on_pa_reasoning_start(self, context: PluginContext) -> PluginResult:
    """Called before PA reasoning cycle"""
    claude_output = context.data.get("claude_output")
    file_changes = context.data.get("file_changes")
    return PluginResult.ok()

def hook_on_pa_decision(self, context: PluginContext) -> PluginResult:
    """Called after PA makes decision"""
    decision = context.data.get("decision")  # CONTINUE, VERIFY, DONE
    function = context.data.get("function")  # Function to execute

    # Example: Log all decisions
    print(f"PA decided: {decision} -> {function}")

    return PluginResult.ok()
```

### Function Execution

```python
def hook_on_function_pre(self, context: PluginContext) -> PluginResult:
    """Called before function execution"""
    function_name = context.data.get("function_name")
    args = context.data.get("args")

    # Example: Block certain functions
    if function_name == "MARK_DONE" and not self._verification_passed:
        return PluginResult.block("Cannot mark done: verification not passed")

    return PluginResult.ok()

def hook_on_function_post(self, context: PluginContext) -> PluginResult:
    """Called after function execution"""
    function_name = context.data.get("function_name")
    result = context.data.get("result")
    return PluginResult.ok()
```

### File Operations

```python
def hook_on_file_change(self, context: PluginContext) -> PluginResult:
    """Called when file is modified"""
    file_path = context.data.get("file_path")
    operation = context.data.get("operation")  # write, edit, create

    # Example: Block sensitive file modifications
    if file_path.startswith("/etc/"):
        return PluginResult.block(f"Cannot modify system file: {file_path}")

    return PluginResult.ok()
```

## Plugin Results

### Continue (Default)

```python
return PluginResult.ok()
```

### Block Operation

```python
return PluginResult.block("Reason for blocking")
```

This stops execution and raises an error with your message.

### Modify Context

```python
return PluginResult.modify(
    data={"prompt": modified_prompt},
    message="Modified prompt to add safety checks"
)
```

## Context Storage

Store data across hook invocations:

```python
def hook_on_task_start(self, context: PluginContext) -> PluginResult:
    # Store data
    context.store("start_time", time.time())
    return PluginResult.ok()

def hook_on_task_complete(self, context: PluginContext) -> PluginResult:
    # Retrieve data
    start_time = context.retrieve("start_time")
    duration = time.time() - start_time
    print(f"Task took {duration:.2f} seconds")
    return PluginResult.ok()
```

## Examples

### Example 1: Notification Plugin

```python
import requests

class SlackNotifierPlugin(AgentProxyPlugin):
    @property
    def name(self) -> str:
        return "slack_notifier"

    def on_init(self, pa):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    def hook_on_task_complete(self, context: PluginContext) -> PluginResult:
        session = context.data.get("session")

        requests.post(self.webhook_url, json={
            "text": f"✅ Task completed: {session.task_description}"
        })

        return PluginResult.ok()

    def hook_on_task_error(self, context: PluginContext) -> PluginResult:
        error = context.data.get("error")

        requests.post(self.webhook_url, json={
            "text": f"❌ Task failed: {error}"
        })

        return PluginResult.ok()
```

### Example 2: Custom Verification Plugin

```python
class CustomVerifierPlugin(AgentProxyPlugin):
    @property
    def name(self) -> str:
        return "custom_verifier"

    def hook_on_function_post(self, context: PluginContext) -> PluginResult:
        function_name = context.data.get("function_name")

        if function_name == "VERIFY_CODE":
            # Run additional custom verification
            if not self._custom_security_scan():
                return PluginResult.block("Custom security scan failed")

        return PluginResult.ok()

    def _custom_security_scan(self) -> bool:
        # Your custom verification logic
        return True
```

## Testing Plugins

```python
import pytest
from agentproxy.plugins.base import PluginContext, PluginHookPhase
from my_plugin import MyPlugin

def test_my_plugin_blocks_dangerous_tasks():
    plugin = MyPlugin()

    context = PluginContext(
        PluginHookPhase.ON_TASK_START,
        prompt="Do something dangerous"
    )

    result = plugin.hook_on_task_start(context)

    assert result.action == "block"
    assert "dangerous" in result.message.lower()
```

## Distribution

### As Python Package

```bash
# pyproject.toml
[project]
name = "agentproxy-myplugin"
version = "1.0.0"
dependencies = ["agentproxy>=0.2.0"]

# Install
pip install agentproxy-myplugin

# Use
export AGENTPROXY_PLUGINS=agentproxy_myplugin.MyPlugin
```

### As File

```bash
# Place in plugins/ directory
cp my_plugin.py ./plugins/

# Run
export AGENTPROXY_PLUGINS_DIR=./plugins
python -m agentproxy "Task"
```

## Best Practices

1. **Keep plugins focused** - One plugin, one responsibility
2. **Handle errors gracefully** - Don't crash PA with plugin errors
3. **Document configuration** - Make ENV vars clear
4. **Test thoroughly** - Unit test your hooks
5. **Be backwards compatible** - Don't assume PA internals
6. **Performance matters** - Keep hook execution fast

## FAQ

**Q: Can plugins modify PA behavior?**
A: Plugins can block operations or modify context data, but cannot change PA's core logic.

**Q: How many plugins can I load?**
A: Unlimited, but each hook is called sequentially. Keep it reasonable for performance.

**Q: Can plugins depend on each other?**
A: Yes, but load order is undefined. Use context storage for inter-plugin communication.

**Q: Are plugins sandboxed?**
A: No, plugins run in the same process as PA. Only use trusted plugins.
```

---

## 2.8 Verification

### Test Plugin System

1. **Backwards compatibility test:**
   ```bash
   # Disable plugins
   export AGENTPROXY_PLUGINS_ENABLED=0
   python -m agentproxy "Write hello world"
   # Should work exactly as before
   ```

2. **Load example plugin:**
   ```bash
   # Create example plugin
   mkdir -p plugins
   cat > plugins/example.py << 'EOF'
   from agentproxy.plugins.base import AgentProxyPlugin, PluginContext, PluginResult

   class ExamplePlugin(AgentProxyPlugin):
       @property
       def name(self):
           return "example"

       def hook_on_task_start(self, context):
           print(f"[ExamplePlugin] Task starting: {context.data.get('prompt')}")
           return PluginResult.ok()
   EOF

   # Run with plugin
   export AGENTPROXY_PLUGINS_DIR=./plugins
   python -m agentproxy "Write hello world"
   # Should see plugin output
   ```

3. **Test plugin blocking:**
   ```bash
   # Create blocking plugin
   cat > plugins/blocker.py << 'EOF'
   from agentproxy.plugins.base import AgentProxyPlugin, PluginContext, PluginResult

   class BlockerPlugin(AgentProxyPlugin):
       @property
       def name(self):
           return "blocker"

       def hook_on_task_start(self, context):
           if "forbidden" in context.data.get("prompt", "").lower():
               return PluginResult.block("Task contains forbidden keyword")
           return PluginResult.ok()
   EOF

   # Should fail
   python -m agentproxy "Do something forbidden"
   # Expected: RuntimeError: Task blocked by plugin

   # Should succeed
   python -m agentproxy "Do something allowed"
   ```

---

## 2.9 Pull Request Checklist

- [ ] Plugin base classes implemented (`plugins/base.py`)
- [ ] Plugin manager implemented (`plugin_manager.py`)
- [ ] Hooks integrated into PA lifecycle
- [ ] OTEL refactored as plugin (optional)
- [ ] Example plugins in `examples/plugins/`
- [ ] Comprehensive documentation (`docs/plugins.md`)
- [ ] README updated with plugin section
- [ ] Unit tests for plugin system
- [ ] Integration tests with example plugins
- [ ] Backwards compatible (works with no plugins)
- [ ] ENV var configuration documented
- [ ] PR description includes:
  - What: Plugin architecture for extensibility
  - Why: Enable third-party extensions without core modifications
  - How: Hook-based system with lifecycle phases
  - Examples: Fleet hooks, custom verification, notifications

---

# Implementation Timeline

## Week 1: Phase 0 + Phase 1 Foundation
- **Day 1:** Phase 0 - Package reorganization
  - Create pyproject.toml with optional deps
  - Reorganize into proper package structure
  - Add __main__.py and entry points
  - Test: `pip install -e .` and `pa --help` works

- **Day 2:** Phase 1 - OTEL dependencies and setup
  - Create `telemetry.py` with conditional imports
  - Test: works without OTEL deps AND with `pip install -e '.[telemetry]'`

- **Day 3-4:** Phase 1 - Core instrumentation
  - Instrument PA core (`pa.py`, `pa_agent.py`)
  - Instrument Gemini API (`gemini_client.py`)

- **Day 5:** Phase 1 - Function and process instrumentation
  - Instrument function executor
  - Instrument process manager with trace context propagation

- **Day 6-7:** Phase 1 - Testing and example stack
  - Unit tests for telemetry
  - Example OTEL stack (docker-compose)
  - Initial README updates

## Week 2: Phase 1 - OTEL Polish & PR
- **Day 1-2:** Grafana dashboard template
  - Create pre-built dashboard JSON
  - Add provisioning configs for Grafana

- **Day 3-4:** Integration tests
  - End-to-end test with real OTEL collector
  - Verify trace propagation to Claude subprocess

- **Day 5:** Documentation finalization
  - Complete README OTEL section
  - Add troubleshooting guide

- **Day 6-7:** PR preparation and submission
  - Code review pass (black, flake8, mypy)
  - PR description with examples
  - Submit to upstream

## Week 3: Phase 2 - Plugin Architecture
- **Day 1-2:** Plugin base classes
  - Design and implement plugin base (`plugins/base.py`)
  - Plugin hook phases enum
  - PluginResult and PluginContext

- **Day 3-4:** Plugin manager
  - Implement discovery and loading
  - Auto-load from directory
  - Load from module paths

- **Day 5:** PA integration
  - Add hooks to PA lifecycle
  - Add plugin manager initialization

- **Day 6-7:** Example plugins
  - Refactor OTEL as plugin (optional)
  - Create fleet hooks example
  - Create notification example

## Week 4: Phase 2 - Plugin Polish & PR
- **Day 1-2:** Documentation
  - Comprehensive plugin development guide (`docs/plugins.md`)
  - README plugin section

- **Day 3-4:** Testing
  - Unit tests for plugin system
  - Integration tests with example plugins
  - Test backwards compatibility

- **Day 5:** Final polish
  - Code review pass
  - Ensure all examples work

- **Day 6-7:** PR preparation and submission
  - PR description with plugin examples
  - Submit to upstream

---

# Critical Files Reference

## Phase 0: Package Structure
- **New:** `pyproject.toml` - Modern Python package configuration
- **New:** `agentproxy/__main__.py` - Entry point for `python -m agentproxy`
- **Modified:** `agentproxy/cli.py` - Add main() entry point for `pa` command
- **Modified:** `agentproxy/server.py` - Add main() entry point for `pa-server` command
- **Modified:** `README.md` - Installation and usage instructions
- **Keep:** `requirements.txt` - Backwards compatibility (optional, can be generated from pyproject.toml)

## Phase 1: OTEL
- **New:** `agentproxy/telemetry.py` - OTEL initialization with conditional imports
- **Modified:** `agentproxy/pa.py` - Add spans to task lifecycle
- **Modified:** `agentproxy/pa_agent.py` - Add spans to reasoning loop
- **Modified:** `agentproxy/gemini_client.py` - Add spans to API calls
- **Modified:** `agentproxy/function_executor.py` - Add spans to functions
- **Modified:** `agentproxy/process_manager.py` - Trace context propagation
- **Modified:** `agentproxy/server.py` - FastAPI auto-instrumentation
- **New:** `examples/otel-stack/` - Example deployment with Grafana/Tempo/Prometheus
- **New:** `examples/otel-stack/docker-compose.yml` - Full observability stack
- **New:** `examples/otel-stack/otel-collector-config.yaml` - Collector configuration
- **New:** `examples/otel-stack/grafana/dashboards/agentproxy.json` - Pre-built dashboard
- **New:** `tests/test_telemetry.py` - Unit tests
- **New:** `tests/integration/test_otel_integration.py` - Integration tests
- **Modified:** `README.md` - OTEL documentation section

## Phase 2: Plugins
- **New:** `agentproxy/plugins/` - Plugin system package
- **New:** `agentproxy/plugins/__init__.py` - Package init
- **New:** `agentproxy/plugins/base.py` - Plugin base classes, hooks, context
- **New:** `agentproxy/plugin_manager.py` - Plugin discovery and execution
- **New:** `agentproxy/plugins/otel_plugin.py` - OTEL refactored as plugin (optional)
- **Modified:** `agentproxy/pa.py` - Add plugin hooks to lifecycle
- **Modified:** `agentproxy/pa_agent.py` - Add plugin hooks to reasoning
- **Modified:** `agentproxy/function_executor.py` - Add plugin hooks to functions
- **New:** `examples/plugins/` - Example plugin implementations
- **New:** `examples/plugins/fleet_hooks.py` - Fleet safety hooks example
- **New:** `examples/plugins/slack_notifier.py` - Notification plugin example
- **New:** `docs/plugins.md` - Comprehensive plugin development guide
- **New:** `tests/test_plugin_system.py` - Plugin unit tests
- **Modified:** `README.md` - Plugin system documentation

---

# Success Criteria

## Phase 0: Package Structure
- ✅ `pyproject.toml` created with optional dependencies
- ✅ Package installs with `pip install -e .`
- ✅ OTEL deps only install with `pip install -e '.[telemetry]'`
- ✅ `pa` command works after install
- ✅ `pa-server` command works after install
- ✅ `python -m agentproxy` still works
- ✅ Backwards compatible (old `python cli.py` works)
- ✅ README updated with installation instructions

## Phase 1: OTEL
- ✅ Telemetry opt-in, backwards compatible
- ✅ Works WITHOUT OTEL deps (graceful degradation)
- ✅ Traces exported to OTEL collector (when deps installed)
- ✅ Metrics available in Prometheus/Grafana
- ✅ Trace context links PA spans to Claude spans
- ✅ README updated with setup instructions
- ✅ Example stack deployable with docker-compose
- ✅ Grafana dashboard template provided
- ✅ Installation: `pip install agentproxy[telemetry]`
- ✅ PR merged to upstream

## Phase 2: Plugins
- ✅ Plugin system opt-in, backwards compatible
- ✅ Plugins load from directory and module paths
- ✅ Hooks work at all lifecycle phases
- ✅ Plugins can block operations
- ✅ Example plugins demonstrate value
- ✅ Documentation complete (`docs/plugins.md`)
- ✅ README updated with plugin section
- ✅ OTEL can optionally work as plugin
- ✅ PR merged to upstream (or clear path forward)

---

# Next Actions

## This Week (Phase 0 + Phase 1 Start)
1. **Day 1:** Create pyproject.toml and reorganize package structure
   - Test: `pip install -e .` works
   - Test: `pa` command available

2. **Day 2:** Add OTEL with optional deps
   - Test: Works WITHOUT `[telemetry]` extra
   - Test: Works WITH `pip install -e '.[telemetry]'`

3. **Day 3-4:** Core OTEL instrumentation
   - Implement telemetry.py with conditional imports
   - Instrument PA reasoning and Gemini API

4. **Day 5-7:** Complete Phase 1 implementation
   - Function executor and process manager
   - Testing and example stack

## Next Week (Phase 1 PR)
- Polish OTEL implementation
- Create Grafana dashboard
- Write comprehensive documentation
- Submit PR to upstream

## Week 3-4 (Phase 2)
- Implement plugin architecture
- Example plugins
- Documentation
- Submit PR to upstream

## After Upstream Merge
- Build fleet-specific plugins (Phases 3-5)
- Event detection and coordinator/worker architecture
- Docker integration
- Autonomous incident response loop