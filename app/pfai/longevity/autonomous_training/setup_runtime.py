"""PHASE 8 setup helper — deterministic install path for real training deps.

Does not auto-run unless invoked. Never installs unrelated packages.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REQUIRED = (
    "torch",
    "transformers",
    "peft",
    "datasets",
    "accelerate",
    "safetensors",
    "trl",
)


def missing_modules() -> list[str]:
    missing = []
    for name in REQUIRED:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    return missing


def install_training_runtime(*, extra_index: str | None = None) -> dict:
    """Install requirements-training.txt into the current environment."""
    req = Path(__file__).resolve().parents[2] / "requirements-training.txt"
    if not req.exists():
        # fallback: app/requirements-training.txt relative to package
        req = Path(__file__).resolve().parents[3] / "requirements-training.txt"
    if not req.exists():
        return {"ok": False, "error": "requirements-training.txt_not_found", "path": str(req)}
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req)]
    # CPU torch wheels are on the default PyPI for many platforms; optional extra index.
    if extra_index:
        cmd.extend(["--extra-index-url", extra_index])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "missing_after": missing_modules(),
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
        "requirements": str(req),
    }


if __name__ == "__main__":
    before = missing_modules()
    print({"missing_before": before})
    if before:
        result = install_training_runtime()
        print(result)
    else:
        print({"ok": True, "note": "all required modules already importable"})
