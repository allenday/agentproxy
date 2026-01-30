---
workstation:
  vcs:
    type: git_worktree          # auto branch/path derived; no manual prep
    parent: /Users/allenday/src/agentproxy
  runtime:
    python:
      version: "3.11"
      venv: .venv
  llm:
    provider: codex_cli
    flags: "--full-auto --sandbox workspace-write"
  telemetry:
    template: otel-compose-local
  tooling: {}
task: |
  Produce a polished "Operator Quickstart + Fast Dogfood" guide so Codex CLI runs are one-shot and observable.
  Update AGENTS.md and a short doc under docs/ to include:
    - Exact env/flags and the minimal working command (codex_cli, workspace-write sandbox, 240s timeout).
    - A minimal frontmatter snippet (vcs/llm/telemetry) with clear fail-fast messaging.
    - A 60-second smoke plan reference (2026-01-31-toy-fib.md) and how to scope pytest (quick vs full).
acceptance:
  - Only docs are changed (AGENTS.md plus one doc under docs/).
  - Quickstart shows a copy-paste command verified to work with codex_cli.
  - Frontmatter snippet is valid YAML, minimal, and explains required keys.
  - Includes pytest scoping guidance (quick subset vs full suite).
work_orders:
  - "WO-1: Create/update docs/fast-dogfood.md with quickstart, env flags, and smoke command. [deps: none]"
  - "WO-2: Add a concise Operator Quickstart section to AGENTS.md linking to the doc and toy smoke plan. [deps: WO-1]"
  - "WO-3: Include the minimal frontmatter snippet (vcs/llm/telemetry) and describe fail-fast errors. [deps: WO-1]"
  - "WO-4: Add pytest scoping guidance (quick vs full) tied to plans. [deps: WO-1]"
  - "WO-5: Verify markdown formatting; no code changes outside docs. [deps: WO-1, WO-2, WO-3, WO-4]"
---

# OTEL Dogfood Docs Task

Goal: tighten operator docs to make Codex CLI dogfood runs one-shot and observable.
