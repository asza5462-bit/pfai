import json
from pathlib import Path
from datetime import datetime, timezone
class AuditLog:
    def __init__(self, path):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
    def record(self, actor, action, details=None):
        event={"ts":datetime.now(timezone.utc).isoformat(),"actor":actor,"action":action,"details":details or {}}
        with self.path.open("a",encoding="utf-8") as f: f.write(json.dumps(event,ensure_ascii=False)+"\n")
