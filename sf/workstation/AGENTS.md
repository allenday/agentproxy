# sf/workstation/ — Execution Environment

Purpose: Provision isolated execution (fixtures), materialize SOPs, and run verification gates.

Main entry points:
- `create_workstation()` in `__init__.py`
- `Workstation` in `workstation.py`

Where to look:
- **Fixtures:** `fixtures/` (worktree, repo, clone, local)
- **SOP registry:** `sop.py`
- **Verification gates:** `quality_gate.py`
- **Telemetry:** `sf/telemetry.py` and `sf/event_processors/`

Isolated execution environment. HAS-A Fixture (VCS), HAS-A SOP (methodology), manages lifecycle.

## Ownership

```
Workstation
  ├── Fixture         VCS isolation (git worktree, local dir, clone)
  ├── SOP             methodology: CLAUDE.md, hooks, verification_commands
  ├── Capabilities    language, framework, tools
  └── Hooks[]         lifecycle: pre_commission, post_production, on_checkpoint
```

**SOP belongs to the Workstation, not the WorkOrder.** `spawn()` inherits SOP to children.

## Lifecycle

```
commission()    → fixture.setup() + sop.materialize(path)
produce         → Claude executes in working dir
checkpoint(msg) → fixture.checkpoint() → git commit
decommission()  → fixture.teardown() → remove worktree/branch
spawn(name)     → fork fixture + inherit SOP/capabilities/hooks
```

## Fixtures

| Class | Created by | Strategy |
|-------|-----------|----------|
| `LocalDirFixture` | `context_type="local"` | Plain directory |
| `GitRepoFixture` | `context_type="git"` | Existing repo |
| `GitWorktreeFixture` | `GitRepoFixture.fork()` | `git worktree add` |
| `GitCloneFixture` | `context_type="clone"` | Fresh `git clone` |

Fork chain: `GitRepoFixture.fork("wo-1")` → `GitWorktreeFixture` at `.sf-worktree-wo-1` on branch `sf/wo-1`.

## SOP Materialization

`sop.materialize(path)` writes during `commission()`:
- `{path}/CLAUDE.md` — Claude reads natively at `cwd=path`
- `{path}/.claude/settings.json` — hook enforcement

Built-in SOPs: `v0` (TDD + pytest + coverage), `hotfix`, `refactor`, `documentation`. Registry: `SOP_REGISTRY` in `sop.py`.

## Quality Gate

`VerificationGate.inspect()` resolves commands from `station.sop.verification_commands`. No SOP on station → no verification (auto-pass). Verification is purely SOP-driven — gate constructor commands are not used as fallback.

Cascading gates supported: ShopFloor can attach multiple `QualityGate` instances. Each runs in order; first failure triggers Kaizen rework.

## Factory

```python
create_workstation(working_dir, context_type="auto", repo_url="", sop_name="v0")
```

Auto-detects git. Looks up SOP from registry. Returns uncommissioned Workstation.
