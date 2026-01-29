"""
Standard Operating Procedures (SOP)
====================================

In manufacturing, an SOP is a documented procedure attached to a workstation.
It defines the methodology the worker follows. Different workstations can have
different SOPs.

The base worker agent is Claude. Therefore, the SOP manifests concretely as
Claude sub-agent hooks:
  - CLAUDE.md (methodology instructions Claude reads natively)
  - .claude/settings.json (tool hooks for enforcement)

These are written during workstation commission and cleaned up during decommission.
"""

import json
import os
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ClaudeHook(BaseModel):
    """A Claude Code hook (PreToolUse, PostToolUse, etc.)."""

    event: str  # "PreToolUse", "PostToolUse", "PreCommit"
    matcher: str = "*"  # Tool name matcher ("Bash", "Write", "*")
    command: str  # Shell command to execute


class SOP(BaseModel):
    """Standard Operating Procedure attached to a Workstation.

    Materialized as Claude sub-agent hooks during workstation commission:
    1. CLAUDE.md written to workstation path (Claude reads natively)
    2. .claude/settings.json hooks written for enforcement
    3. Quality gate verification commands enforced post-production
    """

    name: str  # "v0", "hotfix", "refactor", "documentation"

    # Methodology (becomes CLAUDE.md content)
    claude_md: str  # Full CLAUDE.md content

    # Claude hooks (becomes .claude/settings.json)
    hooks: List[ClaudeHook] = Field(default_factory=list)

    # Quality gate verification (enforced post-production by VerificationGate)
    verification_commands: List[str] = Field(default_factory=list)

    # Pre-conditions (checked during commission before CLAUDE.md is written)
    pre_conditions: List[str] = Field(default_factory=list)

    def materialize(self, path: str) -> None:
        """Write SOP artifacts to a workstation path.

        Writes:
          - {path}/CLAUDE.md: Claude reads this natively when spawned with cwd=path
          - {path}/.claude/settings.json: Claude hook configuration
          - {path}/.env.sop: helper to set PYTHONPATH for pytest/imports

        Args:
            path: Absolute path to the workstation working directory.
        """
        # Write CLAUDE.md
        claude_md_path = os.path.join(path, "CLAUDE.md")
        with open(claude_md_path, "w") as f:
            f.write(self.claude_md)

        # Write .claude/settings.json if hooks are defined
        if self.hooks:
            claude_dir = os.path.join(path, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            settings_path = os.path.join(claude_dir, "settings.json")

            # Build settings structure
            hooks_config: Dict[str, list] = {}
            for hook in self.hooks:
                key = hook.event
                if key not in hooks_config:
                    hooks_config[key] = []
                hooks_config[key].append({
                    "matcher": hook.matcher,
                    "command": hook.command,
                })

            settings = {"hooks": hooks_config}
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)

        # Write PYTHONPATH helper
        env_path = os.path.join(path, ".env.sop")
        with open(env_path, "w") as f:
            f.write("PYTHONPATH=$(pwd):$(pwd)/src\n")

    def run_pre_conditions(self, path: str) -> List[str]:
        """Run pre-condition commands on the workstation path.

        Args:
            path: Workstation working directory.

        Returns:
            List of error messages (empty if all passed).
        """
        import os
        import subprocess

        if os.getenv("SF_SKIP_SOP_PRECONDITIONS", "0") == "1":
            return []

        errors: List[str] = []
        for cmd in self.pre_conditions:
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    errors.append(
                        f"Pre-condition failed: {cmd}\n"
                        f"stderr: {result.stderr[:200]}"
                    )
            except Exception as e:
                errors.append(f"Pre-condition error: {cmd} -- {e}")
        return errors


# =============================================================================
# Built-in SOPs
# =============================================================================

