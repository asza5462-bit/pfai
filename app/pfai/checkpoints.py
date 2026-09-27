import json, os, hashlib, shutil
from datetime import datetime, timezone
class CheckpointStore:
    def __init__(self, root='data/checkpoints'):
        self.root=root; os.makedirs(root,exist_ok=True)
    def save(self, version, artifact, metadata=None):
        dst=os.path.join(self.root,version.replace('/','_')); os.makedirs(dst,exist_ok=True)
        target=os.path.join(dst,os.path.basename(artifact))
        if os.path.abspath(artifact)!=os.path.abspath(target): shutil.copy2(artifact,target)
        manifest={'version':version,'artifact':target,'sha256':self._sha256(target),'created_at':datetime.now(timezone.utc).isoformat(),'metadata':metadata or {}}
        with open(os.path.join(dst,'manifest.json'),'w',encoding='utf-8') as f: json.dump(manifest,f,ensure_ascii=False,indent=2)
        return manifest
    def _sha256(self,p):
        h=hashlib.sha256()
        with open(p,'rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
        return h.hexdigest()
