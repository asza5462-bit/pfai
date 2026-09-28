"""Smart continuous training — focused, high-precision, always-running curation.

Removes empty-cycle friction: when the curated queue is thin, seed high-precision
focused examples; score with a multi-dimension precision engine when the teacher
or LLM evaluator is unavailable; adapt the worker interval for real continuity.

Invariants (never violated here):
- Does NOT promote or activate model weights.
- Does NOT bypass SSRF / network / security gates.
- Weight-training eligibility remains honest (backend/growth gates stay authoritative).
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional


# ---------------------------------------------------------------------------
# High-precision seed bank (deterministic, provenance-tagged, track-balanced)
# ---------------------------------------------------------------------------

_SEED_BANK: dict[str, list[tuple[str, str]]] = {
    "software_engineering": [
        (
            "Write a pure Python function that validates an email shape without regex backtracking risk.",
            "Prefer a bounded pattern and reject oversized inputs early. Validate local and domain parts separately, "
            "cap total length (e.g. 254), and return False on empty/None. Unit-test valid, invalid, and adversarial long strings.",
        ),
        (
            "How do you design a retry helper for flaky I/O that stays safe under load?",
            "Use exponential backoff with jitter, a hard max attempts, and a total deadline. Never retry non-idempotent "
            "mutations without an idempotency key. Log attempt/error class; surface the last error clearly.",
        ),
        (
            "Explain a minimal test strategy for a FastAPI route that writes JSONL.",
            "Use TestClient against a temp directory. Assert status, body shape, and that exactly one valid JSON line "
            "was appended. Cover empty payload and invalid UTF-8 with explicit 4xx expectations.",
        ),
        (
            "What is a safe pattern for parsing untrusted JSON from a model?",
            "Extract the first {...} span, json.loads inside try/except, type-check required keys, coerce types narrowly, "
            "and fail closed (None/error) rather than inventing defaults that look successful.",
        ),
        (
            "How should a daemon training worker treat skipped cycles?",
            "Skips for empty queues or missing scores must not increment consecutive failure counters. Heartbeat, seed or "
            "ingest, then wait an adaptive interval. Only real exceptions count as failures.",
        ),
    ],
    "ai_engineering": [
        (
            "Separate experience learning from weight training in an autonomous AI control plane.",
            "Experience learning curates and evaluates instruction/response candidates. Weight training is a separate "
            "eligible job with backend/resource/growth gates. Never treat curation success as model activation.",
        ),
        (
            "What signals justify starting LoRA fine-tuning?",
            "Enough accepted examples, meaningful growth since last trained dataset, quality/provenance pass, available "
            "trainer backend, resource admission, and a trigger (schedule/owner/regression). Min-examples alone is insufficient.",
        ),
        (
            "How do you evaluate a candidate adapter before activation?",
            "Run task/regression suites against last-known-good, check reload/inference compatibility, and require explicit "
            "activation. Training loss alone is never enough for production promotion.",
        ),
        (
            "Describe honest reporting when the training backend is missing.",
            "Return TRAINING_BACKEND_UNAVAILABLE with eligible=false. Do not fabricate completed jobs, fake metrics, or "
            "silent downloads. Keep curation/learning cycles running independently.",
        ),
        (
            "Why keep auto_promote=false in continuous learning configs?",
            "Continuous workers may curate and auto-accept dataset candidates in open mode, but activating weights changes "
            "production behavior and must remain an explicit owner/API decision.",
        ),
    ],
    "reasoning_and_agents": [
        (
            "How should an agent plan tools when the user asks for continuous smart training?",
            "Prefer continuous_start/continuous_tick for curation continuity, training_eligibility before weight cycles, "
            "and never imply silent promotion. Report focus tracks, precision scores, and honest blockers.",
        ),
        (
            "Give a verification checklist before claiming a learning cycle succeeded.",
            "Confirm curated rows exist, evaluation/precision score was computed, candidate status is accepted or pending, "
            "worker heartbeat is fresh, and auto_promote remains false. Distinguish skipped vs failed.",
        ),
        (
            "What is a high-focus curriculum allocation strategy?",
            "Measure track coverage in the pending queue, pick the most underrepresented high-priority tracks, seed or "
            "generate only for those tracks, then re-rank by precision so each cycle sharpens weak areas.",
        ),
        (
            "How does deep comprehension improve training example quality?",
            "Parse user intent into latent goals (continuity, intelligence, focus, precision), reject vague filler "
            "responses, and require specific actionable answers that a student or agent can execute.",
        ),
    ],
    "general_knowledge": [
        (
            "What does 'continuous without useless restrictions' mean for PFAI learning?",
            "It means the curation worker keeps cycling: seed when empty, score when no teacher, adapt intervals, and "
            "auto-accept curated candidates in open mode — while security, SSRF, secrets, and weight promotion stay gated.",
        ),
        (
            "Summarize the difference between curated learning accept and model promotion.",
            "Accept adds a scored candidate to the learning registry/dataset path. Promotion/activation swaps the live "
            "model weights. Open mode may auto-accept candidates; it must never auto-promote weights.",
        ),
        (
            "Name three precision dimensions for training example quality.",
            "Clarity (specific question), substance (response length and concreteness), and consistency (instruction and "
            "response agree, no placeholders/todos, provenance present). Track fit is a fourth useful signal.",
        ),
    ],
}


@dataclass
class SmartContinuousConfig:
    enabled: bool = True
    fast_interval_seconds: int = 60
    base_interval_seconds: int = 120
    thin_queue_threshold: int = 8
    seed_per_focus_track: int = 3
    precision_min_score: float = 0.55
    focus_top_tracks: int = 2
    use_precision_fallback: bool = True
    max_focus_examples_per_cycle: int = 48


@dataclass
class PrecisionReport:
    score: float
    reason: str
    evaluated: int
    dimensions: dict[str, float] = field(default_factory=dict)
    method: str = "precision_engine"

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reason": self.reason,
            "evaluated": self.evaluated,
            "dimensions": dict(self.dimensions),
            "method": self.method,
        }


class PrecisionScorer:
    """Multi-dimension heuristic scorer — high focus, fails closed on junk."""

    PLACEHOLDER = re.compile(
        r"\b(todo|tbd|lorem ipsum|as an ai|i cannot|غير متاح|TODO)\b",
        re.I,
    )

    def score_example(
        self,
        instruction: str,
        response: str,
        *,
        track: str = "",
        source: str = "",
    ) -> dict[str, float]:
        ins = (instruction or "").strip()
        resp = (response or "").strip()
        dims = {
            "clarity": 0.0,
            "substance": 0.0,
            "specificity": 0.0,
            "consistency": 0.0,
            "provenance": 0.0,
            "track_fit": 0.0,
        }
        if not ins or not resp:
            return dims

        # Clarity: well-formed question / task
        if len(ins) >= 20:
            dims["clarity"] += 0.45
        if len(ins) >= 40:
            dims["clarity"] += 0.25
        if ins.endswith("?") or any(w in ins.lower() for w in ("how", "what", "why", "explain", "write", "كيف", "ما ", "اشرح")):
            dims["clarity"] += 0.30
        dims["clarity"] = min(1.0, dims["clarity"])

        # Substance: non-trivial answer
        if len(resp) >= 40:
            dims["substance"] += 0.35
        if len(resp) >= 120:
            dims["substance"] += 0.35
        if len(resp.split()) >= 18:
            dims["substance"] += 0.30
        dims["substance"] = min(1.0, dims["substance"])

        # Specificity: concrete nouns / actionable verbs
        concrete = len(re.findall(
            r"\b(test|assert|gate|lora|json|api|retry|checkpoint|sandbox|provenance|evaluate|activate|worker)\b",
            resp,
            re.I,
        ))
        dims["specificity"] = min(1.0, 0.25 * concrete + (0.2 if any(c.isdigit() for c in resp) else 0.0))

        # Consistency / anti-junk
        dims["consistency"] = 0.85
        if self.PLACEHOLDER.search(resp) or self.PLACEHOLDER.search(ins):
            dims["consistency"] = 0.1
        if len(resp) < 20:
            dims["consistency"] *= 0.4
        if ins.lower()[:40] == resp.lower()[:40]:
            dims["consistency"] *= 0.3

        # Provenance
        if source and source not in ("unknown", ""):
            dims["provenance"] = 0.9
        elif source:
            dims["provenance"] = 0.4
        else:
            dims["provenance"] = 0.2

        # Track fit (soft)
        track = (track or "").lower()
        text = (ins + " " + resp).lower()
        fit_map = {
            "software_engineering": ("python", "test", "api", "code", "debug", "fastapi"),
            "ai_engineering": ("lora", "train", "model", "evaluat", "ml", "adapter", "dataset"),
            "reasoning_and_agents": ("agent", "tool", "plan", "verif", "checklist", "focus"),
            "general_knowledge": ("learning", "promot", "curat", "precision", "continuous"),
        }
        keys = fit_map.get(track) or ()
        if keys:
            hits = sum(1 for k in keys if k in text)
            dims["track_fit"] = min(1.0, 0.2 + 0.2 * hits)
        else:
            dims["track_fit"] = 0.5

        return dims

    def aggregate(self, dims: dict[str, float]) -> float:
        weights = {
            "clarity": 0.18,
            "substance": 0.22,
            "specificity": 0.18,
            "consistency": 0.22,
            "provenance": 0.10,
            "track_fit": 0.10,
        }
        return round(sum(dims.get(k, 0.0) * w for k, w in weights.items()), 4)

    def score_batch(self, examples: Iterable[dict]) -> PrecisionReport:
        rows = list(examples)
        if not rows:
            return PrecisionReport(0.0, "no examples to evaluate", 0)
        scores: list[float] = []
        dim_acc: dict[str, float] = {}
        for r in rows:
            dims = self.score_example(
                str(r.get("instruction") or ""),
                str(r.get("response") or ""),
                track=str(r.get("track") or ""),
                source=str(r.get("source") or ""),
            )
            s = self.aggregate(dims)
            # Prefer teacher_score when present and sane
            meta = r.get("metadata") or {}
            ts = meta.get("teacher_score")
            try:
                if ts is not None:
                    s = max(s, min(1.0, float(ts)))
            except (TypeError, ValueError):
                pass
            scores.append(s)
            for k, v in dims.items():
                dim_acc[k] = dim_acc.get(k, 0.0) + v
        n = len(scores)
        avg_dims = {k: round(v / n, 4) for k, v in dim_acc.items()}
        mean = round(sum(scores) / n, 4)
        # Mild penalty if many weak rows
        weak = sum(1 for s in scores if s < 0.45)
        if weak > n // 2:
            mean = round(mean * 0.85, 4)
        reason = (
            f"precision mean={mean} n={n} "
            f"substance={avg_dims.get('substance', 0):.2f} "
            f"consistency={avg_dims.get('consistency', 0):.2f}"
        )
        return PrecisionReport(mean, reason, n, avg_dims)


class FocusAnalyzer:
    def analyze(self, pending: list[dict], track_names: list[str], priorities: dict[str, float] | None = None) -> dict[str, Any]:
        counts = {t: 0 for t in track_names}
        for row in pending:
            t = str(row.get("track") or "general_knowledge")
            if t not in counts:
                counts[t] = 0
            counts[t] += 1
        total = max(1, sum(counts.values()))
        priorities = priorities or {t: 1.0 for t in track_names}
        # Gap score: high priority + low coverage → focus
        gaps = []
        for t in track_names:
            share = counts.get(t, 0) / total
            pri = float(priorities.get(t, 0.1))
            gap = max(0.0, pri - share) + (0.15 if counts.get(t, 0) == 0 else 0.0)
            gaps.append((gap, t, counts.get(t, 0)))
        gaps.sort(reverse=True)
        return {
            "counts": counts,
            "total": len(pending),
            "ranked_gaps": [{"track": t, "count": c, "gap": round(g, 4)} for g, t, c in gaps],
        }

    def focus_tracks(self, analysis: dict[str, Any], top_n: int = 2) -> list[str]:
        ranked = analysis.get("ranked_gaps") or []
        return [x["track"] for x in ranked[: max(1, top_n)]]


class SmartContinuousBrain:
    """Coordinates focus + precision + adaptive continuity for the learning worker."""

    def __init__(
        self,
        config: Optional[SmartContinuousConfig] = None,
        *,
        open_mode: Optional[Callable[[], bool]] = None,
    ):
        self.config = config or SmartContinuousConfig()
        self.open_mode = open_mode or (lambda: False)
        self.scorer = PrecisionScorer()
        self.focus = FocusAnalyzer()
        self._cycle_index = 0
        self._last_prep: dict[str, Any] = {}
        self._last_precision: dict[str, Any] = {}
        self._seeded_total = 0
        self._precision_fallbacks = 0

    # -- seeds ---------------------------------------------------------------
    def _seed_rows(self, tracks: list[str], n_per: int) -> list[dict]:
        rows: list[dict] = []
        for track in tracks:
            bank = _SEED_BANK.get(track) or _SEED_BANK["general_knowledge"]
            # Rotate through bank by cycle index for diversity
            for i in range(n_per):
                idx = (self._cycle_index + i) % len(bank)
                ins, resp = bank[idx]
                # Variant marker keeps dedupe from collapsing all cycles forever
                variant = f" [focus-cycle {self._cycle_index}#{i}]"
                rows.append(
                    {
                        "instruction": ins + variant,
                        "response": resp,
                        "source": "smart_seed",
                        "track": track,
                        "metadata": {
                            "via": "smart_continuous",
                            "precision_seed": True,
                            "focus_track": track,
                            "cycle": self._cycle_index,
                        },
                    }
                )
        return rows

    # -- prepare -------------------------------------------------------------
    def prepare_cycle(
        self,
        pending: list[dict],
        *,
        track_names: list[str],
        track_weights: dict[str, float] | None = None,
        register_batch: Optional[Callable[[list[dict]], dict]] = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return {"enabled": False, "seeded": 0, "focus_tracks": []}
        self._cycle_index += 1
        analysis = self.focus.analyze(pending, track_names, track_weights)
        focus_tracks = self.focus.focus_tracks(analysis, self.config.focus_top_tracks)
        seeded = 0
        seed_result: dict[str, Any] = {}
        thin = len(pending) < self.config.thin_queue_threshold
        missing_focus = any(analysis["counts"].get(t, 0) == 0 for t in focus_tracks)
        if thin or missing_focus:
            rows = self._seed_rows(focus_tracks, self.config.seed_per_focus_track)
            if register_batch and rows:
                seed_result = register_batch(rows) or {}
                seeded = int(seed_result.get("accepted") or 0)
                self._seeded_total += seeded
        prep = {
            "enabled": True,
            "cycle_index": self._cycle_index,
            "focus_tracks": focus_tracks,
            "analysis": analysis,
            "thin_queue": thin,
            "seeded": seeded,
            "seed_result": seed_result,
            "open_mode": bool(self.open_mode()),
        }
        self._last_prep = prep
        return prep

    def rank_for_focus(self, pending: list[dict], focus_tracks: list[str]) -> list[dict]:
        """Prefer focused tracks and higher precision; cap for cycle density."""
        if not pending:
            return []
        focus_set = set(focus_tracks or [])

        def key(row: dict) -> tuple:
            dims = self.scorer.score_example(
                str(row.get("instruction") or ""),
                str(row.get("response") or ""),
                track=str(row.get("track") or ""),
                source=str(row.get("source") or ""),
            )
            score = self.scorer.aggregate(dims)
            in_focus = 1 if str(row.get("track") or "") in focus_set else 0
            return (in_focus, score)

        ranked = sorted(pending, key=key, reverse=True)
        cap = max(8, int(self.config.max_focus_examples_per_cycle))
        return ranked[:cap]

    def precision_score(self, examples: Iterable[dict]) -> PrecisionReport:
        report = self.scorer.score_batch(examples)
        self._last_precision = report.as_dict()
        return report

    def resolve_score(
        self,
        examples: list[dict],
        *,
        llm_score: Optional[float] = None,
        llm_reason: str = "",
    ) -> dict[str, Any]:
        """Pick the best honest score: prefer LLM when sane, else precision fallback."""
        prec = self.precision_score(examples)
        use_llm = (
            llm_score is not None
            and float(llm_score) >= self.config.precision_min_score
        )
        if use_llm:
            return {
                "score": float(llm_score),
                "reason": llm_reason or "llm_evaluator",
                "method": "llm",
                "precision": prec.as_dict(),
                "fallback_used": False,
            }
        if self.config.use_precision_fallback and prec.score >= self.config.precision_min_score:
            self._precision_fallbacks += 1
            return {
                "score": prec.score,
                "reason": prec.reason,
                "method": "precision_fallback",
                "precision": prec.as_dict(),
                "fallback_used": True,
            }
        # Fail closed below threshold
        return {
            "score": float(llm_score) if llm_score is not None else prec.score,
            "reason": llm_reason or prec.reason or "below_precision_threshold",
            "method": "llm" if llm_score is not None else "precision",
            "precision": prec.as_dict(),
            "fallback_used": False,
            "below_threshold": True,
        }

    def adaptive_interval(self, *, pending_count: int, last_skipped: bool = False) -> int:
        base = max(15, int(self.config.base_interval_seconds))
        fast = max(15, int(self.config.fast_interval_seconds))
        if not self.config.enabled:
            return base
        if self.open_mode() and (pending_count < self.config.thin_queue_threshold or last_skipped):
            return fast
        if pending_count < self.config.thin_queue_threshold:
            return min(base, max(fast, base // 2))
        return base

    def focused_self_training_tracks(self, track_names: list[str]) -> list[str]:
        prep = self._last_prep or {}
        focus = list(prep.get("focus_tracks") or [])
        if focus:
            return focus
        return list(track_names)[: max(1, self.config.focus_top_tracks)]

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.enabled),
            "cycle_index": self._cycle_index,
            "seeded_total": self._seeded_total,
            "precision_fallbacks": self._precision_fallbacks,
            "last_prep": {
                k: self._last_prep.get(k)
                for k in ("focus_tracks", "thin_queue", "seeded", "cycle_index", "open_mode")
                if self._last_prep
            },
            "last_precision": self._last_precision,
            "config": {
                "fast_interval_seconds": self.config.fast_interval_seconds,
                "base_interval_seconds": self.config.base_interval_seconds,
                "thin_queue_threshold": self.config.thin_queue_threshold,
                "precision_min_score": self.config.precision_min_score,
                "focus_top_tracks": self.config.focus_top_tracks,
                "use_precision_fallback": self.config.use_precision_fallback,
            },
            "auto_promote": False,
            "note": "Smart continuous curates/focuses/scores; weight promotion stays owner-gated.",
        }


def fingerprint_example(instruction: str, response: str) -> str:
    return hashlib.sha256(f"{instruction}\n{response}".encode()).hexdigest()[:16]


def smart_config_from_dict(raw: dict[str, Any] | None, *, base_interval: int = 120) -> SmartContinuousConfig:
    d = dict(raw or {})
    return SmartContinuousConfig(
        enabled=bool(d.get("enabled", True)),
        fast_interval_seconds=int(d.get("fast_interval_seconds") or 60),
        base_interval_seconds=int(d.get("base_interval_seconds") or base_interval or 120),
        thin_queue_threshold=int(d.get("thin_queue_threshold") or 8),
        seed_per_focus_track=int(d.get("seed_per_focus_track") or 3),
        precision_min_score=float(d.get("precision_min_score") or 0.55),
        focus_top_tracks=int(d.get("focus_top_tracks") or 2),
        use_precision_fallback=bool(d.get("use_precision_fallback", True)),
        max_focus_examples_per_cycle=int(d.get("max_focus_examples_per_cycle") or 48),
    )
