"""In-process Transformers local open-weight provider (PHASE 9).

Loads from MODEL_PATH / local directory. Does not call the internet at inference time.
Optional PEFT adapter from ActiveModelRuntime checkpoint.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from pfai.model import ModelProvider


class TransformersLocalProvider(ModelProvider):
    """Causal LM via local transformers weights (+ optional LoRA adapter)."""

    kind = "transformers_local"

    def __init__(
        self,
        *,
        model_path: str | None = None,
        adapter_path: str | None = None,
        max_new_tokens: int = 64,
        temperature: float = 0.2,
        context_length: int = 512,
        device: str | None = None,
    ) -> None:
        self.model_path = (
            model_path
            or os.environ.get("MODEL_PATH")
            or os.environ.get("PFAI_MODEL_PATH")
            or ""
        ).strip()
        self.adapter_path = adapter_path
        self.max_new_tokens = int(max_new_tokens)
        self.temperature = float(temperature)
        self.context_length = int(context_length)
        self.device = device
        self._lock = threading.RLock()
        self._model = None
        self._tokenizer = None
        self._loaded_from: dict[str, Any] = {}
        self._last_error: str | None = None

    def status(self) -> dict[str, Any]:
        p = Path(self.model_path) if self.model_path else None
        available = bool(p and p.exists() and (p / "config.json").exists())
        return {
            "adapter": self.__class__.__name__,
            "kind": self.kind,
            "model_path": self.model_path or None,
            "adapter_path": self.adapter_path,
            "MODEL_AVAILABLE": available,
            "MODEL_LOADABLE": available and self._last_error is None,
            "MODEL_ACTIVE": self._model is not None,
            "loaded": self._model is not None,
            "loaded_from": dict(self._loaded_from),
            "error": self._last_error,
            "device": self.device or ("cuda" if self._cuda() else "cpu"),
            "GPU_AVAILABLE": self._cuda(),
        }

    @staticmethod
    def _cuda() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def ensure_loaded(self) -> dict[str, Any]:
        with self._lock:
            if self._model is not None:
                return {"ok": True, "cached": True, **self.status()}
            if not self.model_path or not Path(self.model_path).exists():
                self._last_error = "MODEL_NOT_INSTALLED"
                return {"ok": False, "status": "MODEL_NOT_INSTALLED", **self.status()}
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer

                device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
                self.device = device
                tok = AutoTokenizer.from_pretrained(self.model_path)
                model = AutoModelForCausalLM.from_pretrained(self.model_path)
                if tok.pad_token is None:
                    tok.pad_token = tok.eos_token
                if self.adapter_path and Path(self.adapter_path).exists():
                    from peft import PeftModel

                    model = PeftModel.from_pretrained(model, self.adapter_path)
                model.to(device)
                model.eval()
                self._tokenizer = tok
                self._model = model
                self._loaded_from = {
                    "base": self.model_path,
                    "adapter": self.adapter_path,
                    "device": device,
                }
                self._last_error = None
                return {"ok": True, "cached": False, **self.status()}
            except Exception as exc:
                self._last_error = f"MODEL_LOAD_ERROR:{type(exc).__name__}:{exc}"
                self._model = None
                self._tokenizer = None
                return {"ok": False, "status": "MODEL_LOAD_ERROR", "error": self._last_error, **self.status()}

    def generate(self, prompt: str, **kwargs: Any) -> str:
        loaded = self.ensure_loaded()
        if not loaded.get("ok"):
            return f"[MODEL_UNAVAILABLE:{loaded.get('status') or loaded.get('error')}]"
        import torch

        max_new = int(kwargs.get("max_tokens") or kwargs.get("max_new_tokens") or self.max_new_tokens)
        temperature = float(kwargs.get("temperature", self.temperature))
        with self._lock:
            assert self._model is not None and self._tokenizer is not None
            inputs = self._tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=min(self.context_length, 1024),
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            gen_kwargs: dict[str, Any] = {
                "max_new_tokens": max_new,
                "do_sample": temperature > 0,
            }
            if temperature > 0:
                gen_kwargs["temperature"] = max(0.01, temperature)
            with torch.no_grad():
                out = self._model.generate(**inputs, **gen_kwargs)
            text = self._tokenizer.decode(out[0], skip_special_tokens=True)
            # Prefer continuation after prompt when present
            if text.startswith(prompt):
                return text[len(prompt) :].strip() or text.strip()
            return text.strip()

    def bind_adapter(self, adapter_path: str | None) -> dict[str, Any]:
        """Hot-swap LoRA adapter from ActiveModelRuntime; forces reload."""
        with self._lock:
            self.adapter_path = adapter_path
            self._model = None
            self._tokenizer = None
        return self.ensure_loaded()
