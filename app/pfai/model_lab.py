import importlib.util
from dataclasses import dataclass

@dataclass
class EnvironmentReport:
    python: str
    transformers: bool
    torch: bool
    cuda: bool
    gpu_count: int
    device: str

class ModelLab:
    def environment(self):
        import sys
        torch_ok = importlib.util.find_spec('torch') is not None
        tr_ok = importlib.util.find_spec('transformers') is not None
        cuda = False; count = 0
        if torch_ok:
            import torch
            cuda = bool(torch.cuda.is_available())
            count = int(torch.cuda.device_count()) if cuda else 0
        return EnvironmentReport(sys.version.split()[0], tr_ok, torch_ok, cuda, count, 'cuda' if cuda else 'cpu')

    def backend(self):
        return 'transformers' if importlib.util.find_spec('transformers') else 'external-openai-compatible'

    def load_local(self, model_id, device='auto'):
        if importlib.util.find_spec('transformers') is None:
            raise RuntimeError('transformers is not installed; use an OpenAI-compatible serving endpoint or install the optional training dependencies')
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch
        actual = device
        if device == 'auto': actual = 'cuda' if torch.cuda.is_available() else 'cpu'
        tok = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(model_id)
        model.to(actual)
        return tok, model, actual
