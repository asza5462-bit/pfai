import json
from pathlib import Path
class Config:
    @classmethod
    def load(cls, path="configs/default.json"):
        return json.loads(Path(path).read_text(encoding="utf-8"))
