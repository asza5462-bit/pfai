import json, urllib.request
from .model import ModelProvider
class OpenAICompatibleProvider(ModelProvider):
    """Works with local servers such as Ollama/vLLM or compatible gateways."""
    def __init__(self,base_url,model,api_key=''):
        self.base_url=base_url.rstrip('/'); self.model=model; self.api_key=api_key
    def generate(self,prompt,**kwargs):
        payload={'model':self.model,'messages':[{'role':'user','content':prompt}], 'temperature':kwargs.get('temperature',0.2)}
        req=urllib.request.Request(self.base_url+'/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        if self.api_key: req.add_header('Authorization','Bearer '+self.api_key)
        with urllib.request.urlopen(req,timeout=kwargs.get('timeout',60)) as r:
            data=json.loads(r.read().decode())
        return data['choices'][0]['message']['content']
