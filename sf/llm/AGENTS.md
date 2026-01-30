# sf/llm/ — LLM Providers

Purpose: Provider registry and adapters for Codex CLI/API, Gemini, and Claude.

Main entry points:
- `get_provider()` in `base.py` (selects provider by `SF_LLM_PROVIDER`)
- Provider implementations in `providers/` (`codex.py`, `gemini.py`, `claude.py`)

Where to look:
- **Provider registry:** `base.py`
- **Request/response types:** `types.py`
- **Codex CLI flags:** `SF_CODEX_FLAGS` and `SF_CODEX_TIMEOUT` (see `docs/fast-dogfood.md`)
- **SOP + fixtures:** `sf/workstation/` (see `sf/workstation/AGENTS.md`)
- **Telemetry:** `sf/telemetry.py` and `sf/event_processors/`
