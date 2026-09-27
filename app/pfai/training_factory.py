from __future__ import annotations
import json, time, uuid
from pathlib import Path
from .data_factory import DataFactory

class TrainingFactory:
    def __init__(self, data_factory=None, workdir="runs"):
        self.data_factory=data_factory or DataFactory(); self.workdir=Path(workdir); self.workdir.mkdir(parents=True,exist_ok=True)
    def prepare(self, dataset_id, version, rows):
        clean=self.data_factory.clean(rows); splits=self.data_factory.split(clean); manifest=self.data_factory.manifest(dataset_id,version,splits)
        root=self.workdir / f"{dataset_id}-{version}"; root.mkdir(parents=True,exist_ok=True)
        for name, data in splits.items(): self.data_factory.save_jsonl(root/f"{name}.jsonl",data)
        (root/"manifest.json").write_text(json.dumps(manifest.__dict__,indent=2),encoding="utf-8")
        return manifest
    def start_run(self, dataset_id, version, backend="dry-run"):
        run_id=f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        p=self.workdir/run_id; p.mkdir(parents=True,exist_ok=True)
        payload={"run_id":run_id,"dataset_id":dataset_id,"dataset_version":version,"backend":backend,"status":"created","checkpoint_dir":str(p/"checkpoints")}
        (p/"run.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
        (p/"checkpoints").mkdir()
        return payload
