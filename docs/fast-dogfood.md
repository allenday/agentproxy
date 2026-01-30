# Operator Quickstart + Fast Dogfood (Codex CLI)

Use this when you want a one-shot Codex CLI run that is fast, observable, and fail-fast on misconfig.

## 1) Minimal working command (Codex CLI + workspace-write + 240s)

```bash
SF_LLM_PROVIDER=codex_cli \
SF_CODEX_FLAGS="--full-auto --sandbox workspace-write" \
SF_CODEX_TIMEOUT=240 \
sf --context-type git_worktree \
  --workorder-type file \
  --workorder-content docs/plans/2026-01-31-toy-fib.md
```

Notes:
- `SF_LLM_PROVIDER=codex_cli` pins the provider to Codex CLI.
- `SF_CODEX_TIMEOUT=240` sets a 240-second wall timeout for the Codex CLI subprocess.
- `SF_CODEX_FLAGS` must include `--sandbox workspace-write` so the workstation can edit files.
- `--workorder-type file` reads the plan file and uses its frontmatter + body.

## 2) Required frontmatter keys (vcs / llm / telemetry)

Use this minimal valid YAML frontmatter template for plans (only required keys shown):

```yaml
---
workstation:
  vcs:
    type: git_worktree
    parent: /path/to/repo
  telemetry:
    template: otel-compose-local
  llm:
    provider: codex_cli
    flags: "--full-auto --sandbox workspace-write"
    timeout_seconds: 240
---
```

Notes:
- `worktree` and `branch` are auto-derived by the workstation when omitted.
- If you add extra fields, keep `vcs`, `llm`, and `telemetry` at the top level under `workstation`.

### Fail-fast errors to expect (and fix)

- Missing frontmatter: `Missing YAML frontmatter (--- ... ---) at top of plan.`
- Missing required section: `Missing required frontmatter section: workstation.<section>`
- Invalid VCS type or missing `git_worktree` fields (`parent` is required).
- Missing `workstation.telemetry.template` or `workstation.llm.provider`/`workstation.llm.flags`.
- Codex CLI missing from PATH: `codex CLI not found on PATH (or set CODEX_BIN)`.

## 3) 60-second smoke plan

The fast smoke plan lives here: `docs/plans/2026-01-31-toy-fib.md`.

It uses a tiny Fibonacci task to validate the end-to-end stack. Run it with the minimal command above.

## 4) Pytest scoping: quick vs full battery

- Quick smoke (single test file):
  ```bash
  PYTHONPATH=$(pwd) ./venv/bin/pytest -q tests/test_fib.py
  ```
- Narrow to a keyword or subset:
  ```bash
  PYTHONPATH=$(pwd) ./venv/bin/pytest -q -k fib
  ```
- Full suite (baseline in AGENTS.md):
  ```bash
  python -m pytest tests/ -q
  ```

Tie the scope to the plan: smoke runs for toy-fib should only run the fib tests; full suites are for before merge.
