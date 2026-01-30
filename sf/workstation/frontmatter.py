"""
Frontmatter parsing and validation for workstation specs.

Expected YAML frontmatter shape:

---
workstation:
  vcs:
    type: git_worktree   # git_repo | git_worktree | git_clone | local
    parent: /path/to/repo          # required for git_worktree/git_clone
    worktree: .worktrees/feat-x    # required for git_worktree
    branch: feat-x                 # required for git_worktree
    repo_url: https://...          # required for git_clone
  runtime:
    template: python-venv
    venv: .venv
    deps: ".[all]"
    pip_cache: .pip-cache
  tooling:
    tests: "python -m pytest -q"
  telemetry:
    template: loki-default         # resolved by runtime/telemetry provisioner
  llm:
    template: codex_cli_default    # resolved separately
---
<plan body>
"""

import re
from typing import Dict, Any, Tuple

try:
    import yaml
except ImportError as e:
    yaml = None

RE_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

REQUIRED_SECTIONS = ["workstation", "workstation.vcs"]

DEFAULT_RUNTIME_TEMPLATE = {
    "python-venv": {
        "venv": ".venv",
        "deps": ".[all]",
        "pip_cache": ".pip-cache",
    }
}

DEFAULT_TELEMETRY_TEMPLATE = {
    "loki-default": {
        "env": {
            "SF_LOKI_ENABLED": "true",
            "SF_LOKI_ENDPOINT": "http://localhost:3100",
            "SF_LOKI_LABELS": "service=sf,component=worker",
            "SF_LOKI_TIMEOUT_S": "5",
        }
    },
    "otel-compose-local": {
        "env": {
            "SF_ENABLE_TELEMETRY": "1",
            "SF_TELEMETRY_VERBOSE": "1",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4317",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://localhost:4317",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            "OTEL_SERVICE_NAME": "sf",
            "OTEL_RESOURCE_ATTRIBUTES": "service.name=sf,service.namespace=allenday.sf,service.instance.id=dogfood",
        }
    },
    "none": {"env": {}},
}

DEFAULT_LLM_TEMPLATE = {
    "codex_cli_default": {"provider": "codex_cli"},
    "claude_cli_default": {"provider": "claude_cli"},
}


class FrontmatterError(ValueError):
    pass


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """
    Parse YAML frontmatter from the top of a plan string.

    Returns (meta, body). If no frontmatter is found, raises FrontmatterError.
    """
    if yaml is None:
        raise FrontmatterError("PyYAML is required for frontmatter parsing; install pyyaml.")
    match = RE_FRONTMATTER.match(text)
    if not match:
        raise FrontmatterError("Missing YAML frontmatter (--- ... ---) at top of plan.")
    raw = match.group(1)
    try:
        meta = yaml.safe_load(raw) or {}
    except Exception as e:
        raise FrontmatterError(f"Invalid YAML frontmatter: {e}")
    body = text[match.end():]
    return meta, body


def _get(meta: Dict[str, Any], path: str) -> Any:
    cur = meta
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def validate_frontmatter(meta: Dict[str, Any]) -> None:
    """
    External/user validation: minimal required fields only.
    """
    for key in REQUIRED_SECTIONS:
        if _get(meta, key) is None:
            raise FrontmatterError(f"Missing required frontmatter section: {key}")

    vcs = _get(meta, "workstation.vcs") or {}
    vcs_type = vcs.get("type")
    if vcs_type not in {"git_repo", "git_worktree", "git_clone", "local"}:
        raise FrontmatterError("workstation.vcs.type must be one of git_repo, git_worktree, git_clone, local")
    if vcs_type == "git_worktree":
        # parent/worktree/branch may be auto-inferred; no hard requirement
        if not vcs.get("parent"):
            # parent can be inferred from cwd; allow omission
            pass
    if vcs_type == "git_clone" and not vcs.get("repo_url"):
        raise FrontmatterError("workstation.vcs.repo_url is required for git_clone")
    # runtime/tooling/telemetry/llm are optional; defaults applied in expand_templates


def validate_internal(meta: Dict[str, Any]) -> None:
    """
    Internal validation after defaults are applied (strict).
    Ensures all workstation sub-sections are present and usable.
    """
    if _get(meta, "workstation") is None:
        raise FrontmatterError("Missing workstation block after expansion")

    vcs = _get(meta, "workstation.vcs") or {}
    vcs_type = vcs.get("type")
    if vcs_type not in {"git_repo", "git_worktree", "git_clone", "local"}:
        raise FrontmatterError("workstation.vcs.type must be one of git_repo, git_worktree, git_clone, local")
    if vcs_type == "git_clone" and not vcs.get("repo_url"):
        raise FrontmatterError("workstation.vcs.repo_url is required for git_clone")

    runtime = _get(meta, "workstation.runtime") or {}
    if not runtime.get("venv"):
        raise FrontmatterError("workstation.runtime.venv is required after expansion")

    telemetry = _get(meta, "workstation.telemetry") or {}
    if "env" not in telemetry:
        raise FrontmatterError("workstation.telemetry.env is required after expansion")

    llm = _get(meta, "workstation.llm") or {}
    if not llm.get("provider"):
        raise FrontmatterError("workstation.llm.provider is required after expansion")

    tooling = _get(meta, "workstation.tooling")
    if tooling is None:
        raise FrontmatterError("workstation.tooling must be a mapping after expansion")


def expand_templates(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Expand runtime/telemetry/llm templates into concrete fields."""
    wm = dict(meta.get("workstation", {}))

    # Runtime
    runtime = dict(wm.get("runtime", {})) or {"template": "python-venv"}
    rt_template = runtime.get("template", "python-venv")
    if rt_template in DEFAULT_RUNTIME_TEMPLATE:
        defaults = DEFAULT_RUNTIME_TEMPLATE[rt_template]
        for k, v in defaults.items():
            runtime.setdefault(k, v)
    wm["runtime"] = runtime

    # Telemetry
    telemetry = dict(wm.get("telemetry", {})) or {"template": "none"}
    t_template = telemetry.get("template", "none")
    if t_template in DEFAULT_TELEMETRY_TEMPLATE:
        defaults = DEFAULT_TELEMETRY_TEMPLATE[t_template]
        for k, v in defaults.items():
            telemetry.setdefault(k, v)
    wm["telemetry"] = telemetry

    # LLM
    llm = dict(wm.get("llm", {}))
    if not llm:
        llm = {"template": "codex_cli_default"}
    l_template = llm.get("template")
    if l_template in DEFAULT_LLM_TEMPLATE:
        defaults = DEFAULT_LLM_TEMPLATE[l_template]
        for k, v in defaults.items():
            llm.setdefault(k, v)
    wm["llm"] = llm

    # Tooling defaults to empty dict
    tooling = dict(wm.get("tooling", {}))
    wm["tooling"] = tooling

    out = dict(meta)
    out["workstation"] = wm
    return out
