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

REQUIRED_SECTIONS = ["workstation", "workstation.vcs", "workstation.runtime", "workstation.tooling", "workstation.telemetry", "workstation.llm"]

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
    Ensure required sections and required fields per vcs type.
    """
    for key in REQUIRED_SECTIONS:
        if _get(meta, key) is None:
            raise FrontmatterError(f"Missing required frontmatter section: {key}")

    vcs = _get(meta, "workstation.vcs") or {}
    vcs_type = vcs.get("type")
    if vcs_type not in {"git_repo", "git_worktree", "git_clone", "local"}:
        raise FrontmatterError("workstation.vcs.type must be one of git_repo, git_worktree, git_clone, local")
    if vcs_type == "git_worktree":
        for field in ("parent", "worktree", "branch"):
            if not vcs.get(field):
                raise FrontmatterError(f"workstation.vcs.{field} is required for git_worktree")
    if vcs_type == "git_clone" and not vcs.get("repo_url"):
        raise FrontmatterError("workstation.vcs.repo_url is required for git_clone")

    runtime = _get(meta, "workstation.runtime") or {}
    rt_template = runtime.get("template")
    if rt_template not in {"python-venv"}:
        raise FrontmatterError("workstation.runtime.template must be 'python-venv'")
    # deps and venv defaults can be applied later; no hard requirement here

    tooling = _get(meta, "workstation.tooling") or {}
    if not tooling.get("tests"):
        raise FrontmatterError("workstation.tooling.tests is required")

    telemetry = _get(meta, "workstation.telemetry") or {}
    if not telemetry.get("template"):
        raise FrontmatterError("workstation.telemetry.template is required")

    llm = _get(meta, "workstation.llm") or {}
    if not llm.get("template") and not llm.get("provider"):
        raise FrontmatterError("workstation.llm.template or workstation.llm.provider is required")


def expand_templates(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Expand runtime/telemetry/llm templates into concrete fields."""
    wm = dict(meta.get("workstation", {}))

    # Runtime
    runtime = dict(wm.get("runtime", {}))
    rt_template = runtime.get("template")
    if rt_template in DEFAULT_RUNTIME_TEMPLATE:
        defaults = DEFAULT_RUNTIME_TEMPLATE[rt_template]
        for k, v in defaults.items():
            runtime.setdefault(k, v)
    wm["runtime"] = runtime

    # Telemetry
    telemetry = dict(wm.get("telemetry", {}))
    t_template = telemetry.get("template")
    if t_template in DEFAULT_TELEMETRY_TEMPLATE:
        defaults = DEFAULT_TELEMETRY_TEMPLATE[t_template]
        for k, v in defaults.items():
            telemetry.setdefault(k, v)
    wm["telemetry"] = telemetry

    # LLM
    llm = dict(wm.get("llm", {}))
    l_template = llm.get("template")
    if l_template in DEFAULT_LLM_TEMPLATE:
        defaults = DEFAULT_LLM_TEMPLATE[l_template]
        for k, v in defaults.items():
            llm.setdefault(k, v)
    wm["llm"] = llm

    out = dict(meta)
    out["workstation"] = wm
    return out
