"""
ShopFloor End-to-End Integration Test (Live, Gated)
=====================================================

Full pipeline: real Gemini decomposition, real Claude execution,
real git worktrees. Requires GEMINI_API_KEY and claude binary.

Skipped when prerequisites are not available.
"""

import os
import shutil
import subprocess
import tempfile

import pytest

from sf.models import EventType

# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CLAUDE_BIN = shutil.which("claude")

if not GEMINI_API_KEY:
    pytest.skip("GEMINI_API_KEY not set", allow_module_level=True)
if not CLAUDE_BIN:
    pytest.skip("claude binary not found", allow_module_level=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fib_project():
    """Module-scoped temp dir with a minimal fibonacci project scaffold."""
    project_dir = tempfile.mkdtemp(prefix="sf-e2e-fib-")

    src_dir = os.path.join(project_dir, "src", "fibonacci")
    tests_dir = os.path.join(project_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(tests_dir, exist_ok=True)

    with open(os.path.join(project_dir, "pyproject.toml"), "w") as f:
        f.write(
            "[project]\n"
            'name = "fibonacci"\n'
            'version = "0.1.0"\n'
            "\n"
            "[build-system]\n"
            'requires = ["setuptools"]\n'
            'build-backend = "setuptools.backends._legacy:_Backend"\n'
            "\n"
            "[tool.setuptools.packages.find]\n"
            'where = ["src"]\n'
        )

    with open(os.path.join(src_dir, "__init__.py"), "w") as f:
        f.write("")

    with open(os.path.join(tests_dir, "__init__.py"), "w") as f:
        f.write("")

    subprocess.run(
        ["git", "init"], cwd=project_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "E2E Test"],
        cwd=project_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "e2e@test.com"],
        cwd=project_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=project_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "scaffold"],
        cwd=project_dir, capture_output=True, check=True,
    )

    yield project_dir

    shutil.rmtree(project_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_shopfloor_fib_pipeline(fib_project):
    """Full ShopFloor pipeline: Gemini decomposition -> Claude execution."""
    from sf.pa import PA

    pa = PA(
        working_dir=fib_project,
        use_shopfloor=True,
        sop_name="v0",
        context_type="git",
    )
    events = list(pa.run_task(
        "Create a Python fibonacci function with iterative and "
        "recursive implementations and tests",
        max_iterations=50,
    ))

    # If Claude is not authenticated, gracefully xfail to unblock pipelines
    if any("Invalid API key" in (e.content or "") for e in events):
        pytest.xfail("Claude not authenticated for headless run (Invalid API key)")

    # --- Diagnostics (printed on failure via assertion messages) ---

    all_py_files = []
    for root, _dirs, files in os.walk(fib_project):
        # Skip .git internals and __pycache__
        rel = os.path.relpath(root, fib_project)
        if rel.startswith(".git") or "__pycache__" in rel:
            continue
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                all_py_files.append(os.path.relpath(
                    os.path.join(root, f), fib_project,
                ))

    log_output = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=fib_project,
        capture_output=True,
        text=True,
    )
    commits = [l for l in log_output.stdout.strip().split("\n") if l]

    # Build a diagnostic summary for assertion messages
    event_summary = []
    for e in events[-40:]:
        src = e.metadata.get("source", "?")
        event_summary.append(
            f"  [{e.event_type.name:12s}] src={src:12s} | "
            f"{e.content[:120]}"
        )
    diag = (
        f"\n=== DIAGNOSTIC ===\n"
        f"Events: {len(events)} total\n"
        f"Py files: {all_py_files}\n"
        f"Commits: {commits}\n"
        f"Last 40 events:\n" + "\n".join(event_summary) + "\n"
    )

    # --- Assertions ---

    # 1. Events contain ShopFloor markers
    shopfloor_events = [
        e for e in events if e.metadata.get("source") == "shopfloor"
    ]
    assert len(shopfloor_events) > 0, f"No events with source='shopfloor'{diag}"

    # 2. BOM parsed
    all_content = " ".join(e.content for e in events)
    assert "Bill of Materials" in all_content, (
        f"Expected 'Bill of Materials' in event stream{diag}"
    )

    # 3. Layers routed
    assert "Layer" in all_content, f"Expected 'Layer' in event stream{diag}"

    # 4. Python source files created (Claude decides exact layout)
    assert len(all_py_files) > 0, (
        f"Expected .py files beyond __init__.py somewhere in {fib_project}{diag}"
    )

    # 5. Test files exist (search recursively — Claude may nest them)
    test_files = [f for f in all_py_files if os.path.basename(f).startswith("test_")]
    assert len(test_files) > 0, (
        f"Expected test_*.py files somewhere in {fib_project}{diag}"
    )

    # 6. Git commits beyond the initial scaffold
    assert len(commits) > 1, (
        f"Expected more than 1 commit, got {len(commits)}: {commits}{diag}"
    )

    # 7. Final event is COMPLETED
    assert events[-1].event_type == EventType.COMPLETED, (
        f"Expected last event to be COMPLETED, got {events[-1].event_type}{diag}"
    )
