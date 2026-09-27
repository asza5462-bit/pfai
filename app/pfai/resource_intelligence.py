from __future__ import annotations
from dataclasses import dataclass
import os, shutil

@dataclass(frozen=True)
class Resources:
    cpu:int
    ram_bytes:int
    disk_free_bytes:int
    gpu_count:int=0
    gpu_vram_bytes:int=0

class ResourceManager:
    def detect(self):
        cpu=os.cpu_count() or 1
        ram=0
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    if line.startswith('MemTotal:'): ram=int(line.split()[1])*1024; break
        except OSError: pass
        disk=shutil.disk_usage('.').free
        gpu=0; vram=0
        try:
            import torch
            if torch.cuda.is_available():
                gpu=torch.cuda.device_count(); vram=max(int(torch.cuda.get_device_properties(i).total_memory) for i in range(gpu))
        except Exception: pass
        return Resources(cpu,ram,disk,gpu,vram)
    def can_run(self,req,actual=None):
        r=actual or self.detect(); return all(r.__dict__.get(k,0)>=v for k,v in req.items())
