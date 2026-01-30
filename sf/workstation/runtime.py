"""
Runtime provisioning (Python venv) for workstation commissioning.
"""

import os
import subprocess
from typing import Dict

from .fixtures.gitignore import ensure_gitignore


class RuntimeProvisionError(Exception):
    pass


def provision_python_venv(
    path: str,
    venv: str = ".venv",
    deps: str = "",
    pip_cache: str = ".pip-cache",
) -> None:
    """
    Create venv (if missing) and install deps.
    """
    venv_path = os.path.join(path, venv)
    cache_path = os.path.join(path, pip_cache)
    os.makedirs(cache_path, exist_ok=True)

    env = os.environ.copy()
    env["PIP_CACHE_DIR"] = cache_path

    def _run(cmd):
        subprocess.run(cmd, cwd=path, check=True, env=env, text=True)

    if not os.path.isdir(venv_path):
        _run(["python3", "-m", "venv", venv_path])

    if deps:
        _run([os.path.join(venv_path, "bin", "python"), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        _run([os.path.join(venv_path, "bin", "pip"), "install", "-q", deps])

    # Extend .gitignore with Python-specific entries
    ensure_gitignore(
        path,
        [
            venv.rstrip("/"),
            "__pycache__/",
            "*.pyc",
            pip_cache.rstrip("/"),
        ],
    )


def provision_runtime(path: str, runtime: Dict) -> None:
    template = runtime.get("template")
    if template == "python-venv":
        provision_python_venv(
            path,
            venv=runtime.get("venv", ".venv"),
            deps=runtime.get("deps", ""),
            pip_cache=runtime.get("pip_cache", ".pip-cache"),
        )
    else:
        raise RuntimeProvisionError(f"Unsupported runtime template: {template}")
