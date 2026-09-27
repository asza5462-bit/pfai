"""Explicit open-weight model installer — NEVER runs without --approve.

Usage:
  python -m pfai.longevity.autonomous_training.install_open_weight \\
    --model distilgpt2 --dest data/models/distilgpt2 --approve
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


DEFAULT_MODELS = {
    "distilgpt2": {
        "hub_id": "distilgpt2",
        "license": "apache-2.0",
        "approx_params": "82M",
        "notes": "Small distilled GPT-2; CPU-compatible starter for LoRA verification.",
    },
    "gpt2": {
        "hub_id": "gpt2",
        "license": "mit",
        "approx_params": "124M",
        "notes": "Classic GPT-2 small; higher RAM than distilgpt2.",
    },
}


def install(*, model_key: str, dest: str, approve: bool, revision: str | None = None) -> dict:
    if not approve:
        return {
            "ok": False,
            "status": "APPROVAL_REQUIRED",
            "error": "Refusing to download without --approve (no silent downloads).",
            "hint": "Re-run with --approve after reviewing license and disk/RAM budget.",
        }
    meta = DEFAULT_MODELS.get(model_key) or {
        "hub_id": model_key,
        "license": "unverified",
        "approx_params": "unknown",
        "notes": "Custom hub id — operator must verify license.",
    }
    hub_id = meta["hub_id"]
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as exc:
        return {"ok": False, "status": "TRAINING_RUNTIME_UNAVAILABLE", "error": str(exc)}

    load_kw = {}
    if revision:
        load_kw["revision"] = revision
    print(f"[install_open_weight] APPROVED download hub_id={hub_id} -> {out}", flush=True)
    tok = AutoTokenizer.from_pretrained(hub_id, **load_kw)
    model = AutoModelForCausalLM.from_pretrained(hub_id, **load_kw)
    tok.save_pretrained(out)
    model.save_pretrained(out)
    license_meta = {
        "model": hub_id,
        "license": meta.get("license") or "unverified",
        "approx_params": meta.get("approx_params"),
        "purpose": "phase9_real_open_weight",
        "source": "huggingface_hub_explicit_approve",
        "revision": revision,
        "notes": meta.get("notes"),
        "operator_approved": True,
    }
    (out / "LICENSE_META.json").write_text(json.dumps(license_meta, indent=2), encoding="utf-8")
    # quick sanity
    assert (out / "config.json").exists()
    files = sorted(p.name for p in out.iterdir())
    return {
        "ok": True,
        "status": "LOCAL_MODEL_AVAILABLE",
        "path": str(out.resolve()),
        "hub_id": hub_id,
        "license_meta": license_meta,
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Explicit open-weight model installer (requires --approve)")
    p.add_argument("--model", default="distilgpt2", help="Model key or hub id")
    p.add_argument("--dest", default="data/models/distilgpt2")
    p.add_argument("--revision", default=None)
    p.add_argument("--approve", action="store_true", help="Required — acknowledges network download")
    args = p.parse_args(argv)
    result = install(model_key=args.model, dest=args.dest, approve=args.approve, revision=args.revision)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
