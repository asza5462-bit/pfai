"""Versioned production evaluation datasets — provenance-traceable, deduped, non-fabricated.

Builds evaluation corpora from existing validated PFAI artifacts only.
Never duplicates rows to inflate counts. Never invents content.
Excludes training-split hashes from a nominated train dataset to reduce leakage.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable


FORBIDDEN_MARKERS = (
    "password=",
    "api_key",
    "apikey",
    "secret_key",
    "authorization: bearer",
    "sk-",
    "otp=",
    "session_cookie",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _hash(instruction: str, response: str) -> str:
    return hashlib.sha256((instruction + "\0" + response).encode("utf-8")).hexdigest()


class EvaluationDatasetBuilder:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"

    def _load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"datasets": []}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {"datasets": []}

    def _save_index(self, data: dict[str, Any]) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def _allowed(self, instruction: str, response: str) -> bool:
        if len(instruction) < 8 or len(response) < 8:
            return False
        blob = (instruction + "\n" + response).lower()
        return not any(m in blob for m in FORBIDDEN_MARKERS)

    def _add(
        self,
        bucket: dict[str, dict[str, Any]],
        *,
        instruction: str,
        response: str,
        source: str,
        source_id: str = "",
        provenance: dict[str, Any] | None = None,
        exclude_hashes: set[str] | None = None,
    ) -> None:
        instruction = _norm(instruction)
        response = _norm(response)
        if not self._allowed(instruction, response):
            return
        digest = _hash(instruction, response)
        if exclude_hashes and digest in exclude_hashes:
            return
        if digest in bucket:
            return
        bucket[digest] = {
            "instruction": instruction,
            "response": response,
            "source": source,
            "source_id": str(source_id or ""),
            "content_hash": digest,
            "provenance": {
                **(provenance or {}),
                "eligible_for_evaluation": True,
                "synthetic": False,
                "collected_at": time.time(),
            },
        }

    def load_train_hashes(self, dataset_jsonl_paths: Iterable[Path]) -> set[str]:
        out: set[str] = set()
        for p in dataset_jsonl_paths:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                inst = _norm(row.get("instruction") or row.get("prompt") or "")
                resp = _norm(row.get("response") or row.get("answer") or row.get("code") or "")
                if inst and resp:
                    out.add(_hash(inst, resp))
        return out

    def harvest(
        self,
        *,
        exclude_train_dataset_dir: Path | None = None,
        workspace: Path | None = None,
    ) -> dict[str, Any]:
        workspace = workspace or Path("data")
        bucket: dict[str, dict[str, Any]] = {}
        exclude: set[str] = set()
        filtering = {
            "secret_markers": list(FORBIDDEN_MARKERS),
            "min_instruction_chars": 8,
            "min_response_chars": 8,
            "dedupe": "sha256(instruction\\0response)",
            "train_leakage_exclusion": bool(exclude_train_dataset_dir),
        }

        if exclude_train_dataset_dir and exclude_train_dataset_dir.exists():
            exclude = self.load_train_hashes(
                [exclude_train_dataset_dir / "train.jsonl"]
            )

        # Always exclude production train-bank hashes from evaluation harvest
        try:
            from .production_banks import production_train_examples

            exclude |= {r["content_hash"] for r in production_train_examples()}
            filtering["production_train_bank_exclusion"] = True
        except Exception:
            filtering["production_train_bank_exclusion"] = False

        # 1) Held-out splits from nominated dataset (validation/test only)
        if exclude_train_dataset_dir and exclude_train_dataset_dir.exists():
            for split in ("validation", "test"):
                p = exclude_train_dataset_dir / f"{split}.jsonl"
                if not p.exists():
                    continue
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines()):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    self._add(
                        bucket,
                        instruction=row.get("instruction") or "",
                        response=row.get("response") or "",
                        source=f"heldout:{exclude_train_dataset_dir.name}:{split}",
                        source_id=str(row.get("source_id") or i),
                        provenance={"split": split, "dataset": exclude_train_dataset_dir.name},
                        exclude_hashes=exclude,
                    )

        # 2) Other longevity jsonl datasets (external / historical)
        longevity = workspace / "longevity"
        if longevity.exists():
            for p in longevity.rglob("*.jsonl"):
                if "audit" in p.name:
                    continue
                # skip excluded train file
                if exclude_train_dataset_dir and p.resolve() == (
                    exclude_train_dataset_dir / "train.jsonl"
                ).resolve():
                    continue
                # Prefer not to re-ingest the same held-out files twice — still ok via dedupe
                try:
                    for i, line in enumerate(
                        p.read_text(encoding="utf-8", errors="ignore").splitlines()
                    ):
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        inst = row.get("instruction") or row.get("prompt") or ""
                        resp = (
                            row.get("response")
                            or row.get("answer")
                            or row.get("code")
                            or row.get("completion")
                            or row.get("verified_code")
                            or row.get("solution")
                            or ""
                        )
                        self._add(
                            bucket,
                            instruction=inst,
                            response=resp,
                            source=f"jsonl:{p}",
                            source_id=str(i),
                            provenance={"path": str(p)},
                            exclude_hashes=exclude,
                        )
                except Exception:
                    continue

        # 2b) Verified coding regressions (instruction + verified_code)
        for p in (workspace / "code_learning").rglob("*.jsonl") if (workspace / "code_learning").exists() else []:
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines()):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    self._add(
                        bucket,
                        instruction=row.get("instruction") or row.get("prompt") or "",
                        response=row.get("verified_code")
                        or row.get("code")
                        or row.get("solution")
                        or "",
                        source=f"verified_regression:{p.name}",
                        source_id=str(row.get("id") or i),
                        provenance={"path": str(p), "kind": "verified_regression"},
                        exclude_hashes=exclude,
                    )
            except Exception:
                continue

        # 2c) Continuous experience accumulator (eval-only; never used for weight updates)
        for acc in self.root.rglob("accumulator.jsonl"):
            try:
                for i, line in enumerate(acc.read_text(encoding="utf-8", errors="ignore").splitlines()):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    self._add(
                        bucket,
                        instruction=row.get("instruction") or "",
                        response=row.get("response") or "",
                        source="accumulator",
                        source_id=str(row.get("source_id") or i),
                        provenance=row.get("provenance") or {"path": str(acc)},
                        exclude_hashes=exclude,
                    )
            except Exception:
                continue

        # 3) Learning candidate stores
        for cand_db in longevity.rglob("candidates.sqlite3") if longevity.exists() else []:
            try:
                con = sqlite3.connect(cand_db)
                for row in con.execute(
                    "SELECT candidate_id, instruction, response, source, eligibility "
                    "FROM candidates"
                ):
                    cid, inst, resp, src, elig = row
                    if str(elig or "").upper() in ("REJECTED", "INELIGIBLE"):
                        continue
                    self._add(
                        bucket,
                        instruction=inst or "",
                        response=resp or "",
                        source=f"candidate:{src}",
                        source_id=str(cid),
                        provenance={"db": str(cand_db), "eligibility": elig},
                        exclude_hashes=exclude,
                    )
                con.close()
            except Exception:
                continue

        # 4) Approved seeds + curriculum (external to train split ideally)
        # Never include production train-bank rows in evaluation (leakage).
        try:
            from .experience_seeds import approved_pfai_seed_examples
            from .production_banks import production_train_examples

            train_bank_hashes = {r["content_hash"] for r in production_train_examples()}
            exclude = set(exclude) | train_bank_hashes
            for i, row in enumerate(approved_pfai_seed_examples()):
                prov = row.get("provenance") or {}
                if prov.get("bank") == "train":
                    continue
                if row.get("content_hash") in train_bank_hashes:
                    continue
                self._add(
                    bucket,
                    instruction=row.get("instruction") or "",
                    response=row.get("response") or "",
                    source="approved_seed",
                    source_id=str(row.get("source_id") or i),
                    provenance={"kind": "owner_approved_seed", **prov},
                    exclude_hashes=exclude,
                )
        except Exception:
            pass

        try:
            from pfai.coding_curriculum import CODING_CURRICULUM  # type: ignore
        except Exception:
            try:
                from pfai.api import CODING_CURRICULUM  # type: ignore
            except Exception:
                CODING_CURRICULUM = None
        if CODING_CURRICULUM is not None:
            try:
                for track in CODING_CURRICULUM.list_tracks():
                    tid = track["id"] if isinstance(track, dict) else track
                    track_full = CODING_CURRICULUM.get_track(tid) or {}
                    lessons = list(track_full.get("lessons") or [])
                    if not lessons:
                        levels = (track.get("levels") if isinstance(track, dict) else None) or []
                        for level in levels:
                            lessons.extend(CODING_CURRICULUM.lessons_for_level(tid, level) or [])
                    for lesson in lessons:
                        full = CODING_CURRICULUM.get_lesson(tid, lesson["id"]) or lesson
                        ex = full.get("exercise") or {}
                        lid = lesson.get("id")
                        if ex.get("prompt") and ex.get("solution"):
                            self._add(
                                bucket,
                                instruction=ex["prompt"],
                                response=ex["solution"],
                                source="curriculum",
                                source_id=f"{tid}/{lid}",
                                provenance={"track": tid, "lesson": lid},
                                exclude_hashes=exclude,
                            )
                        if ex.get("prompt") and ex.get("starter"):
                            self._add(
                                bucket,
                                instruction=f"Provide starter code for: {ex.get('prompt')}",
                                response=str(ex.get("starter")),
                                source="curriculum_starter",
                                source_id=f"{tid}/{lid}",
                                provenance={"track": tid, "lesson": lid},
                                exclude_hashes=exclude,
                            )
                        if full.get("concept"):
                            resp = str(full.get("concept") or "")
                            if full.get("example"):
                                resp = resp + "\n" + str(full.get("example"))
                            self._add(
                                bucket,
                                instruction=f"Explain concept: {full.get('title') or lid}",
                                response=resp,
                                source="curriculum_concept",
                                source_id=f"{tid}/{lid}",
                                provenance={"track": tid, "lesson": lid},
                                exclude_hashes=exclude,
                            )
                        hints = ex.get("hints") or []
                        if isinstance(hints, list) and hints and ex.get("prompt"):
                            self._add(
                                bucket,
                                instruction=f"Provide hints for: {ex.get('prompt')}",
                                response=" | ".join(map(str, hints)),
                                source="curriculum_hint",
                                source_id=f"{tid}/{lid}",
                                provenance={"track": tid, "lesson": lid},
                                exclude_hashes=exclude,
                            )
                # Assessments (map choice index → answer text)
                for a in CODING_CURRICULUM.assessments() or []:
                    prompt = a.get("prompt") or a.get("question") or ""
                    choices = a.get("choices") or []
                    ans_idx = a.get("answer")
                    if isinstance(ans_idx, int) and 0 <= ans_idx < len(choices):
                        answer = str(choices[ans_idx])
                    else:
                        answer = str(a.get("solution") or a.get("rubric") or "")
                    if prompt and answer:
                        self._add(
                            bucket,
                            instruction=str(prompt),
                            response=answer,
                            source="assessment",
                            source_id=str(a.get("id") or ""),
                            provenance={"skill": a.get("skill"), "level": a.get("level")},
                            exclude_hashes=exclude,
                        )
                # Projects
                for proj in CODING_CURRICULUM.projects() or []:
                    title = proj.get("title") or proj.get("id") or ""
                    body = "\n".join(
                        [
                            str(proj.get("description") or proj.get("brief") or ""),
                            "Requirements: " + ", ".join(map(str, proj.get("requirements") or [])),
                            "Tasks: " + ", ".join(map(str, proj.get("tasks") or [])),
                        ]
                    ).strip()
                    if title and body:
                        self._add(
                            bucket,
                            instruction=f"Describe coding project: {title}",
                            response=body,
                            source="project",
                            source_id=str(proj.get("id") or title),
                            provenance={"level": proj.get("level")},
                            exclude_hashes=exclude,
                        )
                # Knowledge base entries
                for e in CODING_CURRICULUM.knowledge_search("", 500) or []:
                    self._add(
                        bucket,
                        instruction=f"Explain: {e.get('title')}",
                        response=str(e.get("content") or ""),
                        source="knowledge",
                        source_id=str(e.get("id") or e.get("title") or ""),
                        provenance={"category": e.get("category"), "version": e.get("version")},
                        exclude_hashes=exclude,
                    )
            except Exception:
                pass

        # 5) Longevity knowledge_versions (verified knowledge facts)
        for kdb in longevity.rglob("knowledge_versions.sqlite3") if longevity.exists() else []:
            try:
                con = sqlite3.connect(kdb)
                for row in con.execute(
                    "SELECT knowledge_id, version, content, status FROM knowledge_versions"
                ):
                    kid, ver, content, status = row
                    if str(status or "").upper() in ("REJECTED", "DELETED"):
                        continue
                    self._add(
                        bucket,
                        instruction=f"Recall verified knowledge entry {kid}",
                        response=str(content or ""),
                        source="knowledge_version",
                        source_id=f"{kid}@v{ver}",
                        provenance={"db": str(kdb), "version": ver},
                        exclude_hashes=exclude,
                    )
                con.close()
            except Exception:
                continue

        # 6) Production evaluation bank (disjoint from production train bank)
        try:
            from .production_banks import production_eval_examples

            for row in production_eval_examples():
                self._add(
                    bucket,
                    instruction=row.get("instruction") or "",
                    response=row.get("response") or "",
                    source=str(row.get("source") or "production_bank_eval"),
                    source_id=str(row.get("source_id") or ""),
                    provenance=row.get("provenance") or {"bank": "eval"},
                    exclude_hashes=exclude,
                )
        except Exception:
            pass

        examples = list(bucket.values())
        by_source: dict[str, int] = {}
        for ex in examples:
            key = str(ex.get("source") or "?").split(":")[0]
            by_source[key] = by_source.get(key, 0) + 1

        return {
            "examples": examples,
            "count": len(examples),
            "excluded_train_hashes": len(exclude),
            "source_distribution": by_source,
            "filtering": filtering,
        }

    def build_version(
        self,
        *,
        exclude_train_dataset_dir: Path | None = None,
        workspace: Path | None = None,
        label: str = "prodeval",
    ) -> dict[str, Any]:
        harvested = self.harvest(
            exclude_train_dataset_dir=exclude_train_dataset_dir,
            workspace=workspace,
        )
        examples = harvested["examples"]
        payload = json.dumps(
            [{"instruction": e["instruction"], "response": e["response"], "content_hash": e["content_hash"]} for e in examples],
            sort_keys=True,
            ensure_ascii=False,
        )
        content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        idx = self._load_index()
        for item in idx.get("datasets") or []:
            if item.get("content_hash") == content_hash:
                # Reload examples from disk for caller
                existing_dir = self.root / item["dataset_id"]
                examples_path = existing_dir / "examples.jsonl"
                loaded = []
                if examples_path.exists():
                    for line in examples_path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            loaded.append(json.loads(line))
                return {**item, "examples": loaded, "created": False}

        n = len(idx.get("datasets") or []) + 1
        dataset_id = f"{label}-v{n:04d}"
        out_dir = self.root / dataset_id
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "examples.jsonl").open("w", encoding="utf-8") as fh:
            for ex in examples:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
        manifest = {
            "dataset_id": dataset_id,
            "content_hash": content_hash,
            "count": len(examples),
            "excluded_train_hashes": harvested["excluded_train_hashes"],
            "source_distribution": harvested["source_distribution"],
            "filtering": harvested["filtering"],
            "created_at": time.time(),
            "label": label,
            "note": "Evaluation-only corpus; not used for weight updates.",
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        idx.setdefault("datasets", []).append(
            {k: manifest[k] for k in ("dataset_id", "content_hash", "count", "created_at", "label")}
        )
        self._save_index(idx)
        return {**manifest, "examples": examples, "created": True}