SOP_V0 = SOP(
    name="v0",
    claude_md="""\
# Software Factory v0 SOP

## Methodology: Test-Driven Development
1. Write failing tests FIRST that define the expected behavior
2. Run tests to confirm they fail
3. Implement the minimum code to make tests pass
4. Refactor while keeping tests green
5. Never commit code without passing tests

## Data Models
- Use Pydantic BaseModel for ALL data models (not dataclass)
- Validate inputs at system boundaries
- Use Field() for defaults and descriptions

## Code Standards
- Python 3.9+ type hints on all function signatures
- Module docstrings explaining purpose
- snake_case functions, PascalCase classes, UPPER_SNAKE constants
- Max 30 lines per function, max 3 nesting levels
- Prefer stdlib over third-party when equivalent

## Error Handling
- No bare except clauses
- All external calls (network, file I/O, subprocess) must be wrapped
- Telemetry should never break the app (silent fail OK for OTEL)
""",
    hooks=[
        ClaudeHook(
            event="PreToolUse",
            matcher="Bash",
            command="echo 'SOP: Bash tool invoked'",
        ),
        ClaudeHook(
            event="PostToolUse",
            matcher="Write",
            command="python -m py_compile {file_path} 2>/dev/null || true",
        ),
    ],
    verification_commands=[
        "PYTHONPATH=$(pwd):$(pwd)/src python -m pytest --tb=short",
        "PYTHONPATH=$(pwd):$(pwd)/src python -m pytest --cov --cov-fail-under=70",
        "python -m py_compile $(find . -name '*.py' -not -path './.git/*' | head -50)",
    ],
    pre_conditions=[
        "test -d tests || mkdir tests",
        "python -m pip install -q --upgrade pip",
        "python -m pip show pydantic >/dev/null 2>&1 || python -m pip install -q pydantic",
        "python -m pip show pytest >/dev/null 2>&1 || python -m pip install -q pytest",
    ],
)


SOP_HOTFIX = SOP(
    name="hotfix",
    claude_md="""\
# Hotfix SOP

## Emergency Fix Procedure
1. Identify the root cause from the error/incident description
2. Write a minimal, targeted fix (NO refactoring)
3. Add a regression test for the specific failure
4. Verify the fix resolves the original issue

## Constraints
- Touch ONLY the files necessary to fix the issue
- Do NOT refactor surrounding code
- Do NOT add features
- Regression test is MANDATORY
""",
    hooks=[],
    verification_commands=[
        "python -m pytest --tb=short -x",
    ],
)


SOP_REFACTOR = SOP(
    name="refactor",
    claude_md="""\
# Refactor SOP

## Refactoring Procedure
1. Ensure full test coverage exists for the code being refactored
2. Run tests to confirm all pass (green baseline)
3. Apply refactoring transformations incrementally
4. Run tests after each transformation
5. Commit after each successful transformation

## Constraints
- Do NOT change behavior (tests must stay green throughout)
- Do NOT add new features during refactoring
- Each commit should be a single, named refactoring (e.g., "Extract Method", "Rename Variable")
""",
    hooks=[],
    verification_commands=[
        "python -m pytest --tb=short",
    ],
)


SOP_DOCUMENTATION = SOP(
    name="documentation",
    claude_md="""\
# Documentation SOP

## Documentation Procedure
1. Read the code being documented
2. Write docstrings for all public functions, classes, and modules
3. Create or update README.md with usage examples
4. Add inline comments only where logic is non-obvious

## Constraints
- Do NOT modify any code logic
- Docstrings follow Google style (Args, Returns, Raises)
- Examples must be runnable
""",
    hooks=[],
    verification_commands=[
        "python -m py_compile $(find . -name '*.py' -not -path './.git/*' | head -50)",
    ],
)


# =============================================================================
# SOP Registry
# =============================================================================

SOP_REGISTRY: Dict[str, SOP] = {
    "v0": SOP_V0,
    "hotfix": SOP_HOTFIX,
    "refactor": SOP_REFACTOR,
    "documentation": SOP_DOCUMENTATION,
}


def get_sop(name: str) -> Optional[SOP]:
    """Look up an SOP by name from the registry.

    Args:
        name: SOP name (e.g., "v0", "hotfix").

    Returns:
        SOP instance or None if not found.
    """
    return SOP_REGISTRY.get(name)


def register_sop(sop: SOP) -> None:
    """Register a custom SOP in the global registry.

    Args:
        sop: SOP instance to register.
    """
    SOP_REGISTRY[sop.name] = sop
