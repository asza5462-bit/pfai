"""v6.11: recovery policy with external approval quorum for high-impact recovery."""
from __future__ import annotations
import hashlib, json, os, shutil, sqlite3, tempfile, time
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    snapshot: str | None = None
    drill_ok: bool = False
    approval_required: bool = False

class RecoveryPolicy:
    ALLOW = "ALLOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENY = "DENY"
    RECOVERED = "RECOVERED"
    FORBIDDEN_APPROVERS = {"model", "agent", "system", "self"}

    def __init__(self, db_path: str | Path, backup_dir: str | Path, ledger_path: str | Path | None = None, approval_quorum: int = 2):
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.ledger_path = Path(ledger_path or (self.backup_dir / "recovery_policy_ledger.jsonl"))
        self.approval_quorum = max(1, int(approval_quorum))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def _integrity(self, path: Path) -> bool:
        if not path.exists(): return False
        try:
            with sqlite3.connect(path) as con:
                row = con.execute("PRAGMA integrity_check").fetchone()
                return bool(row and row[0] == "ok")
        except sqlite3.DatabaseError:
            return False

    def _hash(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _verified_snapshots(self):
        out = []
        for meta in self.backup_dir.glob("*.json"):
            if meta.name == self.ledger_path.name: continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                p = Path(data["path"])
                if not p.is_absolute(): p = self.backup_dir / p
                if p.exists() and self._hash(p) == data.get("sha256") and self._integrity(p):
                    out.append((p.stat().st_mtime, p))
            except Exception:
                continue
        return [p for _, p in sorted(out, reverse=True)]

    def _append_audit(self, event: dict):
        prev = "0" * 64
        if self.ledger_path.exists():
            try:
                last = self.ledger_path.read_text(encoding="utf-8").splitlines()[-1]
                prev = json.loads(last)["hash"]
            except Exception:
                prev = "CORRUPT"
        body = {"ts": time.time(), "prev": prev, **event}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        body["hash"] = hashlib.sha256(raw).hexdigest()
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")
            f.flush(); os.fsync(f.fileno())

    def verify_ledger(self) -> bool:
        if not self.ledger_path.exists(): return True
        prev = "0" * 64
        try:
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line); got = item.pop("hash")
                if item.get("prev") != prev: return False
                raw = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
                if hashlib.sha256(raw).hexdigest() != got: return False
                prev = got
            return True
        except Exception:
            return False

    def _decision(self, action, reason, snapshot=None, drill_ok=False, approval_required=False):
        d = RecoveryDecision(action, reason, snapshot, drill_ok, approval_required)
        self._append_audit({"event":"decision","action":d.action,"reason":d.reason,"snapshot":d.snapshot,"approval_required":d.approval_required})
        return d

    def decide(self, force: bool = False) -> RecoveryDecision:
        if not self.verify_ledger():
            return self._decision(self.DENY, "audit_ledger_invalid")
        if self._integrity(self.db_path) and not force:
            return self._decision(self.ALLOW, "database_valid_no_recovery")
        snaps = self._verified_snapshots()
        if not snaps:
            return self._decision(self.DENY, "no_verified_snapshot")
        snap = snaps[0]
        if force:
            return self._decision(self.APPROVAL_REQUIRED, "forced_recovery_requires_external_approval", snap.name, True, True)
        return self._decision(self.ALLOW, "verified_snapshot_and_integrity", snap.name, True, False)

    def approve(self, decision: RecoveryDecision, approvers) -> bool:
        if decision.action != self.APPROVAL_REQUIRED or not decision.snapshot:
            return False
        names = []
        for approver in approvers or []:
            name = str(approver).strip()
            if name and name.lower() not in self.FORBIDDEN_APPROVERS and name not in names:
                names.append(name)
        if len(names) < self.approval_quorum:
            self._append_audit({"event":"approval","action":self.DENY,"reason":"approval_quorum_not_met","snapshot":decision.snapshot,"count":len(names)})
            return False
        self._append_audit({"event":"approval","action":"APPROVED","reason":"external_approval_quorum_met","snapshot":decision.snapshot,"approvers":names})
        return True

    def recover(self, force: bool = False, approvers=None) -> RecoveryDecision:
        d = self.decide(force=force)
        if d.action == self.APPROVAL_REQUIRED:
            if not self.approve(d, approvers):
                return RecoveryDecision(self.DENY, "external_approval_required", d.snapshot, d.drill_ok, True)
        elif d.action != self.ALLOW or d.reason == "database_valid_no_recovery":
            return d
        snap = self.backup_dir / d.snapshot
        if self.db_path.exists():
            bad = self.db_path.with_suffix(self.db_path.suffix + f".recovery-{time.time_ns()}.bad")
            shutil.copy2(self.db_path, bad)
        fd, tmp = tempfile.mkstemp(prefix=".safe-recovery-", dir=self.db_path.parent); os.close(fd)
        p = Path(tmp)
        try:
            shutil.copy2(snap, p)
            if not self._integrity(p):
                self._append_audit({"event":"recovery","action":self.DENY,"reason":"restored_snapshot_failed_integrity","snapshot":snap.name})
                return RecoveryDecision(self.DENY, "restored_snapshot_failed_integrity", snap.name, False, d.approval_required)
            os.replace(p, self.db_path)
            self._append_audit({"event":"recovery","action":self.RECOVERED,"reason":"verified_snapshot_restored","snapshot":snap.name})
            return RecoveryDecision(self.RECOVERED, "verified_snapshot_restored", snap.name, True, d.approval_required)
        finally:
            if p.exists(): p.unlink()
