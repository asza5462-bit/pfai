from dataclasses import dataclass, asdict
from pathlib import Path
import json, time

@dataclass
class TrainingCapability:
    torch: bool
    transformers: bool
    peft: bool
    trl: bool
    datasets: bool
    cuda: bool

class SFTLoRATrainer:
    def __init__(self, output_root='artifacts/training'):
        self.output_root = Path(output_root)

    def capabilities(self):
        def has(name):
            try: __import__(name); return True
            except Exception: return False
        cuda = False
        try:
            import torch; cuda = bool(torch.cuda.is_available())
        except Exception: pass
        return TrainingCapability(has('torch'), has('transformers'), has('peft'), has('trl'), has('datasets'), cuda)

    def preflight(self, require_gpu=False):
        c=self.capabilities(); d=asdict(c)
        missing=[k for k in ('torch','transformers','peft','trl','datasets') if not d[k]]
        if require_gpu and not c.cuda: missing.append('cuda')
        return {'ready': not missing, 'missing': missing, 'capabilities': d}

    def prepare_run(self, run_id, model_id, dataset_manifest, config=None):
        p=self.output_root/run_id; p.mkdir(parents=True, exist_ok=True)
        manifest={'run_id':run_id,'model_id':model_id,'dataset_manifest':dataset_manifest,'config':config or {},'created_at':time.time(),'trainer':'SFTLoRA'}
        (p/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8'); return manifest

    def resume_from(self, run_id):
        p=self.output_root/run_id; cps=sorted(p.glob('checkpoint-*')) if p.exists() else []
        return str(cps[-1]) if cps else None

    def train(self, run_id, dry_run=True, require_gpu=False, model_id=None, rows=None, config=None):
        check=self.preflight(require_gpu)
        if dry_run:
            p=self.output_root/run_id; p.mkdir(parents=True,exist_ok=True); cp=p/'checkpoint-0000'; cp.mkdir(exist_ok=True)
            (cp/'trainer_state.json').write_text(json.dumps({'run_id':run_id,'dry_run':True,'capabilities':check['capabilities']},indent=2),encoding='utf-8')
            return {'status':'dry_run','checkpoint':str(cp),'preflight':check}
        if not check['ready']:
            return {'status':'blocked','reason':'real training backend unavailable','preflight':check}
        if not model_id or not rows:
            return {'status':'blocked','reason':'model_id and non-empty rows are required','preflight':check}
        # TRL's SFTTrainer performs real forward/backward/optimizer steps. This
        # branch is intentionally only entered after the full dependency preflight.
        try:
            from datasets import Dataset
            from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
            from peft import LoraConfig
            from trl import SFTTrainer
            p=self.output_root/run_id; p.mkdir(parents=True,exist_ok=True)
            ds=Dataset.from_list([{'text': f"### Instruction\n{r['instruction']}\n### Response\n{r['response']}"} for r in rows])
            tokenizer=AutoTokenizer.from_pretrained(model_id, use_fast=True)
            model=AutoModelForCausalLM.from_pretrained(model_id)
            if tokenizer.pad_token is None: tokenizer.pad_token=tokenizer.eos_token
            args=TrainingArguments(output_dir=str(p), per_device_train_batch_size=int((config or {}).get('batch_size',1)), num_train_epochs=float((config or {}).get('epochs',1)), learning_rate=float((config or {}).get('learning_rate',2e-5)), logging_steps=10, save_strategy='steps', save_steps=100, report_to=[])
            trainer=SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=ds, args=args, peft_config=LoraConfig(r=8,lora_alpha=16,lora_dropout=0.05,target_modules=(config or {}).get('target_modules', ['q_proj','v_proj'])))
            result=trainer.train(); trainer.save_model(str(p/'final'))
            return {'status':'completed','checkpoint':str(p/'final'),'train_loss':getattr(result,'training_loss',None),'preflight':check}
        except Exception as exc:
            return {'status':'failed','reason':str(exc),'preflight':check}
