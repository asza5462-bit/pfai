"""PHASE 9 — local open-weight model discovery and selection (no silent downloads)."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Known non-production / random / internal testing markers
_TEST_ONLY_MARKERS = (
    "tiny-random",
    "hf-internal-testing",
    "test-only",
    "dummy",
)


@dataclass
class DiscoveredModel:
    path: str
    model_name: str
    status: str  # LOCAL_MODEL_AVAILABLE | MODEL_INCOMPATIBLE | MODEL_LOAD_ERROR | TEST_ONLY
    has_config: bool = False
    has_tokenizer: bool = False
    has_weights: bool = False
    license_meta: dict[str, Any] = field(default_factory=dict)
    revision_or_hash: str | None = None
    param_estimate: int | None = None
    is_test_only: bool = False
    load_ok: bool = False
    tokenizer_ok: bool = False
    inference_ok: bool = False
    context_length: int | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpenWeightModelSelector:
    """Discover and validate local HF-format models. Never downloads."""

    def __init__(self, search_roots: list[str | Path] | None = None) -> None:
        env_path = (os.environ.get("MODEL_PATH") or "").strip()
        defaults = [
            Path("data/models"),
            Path("app/data/models"),
            Path("data/longevity/models"),
        ]
        if env_path:
            defaults.insert(0, Path(env_path))
        self.search_roots = [Path(p) for p in (search_roots or defaults)]

    @staticmethod
    def hardware_audit() -> dict[str, Any]:
        report: dict[str, Any] = {
            "os": platform.platform(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
            "gpu_available": False,
            "cuda": False,
            "vram_gb": None,
            "cuda_version": None,
        }
        try:
            import psutil

            vm = psutil.virtual_memory()
            report["ram_gb"] = round(vm.total / (1024**3), 2)
            report["ram_available_gb"] = round(vm.available / (1024**3), 2)
        except Exception:
            report["ram_gb"] = None
            report["ram_available_gb"] = None
        try:
            report["disk_free_gb"] = round(shutil.disk_usage(".").free / (1024**3), 2)
        except Exception:
            report["disk_free_gb"] = None
        modules: dict[str, Any] = {}
        for name in (
            "torch",
            "transformers",
            "peft",
            "trl",
            "datasets",
            "accelerate",
            "safetensors",
            "bitsandbytes",
        ):
            try:
                mod = __import__(name)
                modules[name] = {"ok": True, "version": getattr(mod, "__version__", None)}
            except Exception as exc:
                modules[name] = {"ok": False, "error": type(exc).__name__}
        report["modules"] = modules
        if modules.get("torch", {}).get("ok"):
            import torch

            report["torch_version"] = torch.__version__
            report["cuda"] = bool(torch.cuda.is_available())
            report["cuda_version"] = getattr(torch.version, "cuda", None)
            report["gpu_available"] = report["cuda"]
            if report["cuda"]:
                try:
                    report["gpu_name"] = torch.cuda.get_device_name(0)
                    report["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
                except Exception as exc:
                    report["gpu_error"] = type(exc).__name__
            else:
                report["vram_gb"] = None
        report["cpu_training_supported"] = bool(modules.get("torch", {}).get("ok"))
        report["recommended_strategy"] = (
            "cpu_lora_small_model"
            if not report["gpu_available"]
            else "gpu_lora_or_qlora"
        )
        return report

    def discover(self, *, probe_load: bool = False) -> list[DiscoveredModel]:
        found: list[DiscoveredModel] = []
        seen: set[str] = set()
        candidates: list[Path] = []
        for root in self.search_roots:
            if root.is_file():
                continue
            if root.is_dir() and (root / "config.json").exists():
                candidates.append(root)
            elif root.is_dir():
                for cfg in root.rglob("config.json"):
                    # skip adapter-only dirs without base config intent if under artifacts
                    parent = cfg.parent
                    if "checkpoint-" in parent.name and "adapter_config.json" in {
                        p.name for p in parent.iterdir() if p.is_file()
                    }:
                        continue
                    candidates.append(parent)
        for path in candidates:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(self.inspect(path, probe_load=probe_load))
        return found

    def inspect(self, path: str | Path, *, probe_load: bool = False) -> DiscoveredModel:
        p = Path(path)
        name = p.name
        dm = DiscoveredModel(path=str(p.resolve()) if p.exists() else str(p), model_name=name, status="MODEL_NOT_INSTALLED")
        if not p.exists():
            dm.errors.append("path_missing")
            dm.status = "MODEL_NOT_INSTALLED"
            return dm
        dm.has_config = (p / "config.json").exists()
        dm.has_tokenizer = (p / "tokenizer.json").exists() or (p / "tokenizer_config.json").exists() or (
            p / "vocab.json"
        ).exists()
        weight_files = list(p.glob("*.safetensors")) + list(p.glob("pytorch_model*.bin")) + list(
            p.glob("model.safetensors")
        )
        dm.has_weights = bool(weight_files)
        license_path = p / "LICENSE_META.json"
        if license_path.exists():
            try:
                dm.license_meta = json.loads(license_path.read_text(encoding="utf-8"))
            except Exception:
                dm.license_meta = {"error": "unreadable_license_meta"}
        else:
            dm.license_meta = {
                "declared_license": os.environ.get("MODEL_LICENSE") or "unverified",
                "note": "LICENSE_META.json missing — operator must verify license before production use",
            }
        # content hash over config + first weight file names/bytes head
        h = hashlib.sha256()
        try:
            if dm.has_config:
                h.update((p / "config.json").read_bytes())
            for wf in sorted(weight_files)[:3]:
                h.update(wf.name.encode())
                h.update(wf.read_bytes()[:65536])
            dm.revision_or_hash = h.hexdigest()[:16]
        except Exception as exc:
            dm.errors.append(f"hash:{type(exc).__name__}")

        lowered = str(p).lower() + " " + json.dumps(dm.license_meta).lower()
        dm.is_test_only = any(m in lowered for m in _TEST_ONLY_MARKERS) or (
            (dm.license_meta or {}).get("purpose") == "phase8_bounded_verification"
        )
        if dm.is_test_only:
            dm.notes.append("classified_as_test_only_not_production_open_weight")
            dm.status = "TEST_ONLY"
        elif not (dm.has_config and dm.has_tokenizer and dm.has_weights):
            dm.status = "MODEL_INCOMPATIBLE"
            dm.errors.append("missing_config_tokenizer_or_weights")
        else:
            dm.status = "LOCAL_MODEL_AVAILABLE"

        if probe_load and dm.status in ("LOCAL_MODEL_AVAILABLE", "TEST_ONLY"):
            self._probe_load(dm)
        return dm

    def _probe_load(self, dm: DiscoveredModel) -> None:
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch

            tok = AutoTokenizer.from_pretrained(dm.path)
            model = AutoModelForCausalLM.from_pretrained(dm.path)
            dm.tokenizer_ok = True
            dm.load_ok = True
            dm.param_estimate = int(sum(p.numel() for p in model.parameters()))
            dm.context_length = int(
                getattr(model.config, "n_positions", None)
                or getattr(model.config, "max_position_embeddings", None)
                or 0
            ) or None
            if tok.pad_token is None:
                tok.pad_token = tok.eos_token
            inputs = tok("Hello", return_tensors="pt")
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=4, do_sample=False)
            _ = tok.decode(out[0], skip_special_tokens=True)
            dm.inference_ok = True
            if dm.status == "LOCAL_MODEL_AVAILABLE":
                pass
            del model
        except Exception as exc:
            dm.load_ok = False
            dm.inference_ok = False
            dm.errors.append(f"load:{type(exc).__name__}:{exc}")
            if dm.status == "LOCAL_MODEL_AVAILABLE":
                dm.status = "MODEL_LOAD_ERROR"

    def select_production_candidate(
        self, *, probe_load: bool = True, allow_test_only: bool = False
    ) -> dict[str, Any]:
        """Pick best local real open-weight model; never silent-download."""
        hw = self.hardware_audit()
        models = self.discover(probe_load=probe_load)
        real = [m for m in models if m.status == "LOCAL_MODEL_AVAILABLE" and (allow_test_only or not m.is_test_only)]
        if probe_load:
            real = [m for m in real if m.load_ok and m.inference_ok]
        install_doc = {
            "status": "MODEL_NOT_INSTALLED",
            "command": (
                f"{sys.executable} -m pfai.longevity.autonomous_training.install_open_weight "
                "--model distilgpt2 --dest data/models/distilgpt2 --approve"
            ),
            "notes": [
                "No silent downloads. Operator must run the install command explicitly with --approve.",
                "Recommended CPU-compatible open-weight starter: distilgpt2 (~82M).",
                "Set MODEL_PATH to the installed directory after install.",
            ],
            "env": {
                "MODEL_PROVIDER": "local_open_weight",
                "MODEL_PATH": "data/models/distilgpt2",
                "MODEL_NAME": "distilgpt2",
                "MODEL_LICENSE": "apache-2.0",
            },
        }
        if not real:
            test_only = [m.to_dict() for m in models if m.is_test_only]
            return {
                "ok": False,
                "status": "MODEL_NOT_INSTALLED",
                "selected": None,
                "discovered": [m.to_dict() for m in models],
                "test_only_models": test_only,
                "hardware": hw,
                "install": install_doc,
                "reason": "no_local_production_open_weight_model",
            }
        # Prefer smaller models on CPU / low RAM
        def score(m: DiscoveredModel) -> tuple:
            params = m.param_estimate or 10**12
            ram = hw.get("ram_available_gb") or 0
            # penalize huge models on CPU
            fit = 0 if (not hw.get("gpu_available") and params > 400_000_000) else 1
            return (fit, -params if params < 300_000_000 else -params)

        real.sort(key=score, reverse=True)
        # Actually sort: fit first, then smaller params
        real.sort(key=lambda m: (0 if ((m.param_estimate or 0) > 400_000_000 and not hw.get("gpu_available")) else 1, -(m.param_estimate or 0)), reverse=True)
        # Prefer smaller: sort by param ascending among fit
        fit = [m for m in real if not (not hw.get("gpu_available") and (m.param_estimate or 0) > 400_000_000)]
        pool = fit or real
        pool.sort(key=lambda m: m.param_estimate or 10**12)
        chosen = pool[0]
        return {
            "ok": True,
            "status": "LOCAL_MODEL_AVAILABLE",
            "selected": chosen.to_dict(),
            "discovered": [m.to_dict() for m in models],
            "hardware": hw,
            "install": None,
        }
