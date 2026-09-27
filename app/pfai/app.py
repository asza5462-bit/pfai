from .config import Config
from .audit import AuditLog
from .memory import MemoryStore
from .model import EchoProvider
from .model_http import OpenAICompatibleProvider
from .model_anthropic import AnthropicProvider
from .policy import Policy
from .web import WebTool
from .tools import ToolGateway
from .agent import Agent
from .embeddings import HashEmbeddingProvider, SentenceTransformerProvider
from .vector_store import VectorStore
from .rag import RAGEngine
from .self_reflection import SelfReflectionEngine
from .llm_reasoning import IntelligentReasoner

def build_app(path='configs/default.json'):
    c=Config.load(path); audit=AuditLog(c['audit']['path']); policy=Policy(c['security']); web=WebTool(policy,audit); tools=ToolGateway(web,audit)
    mc=c.get('model',{}); provider=mc.get('provider','echo')
    if provider=='openai_compatible':
        # Prefer env-sourced secrets. `api_key` in JSON is legacy; if present it
        # should be an env var *name* only when `api_key_env` is set.
        import os as _os
        key_env = mc.get('api_key_env')
        api_key = _os.environ.get(key_env, '') if key_env else ''
        if not api_key:
            # Backward compatible: allow empty key for local unauthenticated gateways.
            api_key = ''
        model=OpenAICompatibleProvider(mc['base_url'],mc['model'],api_key)
    elif provider=='anthropic': model=AnthropicProvider(mc.get('model','claude-opus-5'),mc.get('base_url','https://api.anthropic.com/v1'),int(mc.get('max_tokens',2048)),mc.get('api_key_env','ANTHROPIC_API_KEY'))
    else: model=EchoProvider()
    ec=c.get('embeddings',{});
    if ec.get('provider')=='sentence_transformers': embedder=SentenceTransformerProvider(ec.get('model','all-MiniLM-L6-v2'))
    else: embedder=HashEmbeddingProvider(int(ec.get('dimensions',256)))
    store=VectorStore(c['vector_memory']['path'],embedder); rag=RAGEngine(model,store,audit=audit)
    # Memory gets its own semantic index (separate sqlite file from RAG's vector_memory,
    # so a lesson learned via reflection is never mixed into RAG's document corpus).
    # If this fails to build for any reason, MemoryStore still works exactly as before
    # via its LIKE-based fallback — this is a pure quality upgrade, never a new failure mode.
    try: memory_vectors=VectorStore(c['memory'].get('vector_path','data/memory_vectors.sqlite3'),embedder)
    except Exception: memory_vectors=None
    memory=MemoryStore(c['memory']['path'],vector_store=memory_vectors)
    # A real model (not the offline EchoProvider placeholder) powers self-learning-via-
    # memory (reflection) and model-driven planning/critique (reasoning), still bounded
    # by the same tool/permission gates as everything else in PFAI.
    learning_cfg=c.get('self_learning',{})
    reflector=SelfReflectionEngine(model,memory,int(learning_cfg.get('max_lessons',3)),float(learning_cfg.get('confidence',0.5))) if provider!='echo' else None
    reasoner=IntelligentReasoner(model) if provider!='echo' else None
    agent=Agent(model,memory,tools,audit,rag,reflector)
    return agent,memory,tools,store,reasoner

def main():
    agent,memory,tools,store,reasoner=build_app(); print('PFAI 8.0.0 ready')
