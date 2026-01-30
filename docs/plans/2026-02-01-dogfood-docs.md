---
workstation:
  vcs:
    type: git_worktree
    parent: /Users/allenday/src/agentproxy
    branch: feat/dogfood-docs
    path: .worktrees/feat-dogfood-docs
  runtime:
    python:
      version: "3.11"
      venv: .venv
  llm:
    provider: codex_cli
    flags: "--full-auto --sandbox workspace-write"
  telemetry:
    template: otel-compose-local
task: |
  Write and wire an "Operator Quickstart + Fast Dogfood" guide so new runs start fast with Codex CLI.
  Update AGENTS.md (root) and add a short doc under docs/ that:
    - Shows exact env/flags and the minimal working command (uses codex_cli, sandbox workspace-write, 240s timeout).
    - Provides a frontmatter snippet (vcs/llm/telemetry) and explains fail-fast errors.
    - References the 60-second smoke plan (2026-01-31-toy-fib.md) and how to scope pytest to a subset vs full suite.
acceptance:
  - Only docs are changed (AGENTS.md and new/updated docs files under docs/).
  - Quickstart includes copy-paste command known to work with codex_cli.
  - Frontmatter snippet is valid YAML and lists required keys.
  - Describes how to run quick smoke vs full test battery.
work_orders:
  - [WO-1] Add/update docs/fast-dogfood.md (or similar) with quickstart steps, env flags, and smoke command. [deps: none]
  - [WO-2] Insert a concise Operator Quickstart section into AGENTS.md linking to the doc and the toy smoke plan. [deps: WO-1]
  - [WO-3] Include the frontmatter template snippet (vcs/llm/telemetry) and explain fail-fast messages. [deps: WO-1]
  - [WO-4] Add guidance for pytest scoping (quick vs full) tied to plans. [deps: WO-1]
  - [WO-5] Verify markdown formatting; no code changes outside docs. [deps: WO-1, WO-2, WO-3, WO-4]
---

# OTEL Dogfood Docs Task

Goal: tighten operator docs to make Codex CLI dogfood runs one-shot and observable.
