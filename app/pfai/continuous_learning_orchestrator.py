"""Continuous Learning Orchestrator — curated cycles + optional in-process worker.

Unifies curriculum, data acquisition/curation, the 24/7 training service, and the
human-gated learning loop into one coherent continuous-learning subsystem.

Invariants:
- Never fetches the open internet on its own.
- Evaluation-gated cycles (score required, LLM evaluator, or precision fallback).
- Promotion still goes through LearningLoop (human approve by default).
- Background worker runs real cycles when start() is called — not a status-only flag.
- Smart continuous focuses/seeds/scores; never auto-promotes model weights.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .learning_curriculum import LearningCurriculum
from .data_acquisition import DataAcquisitionEngine
from .learning_loop import LearningLoop
from .continuous_training import ContinuousTrainingService, ContinuousConfig
from .evaluation_lab import EvaluationLab
from .llm_evaluator import LLMEvaluator
from .self_training import SelfTrainingEngine
from .smart_continuous import SmartContinuousBrain, SmartContinuousConfig, smart_config_from_dict

log = logging.getLogger("pfai.continuous")


class ContinuousLearningOrchestrator:
    """Coordinates curriculum-weighted data curation with governed learning cycles."""

    def __init__(
        self,
        root="data/continuous_learning",
        curriculum: Optional[LearningCurriculum] = None,
        min_quality: float = 0.40,
        continuous_config: Optional[ContinuousConfig] = None,
        require_human_approval: bool = True,
        min_improvement: float = 0.01,
        min_score: float = 0.0,
        evaluator_model=None,
        self_training: bool = False,
        self_training_batch_size: int = 2,
        self_training_min_score: float = 0.80,
        max_curated_examples: int = 10000,
        smart_config: Optional[SmartContinuousConfig | dict] = None,
        open_mode: Optional[Callable[[], bool]] = None,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.curriculum = curriculum or LearningCurriculum()
        self.acquisition = DataAcquisitionEngine(self.curriculum, min_quality=min_quality)
        self.service = ContinuousTrainingService(
            str(self.root / "service"), continuous_config or ContinuousConfig()
        )
        self.loop = LearningLoop(
            str(self.root / "learning_registry.json"),
            min_improvement=min_improvement,
            min_score=min_score,
            require_human_approval=require_human_approval,
        )
        self.evaluator = EvaluationLab(min_score)
        self.llm_evaluator = LLMEvaluator(evaluator_model) if evaluator_model is not None else None
        self.sources_path = self.root / "curated_examples.jsonl"
        self.max_curated_examples = max(100, int(max_curated_examples))
        self.self_training = (
            SelfTrainingEngine(
                evaluator_model,
                str(self.root / "self_training"),
                batch_size=self_training_batch_size,
                min_teacher_score=self_training_min_score,
            )
            if self_training
            else None
        )
        base_iv = int((continuous_config or ContinuousConfig()).interval_seconds or 120)
        if isinstance(smart_config, SmartContinuousConfig):
            sc = smart_config
        else:
            sc = smart_config_from_dict(smart_config if isinstance(smart_config, dict) else None, base_interval=base_iv)
        self.smart = SmartContinuousBrain(sc, open_mode=open_mode)
        self._ingest_fn: Callable[[], list[dict]] | None = None
        self._worker: threading.Thread | None = None
        self._worker_stop = threading.Event()
        self._lock = threading.RLock()
        self._last_cycle_skipped = False
        self._push_experience_fn: Callable[[list[dict]], dict] | None = None

    def bind_experience_ingest(self, fn: Callable[[], list[dict]]) -> None:
        """Optional pull of accepted learning rows into the curated queue."""
        self._ingest_fn = fn

    def bind_experience_push(self, fn: Callable[[list[dict]], dict]) -> None:
        """Optional push of high-precision curated rows into longevity experience."""
        self._push_experience_fn = fn

    # -- data intake -----------------------------------------------------
    def register_batch(self, rows: Iterable[dict]) -> dict:
        curated = self.acquisition.curate(rows)
        rows = list(rows)
        if curated:
            with self.sources_path.open("a", encoding="utf-8") as f:
                for item in curated:
                    f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
            self._trim_jsonl(self.sources_path, self.max_curated_examples)
        return {
            "submitted": len(rows),
            "accepted": len(curated),
            "rejected": len(rows) - len(curated),
            "by_track": self._counts(curated),
            "curriculum_allocation": self.curriculum.allocate(len(curated)),
        }

    @staticmethod
    def _counts(items) -> dict:
        counts: dict = {}
        for it in items:
            counts[it.track] = counts.get(it.track, 0) + 1
        return counts

    @staticmethod
    def _trim_jsonl(path: Path, max_rows: int) -> None:
        if not path.exists():
            return
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) <= max_rows:
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines[-max_rows:]) + "\n", encoding="utf-8")
        tmp.replace(path)

    def pending_examples(self, limit: Optional[int] = None) -> list[dict]:
        if not self.sources_path.exists():
            return []
        max_rows = self.max_curated_examples if limit is None else max(1, min(int(limit), self.max_curated_examples))
        with self.sources_path.open("rb") as f:
            data = f.read()
        lines = [x for x in data.splitlines() if x.strip()]
        lines = lines[-max_rows:]
        items = []
        for raw in lines:
            try:
                items.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return items

    def _pull_experience(self) -> dict:
        if not self._ingest_fn:
            return {"pulled": 0}
        try:
            rows = self._ingest_fn() or []
        except Exception as exc:
            log.warning("experience ingest failed: %s", exc)
            return {"pulled": 0, "error": str(exc)}
        if not rows:
            return {"pulled": 0}
        mapped = []
        for r in rows:
            instr = (r.get("instruction") or r.get("input") or r.get("prompt") or "").strip()
            resp = (r.get("response") or r.get("output") or r.get("completion") or "").strip()
            if instr and resp:
                mapped.append({
                    "instruction": instr[:2000],
                    "response": resp[:4000],
                    "source": r.get("source") or r.get("attribution") or "experience_bridge",
                    "track": r.get("track") or "ai_engineering",
                    "metadata": {"via": "experience_ingest"},
                })
        if not mapped:
            return {"pulled": 0}
        result = self.register_batch(mapped)
        return {"pulled": len(mapped), **result}

    # -- governed learning cycle ------------------------------------------
    def run_cycle(self, version: str, score: Optional[float] = None, notes: str = "") -> dict:
        with self._lock:
            return self._run_cycle_locked(version, score=score, notes=notes)

    def _run_cycle_locked(self, version: str, score: Optional[float] = None, notes: str = "") -> dict:
        generated = {"generated": 0, "accepted": 0}
        track_names = [t.name for t in self.curriculum.tracks]
        track_weights = {t.name: t.weight for t in self.curriculum.tracks}

        # Smart prepare: focus analysis + seed when thin (no weight promote)
        prep = self.smart.prepare_cycle(
            self.pending_examples(),
            track_names=track_names,
            track_weights=track_weights,
            register_batch=self.register_batch,
        )
        focus_tracks = list(prep.get("focus_tracks") or track_names[:2])

        if self.self_training is not None and score is None:
            # High-focus teacher generation on gap tracks only
            gen_tracks = self.smart.focused_self_training_tracks(track_names) or focus_tracks
            generated = self.self_training.generate_batch(gen_tracks)
            examples = generated.get("examples") or []
            if examples:
                mapped = []
                for ex in examples:
                    mapped.append({
                        "instruction": ex.get("instruction", ""),
                        "response": ex.get("response", ""),
                        "source": ex.get("source") or "autonomous_teacher",
                        "track": (ex.get("metadata") or {}).get("track") or focus_tracks[0],
                        "metadata": {**(ex.get("metadata") or {}), "focus": True},
                    })
                self.register_batch(mapped)

        pending = self.pending_examples()
        dataset = self.smart.rank_for_focus(pending, focus_tracks) if pending else []
        if not dataset:
            self._last_cycle_skipped = True
            return {
                "evaluated": False,
                "skipped": True,
                "reason": "no curated data available for this cycle",
                "self_training": generated,
                "smart": prep,
            }

        auto_scored = False
        score_meta: dict[str, Any] = {}
        if score is None:
            llm_score = None
            llm_reason = ""
            if self.llm_evaluator:
                auto = self.llm_evaluator.score_examples(dataset)
                llm_score = auto.get("score")
                llm_reason = str(auto.get("reason") or "")
            score_meta = self.smart.resolve_score(
                dataset, llm_score=llm_score, llm_reason=llm_reason
            )
            score = float(score_meta["score"])
            auto_scored = True
            notes = (
                notes
                + f" [scored:{score_meta.get('method')}: {score_meta.get('reason', '')}]"
            ).strip()
            # Below threshold with no usable score → soft skip (not a hard failure)
            if score_meta.get("below_threshold") and score < self.smart.config.precision_min_score:
                self._last_cycle_skipped = True
                return {
                    "evaluated": False,
                    "skipped": True,
                    "reason": "precision below threshold for this cycle",
                    "self_training": generated,
                    "smart": {**prep, "score": score_meta},
                }

        proposal = self.loop.propose(version, dataset, lambda _rows: float(score), notes)
        self._last_cycle_skipped = False

        # Push high-precision accepted rows into longevity experience (growth path)
        push_out: dict[str, Any] = {}
        if (
            self._push_experience_fn
            and proposal.get("eligible")
            and proposal.get("status") in ("accepted", "pending_approval")
        ):
            try:
                push_out = self._push_experience_fn(dataset[:24]) or {}
            except Exception as exc:
                push_out = {"error": str(exc)}

        return {
            "evaluated": True,
            "auto_scored": auto_scored,
            "self_training": generated,
            "smart": {**prep, "score": score_meta, "focus_dataset": len(dataset), "experience_push": push_out},
            **proposal,
        }

    def auto_score(self, limit: Optional[int] = None) -> dict:
        if not self.llm_evaluator:
            return {"evaluated": False, "reason": "no evaluator model configured"}
        dataset = self.pending_examples(limit)
        if not dataset:
            return {"evaluated": False, "reason": "no curated data available"}
        return {"evaluated": True, **self.llm_evaluator.score_examples(dataset)}

    # -- background worker ------------------------------------------------
    def _worker_alive(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker_alive():
                return
            self._worker_stop.clear()
            t = threading.Thread(target=self._worker_loop, name="pfai-continuous-worker", daemon=True)
            self._worker = t
            t.start()
            log.info("continuous worker started interval=%s", self.service.config.interval_seconds)

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            st = self.service.status().get("status")
            if st == "paused":
                self.service.heartbeat()
                self._worker_stop.wait(max(5, int(self.service.config.heartbeat_seconds or 30)))
                continue
            if st not in ("running", "cycle"):
                break
            try:
                ingest = self._pull_experience()
                version = f"cl-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

                def _fn():
                    return self.run_cycle(version)

                result = self._run_service_cycle(_fn)
                log.info(
                    "continuous cycle done status=%s skipped=%s ingest=%s focus=%s",
                    result.get("status"),
                    result.get("skipped"),
                    ingest.get("pulled"),
                    ((result.get("smart") or {}).get("focus_tracks")),
                )
            except Exception as exc:
                log.warning("continuous worker cycle error: %s", exc)
            # Reload status — stop/pause may have happened during cycle
            if self.service.status().get("status") != "running":
                continue
            wait = self.smart.adaptive_interval(
                pending_count=len(self.pending_examples()),
                last_skipped=self._last_cycle_skipped,
            )
            self._worker_stop.wait(max(15, int(wait)))

    def _run_service_cycle(self, cycle_fn: Callable[[], dict]) -> dict:
        """Like ContinuousTrainingService.run_cycle but treats skipped/no-data as soft."""
        state = self.service.status()
        if state.get("status") not in ("running", "cycle"):
            return {"status": "skipped", "reason": state.get("status")}
        # Temporarily soften evaluation for empty-queue honesty
        result = cycle_fn() or {}
        if result.get("skipped") or result.get("evaluated") is not True:
            self.service.heartbeat()
            return {
                "status": "skipped",
                "skipped": True,
                "reason": result.get("reason") or "not evaluated",
                "self_training": result.get("self_training"),
            }
        return self.service.run_cycle(lambda: result)

    # -- service lifecycle ------------------------------------------------
    def start(self):
        st = self.service.start()
        self._ensure_worker()
        return {**st, "worker_alive": self._worker_alive(), "real_loop": True}

    def pause(self):
        return self.service.pause()

    def resume(self):
        st = self.service.resume()
        self._ensure_worker()
        return {**st, "worker_alive": self._worker_alive(), "real_loop": True}

    def stop(self, reason="operator"):
        self._worker_stop.set()
        return {**self.service.stop(reason), "worker_alive": False, "real_loop": False}

    def tick_once(self) -> dict[str, Any]:
        """Run one continuous cycle immediately (for chat/API). Does not promote."""
        if not self.service.status().get("status") == "running":
            self.service.start()
        self._ensure_worker()
        ingest = self._pull_experience()
        version = f"cl-tick-{uuid.uuid4().hex[:8]}"
        result = self._run_service_cycle(lambda: self.run_cycle(version))
        return {"ok": True, "ingest": ingest, "cycle": result, "status": self.status()}

    # -- learning-loop governance -----------------------------------------
    def approve(self, version: str) -> bool:
        return self.loop.approve(version)

    def reject(self, version: str) -> bool:
        return self.loop.reject(version)

    def promote(self, version: str) -> bool:
        return self.loop.promote(version)

    def rollback(self, version: Optional[str] = None) -> bool:
        return self.loop.rollback(version)

    # -- observability -----------------------------------------------------
    def status(self) -> dict:
        pending_n = len(self.pending_examples())
        return {
            "service": self.service.status(),
            "curriculum": self.curriculum.describe(),
            "pending_examples": pending_n,
            "active_candidate": self.loop.active(),
            "learning_history": self.loop.history()[-20:],
            "self_training": {
                "enabled": self.self_training is not None,
                "data_path": str(self.self_training.data_path) if self.self_training else None,
            },
            "smart": self.smart.status(),
            "adaptive_interval_seconds": self.smart.adaptive_interval(
                pending_count=pending_n,
                last_skipped=self._last_cycle_skipped,
            ),
            "worker_alive": self._worker_alive(),
            "real_loop": self._worker_alive() and self.service.status().get("status") in ("running", "cycle", "paused"),
            "auto_promote": False,
        }
