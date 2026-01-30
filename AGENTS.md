# SF (Software Factory)

Manufacturing-inspired orchestration for coding agents. PA supervises Claude Code; ShopFloor parallelizes work across git worktrees with SOP-driven quality gates.

## Build & Test

```bash
pip install -e ".[all]"
python -m pytest tests/ -q
sf --workorder-type=bespoke --workorder-content="task"   # ShopFloor pipeline
sf "task"                                                 # Direct PA mode
sf-server                                                 # HTTP API + webhooks
```

## Operator Quickstart (Codex CLI)

For a one-shot, observable dogfood run with Codex CLI (workspace-write, 240s timeout), see:
- `docs/fast-dogfood.md` (copy-paste command, required frontmatter keys, fail-fast errors)
- 60-second smoke plan: `docs/plans/2026-01-31-toy-fib.md`

Use the smoke plan for quick validation and scope pytest accordingly; use the full suite for pre-merge confidence.

## Data Model Rule

Pydantic `BaseModel` for all domain models. `dataclass` only for event/result structs (`OutputEvent`, `InspectionResult`).

## Package Map

| Package | Owns | AGENTS.md |
|---------|------|-----------|
| `sf/` | PA, CLI, server, models, telemetry, process manager | [sf/AGENTS.md](sf/AGENTS.md) |
| `sf/shopfloor/` | BOM routing, dispatch, assembly, Kaizen loop | [sf/shopfloor/AGENTS.md](sf/shopfloor/AGENTS.md) |
| `sf/workstation/` | Fixtures, SOP, QualityGate, capabilities | [sf/workstation/AGENTS.md](sf/workstation/AGENTS.md) |
| `sf/prompts/` | Static `.md` templates for Gemini (Tier 1 best practices) | [sf/prompts/AGENTS.md](sf/prompts/AGENTS.md) |
| `sf/sources/` | Webhook adapters (GitHub, Jira, Alert) | [sf/sources/AGENTS.md](sf/sources/AGENTS.md) |
| `sf/plugins/` | Hook-based plugin system | [sf/plugins/AGENTS.md](sf/plugins/AGENTS.md) |
| `sf/event_processors/` | Tool event enrichment for OTEL | [sf/event_processors/AGENTS.md](sf/event_processors/AGENTS.md) |
