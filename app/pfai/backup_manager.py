"""v6.8: safe backup rotation and verified recovery-point management."""
from __future__ import annotations
import hashlib, json, os, shutil, tempfile, time
from pathlib import Path

class BackupManager:
    def __init__(self, source: str, backup_dir: str, retention: int = 5):
        if retention < 2:
            raise ValueError("retention must be >= 2")
        self.source = Path(source)
        self.backup_dir = Path(backup_dir)
        self.retention = retention
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.backup_dir / "manifest.json"

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def create(self, label: str | None = None) -> dict:
        if not self.source.exists():
            raise FileNotFoundError(self.source)
        stamp = f"{time.time_ns()}"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "snapshot"))
        target = self.backup_dir / f"{stamp}_{safe}.bak"
        fd, tmp = tempfile.mkstemp(prefix=".backup-", dir=self.backup_dir)
        os.close(fd)
        tmp_path = Path(tmp)
        try:
            shutil.copy2(self.source, tmp_path)
            digest = self._sha256(tmp_path)
            os.replace(tmp_path, target)
            rec = {"path": target.name, "sha256": digest, "created_at": time.time(), "size": target.stat().st_size}
            entries = self._load()
            entries.append(rec)
            self._save(entries)
            self.rotate()
            return rec
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _load(self):
        if not self.manifest.exists():
            return []
        try:
            return json.loads(self.manifest.read_text())
        except Exception:
            return []

    def _save(self, entries):
        fd, tmp = tempfile.mkstemp(prefix=".manifest-", dir=self.backup_dir)
        os.close(fd)
        p = Path(tmp)
        try:
            p.write_text(json.dumps(entries, indent=2, sort_keys=True))
            with p.open("rb") as f: os.fsync(f.fileno())
            os.replace(p, self.manifest)
        finally:
            if p.exists(): p.unlink()

    def verify(self, rec: dict) -> bool:
        p = self.backup_dir / rec["path"]
        return p.exists() and self._sha256(p) == rec["sha256"]

    def verified(self):
        return [r for r in self._load() if self.verify(r)]

    def rotate(self):
        entries = sorted(self._load(), key=lambda r: r.get("created_at", 0), reverse=True)
        verified = [r for r in entries if self.verify(r)]
        keep = entries[: self.retention]
        # Never delete the last verified recovery point.
        if not verified:
            return
        keep_names = {r["path"] for r in keep}
        newest_verified = verified[0]
        keep_names.add(newest_verified["path"])
        new_entries = []
        for r in entries:
            if r["path"] in keep_names:
                new_entries.append(r)
            else:
                p = self.backup_dir / r["path"]
                if p.exists(): p.unlink()
        self._save(sorted(new_entries, key=lambda r: r.get("created_at", 0)))

    def restore_latest(self) -> dict:
        candidates = sorted(self.verified(), key=lambda r: r.get("created_at", 0), reverse=True)
        if not candidates:
            raise RuntimeError("no verified recovery point")
        rec = candidates[0]
        src = self.backup_dir / rec["path"]
        fd, tmp = tempfile.mkstemp(prefix=".restore-", dir=self.source.parent)
        os.close(fd)
        p = Path(tmp)
        try:
            shutil.copy2(src, p)
            if self._sha256(p) != rec["sha256"]:
                raise RuntimeError("recovery point changed during restore")
            os.replace(p, self.source)
            return rec
        finally:
            if p.exists(): p.unlink()
