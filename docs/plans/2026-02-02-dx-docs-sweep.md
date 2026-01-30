---
workstation:
  vcs:
    type: git_worktree
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
  Execute a DX doc sweep to make onboarding and dogfood frictionless with progressive disclosure.
  Improve root README.md, root AGENTS.md, and add concise AGENTS.md stubs in key subpackages.
acceptance:
  - README.md gains a “Fast path to dogfood” section with the validated Codex CLI command and link to fast-dogfood doc.
  - Root AGENTS.md expands with progressive-disclosure pointers and commissioning vs order vs traveler terminology.
  - New/updated AGENTS.md stubs in sf/, sf/shopfloor/, sf/workstation/, sf/llm/, sf/telemetry/ (or existing ones refreshed) describe purpose, main entry points, and where SOP/fixtures/telemetry live.
  - Commands are copy/pasteable and match the validated Codex CLI settings.
  - No code changes outside docs/ and AGENTS.md files.
work_orders:
  - "WO-1: Update README.md with Fast Path to Dogfood (validated codex_cli command + link to docs/fast-dogfood.md). [deps: none]"
  - "WO-2: Expand root AGENTS.md with progressive disclosure, terminology (order vs traveler), and quickstart pointer. [deps: WO-1]"
  - "WO-3: Add/refresh AGENTS.md stubs in sf/, sf/shopfloor/, sf/workstation/, sf/llm/, sf/telemetry/ describing roles/entry points/where docs live. [deps: WO-2]"
  - "WO-4: Cross-link fast-dogfood doc and smoke plan (2026-01-31-toy-fib.md) in relevant docs. [deps: WO-2]"
  - "WO-5: Verify markdown formatting; doc-only changes. [deps: WO-1, WO-2, WO-3, WO-4]"
---

# DX Docs Sweep – Progressive Disclosure & Fast Dogfood
