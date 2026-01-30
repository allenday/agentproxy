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

## Progressive Disclosure (Onboarding Path)

1) **Fast path:** `README.md` → “Fast path to dogfood” (validated command)
2) **Operator details:** `docs/fast-dogfood.md` (frontmatter + errors + pytest scoping)
3) **Smoke plan:** `docs/plans/2026-01-31-toy-fib.md` (minimal plan template)
4) **Subsystem guides:** package-level `AGENTS.md` files (purpose, entry points, SOP/fixtures/telemetry)

## Terminology: Commissioning vs Order vs Traveler

- **Commissioning**: Workstation setup (fixture + SOP materialization) before execution.
- **Order / Work Order**: The numbered unit of work in the BOM; ShopFloor routes and dispatches these.
- **Traveler**: The plan file (YAML frontmatter + task body) that travels with the work through stations.

## Data Model Rule

Pydantic `BaseModel` for all domain models. `dataclass` only for event/result structs (`OutputEvent`, `InspectionResult`).

## Package Map

| Package | Owns | AGENTS.md |
|---------|------|-----------|
| `sf/` | PA, CLI, server, models, telemetry, process manager | [sf/AGENTS.md](sf/AGENTS.md) |
| `sf/shopfloor/` | BOM routing, dispatch, assembly, Kaizen loop | [sf/shopfloor/AGENTS.md](sf/shopfloor/AGENTS.md) |
| `sf/workstation/` | Fixtures, SOP, QualityGate, capabilities | [sf/workstation/AGENTS.md](sf/workstation/AGENTS.md) |
| `sf/llm/` | LLM provider registry and adapters | [sf/llm/AGENTS.md](sf/llm/AGENTS.md) |
| `sf/telemetry/` | OTEL wiring + event processors | [sf/telemetry/AGENTS.md](sf/telemetry/AGENTS.md) |
| `sf/prompts/` | Static `.md` templates for Gemini (Tier 1 best practices) | [sf/prompts/AGENTS.md](sf/prompts/AGENTS.md) |
| `sf/sources/` | Webhook adapters (GitHub, Jira, Alert) | [sf/sources/AGENTS.md](sf/sources/AGENTS.md) |
| `sf/plugins/` | Hook-based plugin system | [sf/plugins/AGENTS.md](sf/plugins/AGENTS.md) |
| `sf/event_processors/` | Tool event enrichment for OTEL | [sf/event_processors/AGENTS.md](sf/event_processors/AGENTS.md) |
