# Pluggable LLM + QA Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Agent Proxy run reliably with a pluggable LLM layer (Codex/Claude/Gemini) and stronger QA/anti-loop controls, preserving OTEL safety and ShopFloor compatibility.

**Architecture:** Introduce a provider-agnostic LLM interface consumed by PA/ShopFloor; adapters for Claude CLI/API, Gemini HTTP, and Codex API; configuration selects a default provider while allowing per-work-order/provider overrides. QA uses metrics-based stall detection plus SOP/Verification gates; telemetry remains best-effort.

**Tech Stack:** Python 3.11+, Pydantic models, subprocess for CLI workers, HTTP clients for APIs, OTEL SDK (optional), pytest.

---

### Task 1: Inventory & Guardrails

**Files:**
- Modify: `sf/AGENTS.md`
- Modify: `sf/pa.py`
- Modify: `sf/shopfloor/AGENTS.md`

**Step 1:** Note new rule in `sf/AGENTS.md`: all domain models stay Pydantic; LLM provider must be selected via env/flag with safe default, and OTEL must never raise.  
**Step 2:** Add doc note in `sf/shopfloor/AGENTS.md` about heterogeneous providers allowed per WorkOrder (`required_capabilities["llm"]`).  
**Step 3:** In `sf/pa.py`, add constants for iteration/time budgets (`SF_MAX_ITERATIONS`, `SF_ITERATION_TIMEOUT_S`) and ensure defaults are low but overridable.

### Task 2: LLM Provider Abstraction

**Files:**
- Create: `sf/llm/base.py`
- Create: `sf/llm/types.py`
- Create: `sf/llm/providers/{claude.py,gemini.py,codex.py}`
- Modify: `sf/__init__.py`
- Modify: `sf/function_executor.py`
- Modify: `sf/pa_agent.py`

**Step 1:** Define `LLMRequest`/`LLMResult` Pydantic models (`types.py`) with fields: messages, tools, model, tokens_used, cost_usd, provider_name, tool_calls.  
**Step 2:** Define abstract `LLMProvider` in `base.py` with `generate(request: LLMRequest) -> LLMResult`.  
**Step 3:** Implement adapters:  
  - `claude.py`: wraps `ClaudeProcessManager` (existing) for now; map stream-json to `LLMResult`.  
  - `gemini.py`: wrap current `GeminiClient.call`; add tool-call no-op (returns text only).  
  - `codex.py`: HTTP client for OpenAI Chat Completions with tool_calls + token accounting.  
**Step 4:** Add provider registry + factory `get_provider(name, default_model=None, env=os.environ)`. Default provider from `SF_LLM_PROVIDER` (default `claude`), model optional; allow `WORK_ORDER.required_capabilities["llm"]` to override per request.  
**Step 5:** Export `get_provider` + types from `sf/__init__.py`.

### Task 3: Wire PA and FunctionExecutor to Provider Layer

**Files:**
- Modify: `sf/pa_agent.py`
- Modify: `sf/function_executor.py`
- Modify: `sf/process_manager.py` (minor: accept model/env overrides)

**Step 1:** Replace direct Gemini use with provider injection: PAAgent builds `LLMRequest` from system/user prompts and tool schema; selects provider via env and optional `WorkOrder` capability.  
**Step 2:** In `function_executor.py`, route tool-use responses through provider result’s `tool_calls`; maintain backward compatibility when provider lacks tools (fallback to text).  
**Step 3:** Ensure subprocess CLAUDE path uses `sf.process_manager` but returns `LLMResult`; include tokens if available, else None.

### Task 4: Reliability Controls (timeouts, iterations, circuit-breaker)

**Files:**
- Modify: `sf/pa.py`
- Modify: `sf/shopfloor/__init__.py` and `sf/shopfloor/assembly.py`
- Modify: `sf/workstation/quality_gate.py`
- Modify: `sf/plugin_manager.py` (optional hook)
- Modify: `tests/test_shopfloor_pipeline.py`
- Create: `tests/unit/test_llm_provider_selection.py`

**Step 1:** Enforce `SF_MAX_ITERATIONS` and `SF_ITERATION_TIMEOUT_S` in PA and ShopFloor loops; emit metrics/log fields `worker.iteration`, `worker.elapsed_s`.  
**Step 2:** Add circuit-breaker: consecutive provider errors > N (env `SF_LLM_MAX_ERRORS`, default 3) abort task with clear status.  
**Step 3:** Enhance `VerificationGate` to record gate name/result in events; add optional `SOPGate` to require SOP presence or explicit skip flag.  
**Step 4:** Stalling heuristic: track deltas (files changed count, tool_calls count, tokens consumed) over sliding window; if below thresholds, emit `OutputEvent` marked `stalled_warning` for supervisor judgment (no auto-fail).  
**Step 5:** Update tests: add unit test for provider selection overrides; extend ShopFloor pipeline stub to simulate provider errors and stalling warnings.

### Task 5: Telemetry Harmonization

**Files:**
- Modify: `sf/telemetry.py`
- Modify: `sf/event_processors/__init__.py` (if needed)
- Modify: `sf/plugins/otel_plugin.py`

**Step 1:** Add spans/metrics for `llm.call` with attrs `llm.provider`, `llm.model`, `llm.tools_used`, guarding all telemetry in try/except.  
**Step 2:** Ensure OTEL exporter remains optional; if missing deps, degrade to no-op without exceptions.  
**Step 3:** Update OTEL plugin to read provider data from `LLMResult` and include in spans.

### Task 6: CLI/Server Surface & Docs

**Files:**
- Modify: `sf/cli.py`
- Modify: `sf/server.py`
- Modify: `README.md`
- Modify: `docs/AGENTS.md` (if present) and add summary to `AGENTS.md`

**Step 1:** Add CLI flags/env help: `--llm-provider`, `--llm-endpoint`, `--llm-api-key`, `--llm-default-model` (optional). `--enable-parallel` to opt into ShopFloor parallel layers.  
**Step 2:** Server: accept provider selection in POST body; default to env.  
**Step 3:** Document configuration matrix and OTEL notes (north bus telemetry, south bus control).

### Task 7: Verification & Clean-up

**Files:**
- Modify: `requirements.txt` / `pyproject.toml` (if new deps)
- Run: `pip install -e ".[all]" && python3 -m pytest tests/ -q`

**Step 1:** Ensure deps for Codex/OpenAI client added.  
**Step 2:** Run full tests; fix breakages.  
**Step 3:** Summarize results and residual risks; propose follow-up for full API (non-CLI) Claude path if needed.

---

Execution options after plan approval:
1) Subagent-driven here (superpowers:subagent-driven-development)  
2) Parallel session using superpowers:executing-plans
