"""v6.12: scheduled recovery drills and tamper-evident observability."""
from __future__ import annotations
import hashlib, json, os, time
from dataclasses import dataclass, asdict
from pathlib import Path
from .recovery_drill import RecoveryDrill

@dataclass(frozen=True)
class DrillRecord:
    snapshot: str
    started_at: float
    finished_at: float
    duration_ms: float
    verified: bool
    restored: bool
    integrity_ok: bool
    state_rows: int
    error: str | None = None

class RecoveryDrillScheduler:
    def __init__(self, backup_dir: str | Path, history_path: str | Path | None = None, interval_seconds: int = 86400):
        self.backup_dir = Path(backup_dir)
        self.history_path = Path(history_path or self.backup_dir / "recovery_drills.jsonl")
        self.interval_seconds = max(1, int(interval_seconds))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, rec: DrillRecord):
        prev = "0" * 64
        if self.history_path.exists():
            try:
                prev = json.loads(self.history_path.read_text(encoding="utf-8").splitlines()[-1])["hash"]
            except Exception:
                prev = "CORRUPT"
        body = {"prev": prev, **asdict(rec)}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        body["hash"] = hashlib.sha256(raw).hexdigest()
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")
            f.flush(); os.fsync(f.fileno())

    def verify_history(self) -> bool:
        if not self.history_path.exists(): return True
        prev = "0" * 64
        try:
            for line in self.history_path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line); got = item.pop("hash")
                if item.get("prev") != prev: return False
                raw = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
                if hashlib.sha256(raw).hexdigest() != got: return False
                prev = got
            return True
        except Exception:
            return False

    def history(self) -> list[dict]:
        if not self.history_path.exists(): return []
        return [json.loads(x) for x in self.history_path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def last_success(self, snapshot: str) -> float | None:
        rows = [r for r in self.history() if r.get("snapshot") == snapshot and r.get("integrity_ok")]
        return max((float(r["finished_at"]) for r in rows), default=None)

    def due(self, snapshot: str, now: float | None = None) -> bool:
        now = time.time() if now is None else float(now)
        last = self.last_success(snapshot)
        return last is None or now - last >= self.interval_seconds

    def run(self, snapshot: str, expected_sha256: str | None = None, now: float | None = None) -> DrillRecord:
        if not self.verify_history():
            raise RuntimeError("recovery drill history integrity failure")
        started = time.time() if now is None else float(now)
        result = RecoveryDrill(self.backup_dir).drill_sqlite(snapshot, expected_sha256)
        finished = time.time() if now is None else max(started, float(now))
        rec = DrillRecord(snapshot, started, finished, max(0.0, (finished-started)*1000), result.verified, result.restored, result.integrity_ok, result.state_rows, result.error)
        self._append(rec)
        return rec
