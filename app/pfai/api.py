from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import os
import time
from fastapi.responses import FileResponse
from pathlib import Path
from .recovery_scheduler import RecoveryDrillScheduler
from pydantic import BaseModel
from .runtime import PFAIRuntime
from .continuous_learning_orchestrator import ContinuousLearningOrchestrator
from .code_execution_evaluator import SandboxedCodeEvaluator
from .code_best_of_n import select_best_solution
from .regression_capture import RegressionCapture
from .code_learning_pipeline import CodeLearningPipeline
from .owner_control import OwnerControl
from .policy import Policy
from .research_gate import ResearchGate
from .config import Config
from .continuous_gate import continuous_gate_status, is_continuous_enabled
from .logging_setup import setup_logging
from .command_audit import CommandAuditLog
from .command_memory import CommandMemoryService
from .tool_router import ToolRouter, ToolSpec, DEFAULT_TOOLS
from .command_agent import CommandAgent
from .coding_curriculum import CurriculumEngine
from .coding_skill_profile import SkillProfileStore
from .coding_academy_memory import CodingAcademyMemory
from .coding_agent import CodingAgent
from .coding_training_scaffold import CodingTrainingScaffold
from .code_execution_evaluator import SandboxedCodeEvaluator
from . import __version__

log = setup_logging('pfai.api')
app=FastAPI(title='PFAI Control API',version=__version__)
_cors=os.getenv('PFAI_CORS_ORIGINS','').strip()
if _cors:
    app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in _cors.split(',') if x.strip()], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
    log.info('CORS enabled for origins: %s', _cors)
else:
    log.info('CORS disabled (set PFAI_CORS_ORIGINS to allow separate frontend hosts)')

runtime=PFAIRuntime()
RECOVERY=RecoveryDrillScheduler('data/backups')
# Passing runtime.model lets the orchestrator auto-score curated batches with the
# real connected model when an operator doesn't supply a score explicitly (see
# ContinuousLearningOrchestrator.run_cycle / auto_score). It never affects the
# separate human-approval gate required before any candidate is promoted.
CONTINUOUS=ContinuousLearningOrchestrator('data/continuous_learning',evaluator_model=runtime.model)
OWNER=OwnerControl('data/security/owner_control.jsonl')
CODE_EVAL=SandboxedCodeEvaluator()
REGRESSIONS=RegressionCapture('data/regression_queue')
# Research is off by default and stays off unless an operator sets
# security.allow_network=true AND lists specific hostnames in
# security.allowed_domains in configs/default.json -- see research_gate.py.
# Even then, /code/solve only ever curates a ground-truth-verified candidate;
# promotion still requires an explicit owner-gated approval, exactly as before.
_SECURITY_CFG=Config.load('configs/default.json').get('security',{})
RESEARCH_GATE=ResearchGate(Policy(_SECURITY_CFG))
# Closes the loop end to end: generate -> optional policy-gated research ->
# ground-truth verify in the sandbox -> curate. Reuses the same connected model
# and evaluator as everything above; still only ever curates (register_batch),
# never promotes.
_CODE_CFG=Config.load('configs/default.json').get('continuous_training', {}).get('code_learning', {})
CODE_LEARNING=CodeLearningPipeline(runtime.model,CONTINUOUS,CODE_EVAL,research_gate=RESEARCH_GATE,
    n=int(_CODE_CFG.get('candidates', 5)), max_repairs=int(_CODE_CFG.get('max_repairs', 4)),
    adversarial_rounds=int(_CODE_CFG.get('adversarial_rounds', 2)), auto_repair=bool(_CODE_CFG.get('auto_repair', True)))
STATIC=Path(__file__).parent/'static'

# --- Command Chat brain (Agent) ↔ heart (core services) -----------------
COMMAND_AUDIT = CommandAuditLog('data/security/command_audit.jsonl')
COMMAND_MEMORY = CommandMemoryService(runtime.memory, 'data/command_chat.sqlite3')

# --- Coding Academy / Coding Intelligence -----------------------------
CODING_CURRICULUM = CurriculumEngine('configs/coding')
CODING_PROFILES = SkillProfileStore('data/coding_academy/profiles.sqlite3', CODING_CURRICULUM)
CODING_MEMORY = CodingAcademyMemory(COMMAND_MEMORY)
CODING_AGENT = CodingAgent(model=runtime.model, curriculum=CODING_CURRICULUM, profiles=CODING_PROFILES, academy_memory=CODING_MEMORY)
CODING_SANDBOX = SandboxedCodeEvaluator()
CODING_TRAINING = CodingTrainingScaffold('data/coding_academy/training_scaffold')

def _tool_propose_improvement(topic: str = ''):
    status = continuous_gate_status()
    return {
        'topic': topic or 'general',
        'suggestions': [
            'Keep continuous learning on memory/feedback only unless owner explicitly starts weight training offline.',
            'Review /metrics errors and regression queue before promoting any candidate.',
            'Confirm owner secret rotation and research allowlist remain deny-by-default.',
        ],
        'continuous_gate': status,
        'note': 'Suggestion only — no production mutation performed.',
    }

def _tool_remember_knowledge(kind: str = 'approved_knowledge', content: str = ''):
    if not str(content).strip():
        raise ValueError('content is required')
    mid = COMMAND_MEMORY.remember(kind, content.strip(), source='command_chat_approved')
    return {'memory_id': mid, 'kind': kind}

def _tool_forget_memory(memory_id: int):
    ok = COMMAND_MEMORY.forget(int(memory_id))
    if not ok:
        raise ValueError('memory not found')
    return {'forgotten': True, 'memory_id': int(memory_id)}

def _tool_correct_memory(memory_id: int, content: str = ''):
    if not str(content).strip():
        raise ValueError('content is required')
    ok = COMMAND_MEMORY.correct(int(memory_id), content.strip())
    if not ok:
        raise ValueError('memory not found')
    return {'corrected': True, 'memory_id': int(memory_id)}

def _tool_save_owner_correction(content: str = ''):
    if not str(content).strip():
        raise ValueError('content is required')
    mid = COMMAND_MEMORY.remember('correction', content.strip(), source='owner_correction', confidence=0.95)
    return {'memory_id': mid, 'kind': 'correction'}

def _tool_continuous_start():
    if not is_continuous_enabled():
        raise RuntimeError('continuous training disabled by config/env gate')
    return CONTINUOUS.start()

def _tool_continuous_resume():
    if not is_continuous_enabled():
        raise RuntimeError('continuous training disabled by config/env gate')
    return CONTINUOUS.resume()

def _tool_run_sandbox(code: str = '', test_code: str = ''):
    r = CODING_SANDBOX.evaluate(code or '', test_code or '')
    return {
        'passed': r.passed, 'static_passed': r.static_passed, 'executed': r.executed,
        'timed_out': r.timed_out, 'stdout': r.stdout, 'stderr': r.stderr,
        'score': r.score, 'reason': r.reason,
    }

def _tool_coding_teach(track_id: str = 'python', goal: str = '', owner: str = 'owner'):
    return CODING_AGENT.tutor.start_path(owner, track_id or 'python', goal=goal or track_id)

def _tool_coding_review(code: str = '', language: str = 'python'):
    return CODING_AGENT.reviewer.review(code or '', language=language or 'python')

CODING_TOOL_SPECS = list(DEFAULT_TOOLS) + [
    ToolSpec('run_sandbox', 'Execute learner code in isolated Python sandbox', 'write', False, {'code': 'string', 'test_code': 'string?'}),
    ToolSpec('coding_tracks', 'List extensible coding curriculum tracks', 'read', False, {}),
    ToolSpec('coding_teach', 'Build personalized learning path for a track', 'read', False, {'track_id': 'string', 'goal': 'string?', 'owner': 'string?'}),
    ToolSpec('coding_review', 'Static/security/maintainability code review', 'read', False, {'code': 'string', 'language': 'string?'}),
    ToolSpec('coding_assess', 'Return skill assessment questions', 'read', False, {}),
    ToolSpec('coding_progress', 'Learner coding progress snapshot', 'read', False, {'owner': 'string?'}),
    ToolSpec('coding_projects', 'List project-based learning catalog', 'read', False, {'level': 'string?'}),
    ToolSpec('coding_knowledge', 'Search coding knowledge base', 'read', False, {'q': 'string', 'limit': 'int?'}),
]

TOOL_ROUTER = ToolRouter({
    'health_check': lambda: runtime.health(extra={'continuous': continuous_gate_status()}),
    'system_status': lambda: {
        'health': runtime.health(extra={'continuous': continuous_gate_status()}),
        'metrics': runtime.metrics.snapshot(),
        'deployments': runtime.deploy.history(),
        'recovery': {'history_valid': RECOVERY.verify_history(), 'drills': RECOVERY.history()},
        'continuous_gate': continuous_gate_status(),
        'version': __version__,
    },
    'metrics_snapshot': lambda: runtime.metrics.snapshot(),
    'modules_list': lambda: {'modules': [
        'reasoning','memory','vector_memory','rag','command_chat','command_agent','tool_router',
        'command_memory','continuous_learning_orchestrator','code_learning_pipeline',
        'coding_agent','coding_tutor','coding_curriculum','coding_academy'
    ]},
    'continuous_status': lambda: {**CONTINUOUS.status(), 'gate': continuous_gate_status(), 'auto_promote': False},
    'deployments_list': lambda: {'items': runtime.deploy.history()},
    'knowledge_search': lambda q='', limit=5: {'results': runtime.store.search(q, int(limit or 5))},
    'memory_search': lambda q='', limit=5: {'results': COMMAND_MEMORY.relevant(q, int(limit or 5))},
    'recovery_verify': lambda: {'valid': RECOVERY.verify_history(), 'history_path': str(RECOVERY.history_path)},
    'research_verify': lambda: {
        'valid': RESEARCH_GATE.verify_chain(), 'ledger_path': str(RESEARCH_GATE.ledger),
        'network_enabled': RESEARCH_GATE.policy.network,
        'allowed_domains': sorted(RESEARCH_GATE.policy.domains),
    },
    'regression_pending': lambda: {'items': REGRESSIONS.pending()},
    'chat_audit_recent': lambda limit=20: {'items': COMMAND_AUDIT.recent(int(limit or 20))},
    'propose_improvement': _tool_propose_improvement,
    'continuous_start': _tool_continuous_start,
    'continuous_pause': CONTINUOUS.pause,
    'continuous_resume': _tool_continuous_resume,
    'continuous_stop': lambda: CONTINUOUS.stop('stopped via command chat'),
    'remember_knowledge': _tool_remember_knowledge,
    'forget_memory': _tool_forget_memory,
    'correct_memory': _tool_correct_memory,
    'save_owner_correction': _tool_save_owner_correction,
    'run_sandbox': _tool_run_sandbox,
    'coding_tracks': lambda: {'tracks': CODING_CURRICULUM.list_tracks()},
    'coding_teach': _tool_coding_teach,
    'coding_review': _tool_coding_review,
    'coding_assess': lambda: CODING_PROFILES.start_assessment(),
    'coding_progress': lambda owner='owner': CODING_PROFILES.progress(owner),
    'coding_projects': lambda level='': {'projects': CODING_CURRICULUM.projects(level or None)},
    'coding_knowledge': lambda q='', limit=8: {'results': CODING_CURRICULUM.knowledge_search(q, int(limit or 8))},
}, specs=CODING_TOOL_SPECS)
COMMAND_AGENT = CommandAgent(TOOL_ROUTER, COMMAND_MEMORY, COMMAND_AUDIT, model=runtime.model)
COMMAND_AGENT.coding_agent = CODING_AGENT
log.info('command chat brain ready provider_probe=%s', COMMAND_AGENT.provider_name())
log.info('coding academy ready provider_probe=%s tracks=%s', CODING_AGENT.provider_name(), len(CODING_CURRICULUM.list_tracks()))

@app.middleware('http')
async def request_log_middleware(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception('unhandled_error method=%s path=%s', request.method, request.url.path)
        raise
    ms = (time.perf_counter() - started) * 1000
    if request.url.path != '/health':
        log.info('request method=%s path=%s status=%s duration_ms=%.1f',
                 request.method, request.url.path, response.status_code, ms)
    return response

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log.warning('validation_error path=%s detail=%s', request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={'detail': exc.errors()})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Let FastAPI/Starlette keep their dedicated handlers for HTTPException.
    if isinstance(exc, HTTPException):
        raise exc
    log.exception('unhandled_exception path=%s', request.url.path)
    return JSONResponse(status_code=500, content={'detail': 'internal server error'})


def require_owner(x_owner_secret: str | None = Header(default=None, alias='X-Owner-Secret')) -> str:
    """Gate for governance-level actions (deploy, promote, rollback, recovery drills,
    continuous-learning approvals/lifecycle). Requires PFAI_OWNER_EMAIL and
    PFAI_OWNER_SECRET_HASH to be configured outside source (see .env.example), and the
    caller to present the matching plaintext secret in the X-Owner-Secret header.
    Every attempt (success or failure) is written to the tamper-evident owner ledger."""
    if not OWNER.owner_email():
        raise HTTPException(503, 'owner identity not configured: set PFAI_OWNER_EMAIL')
    if not OWNER.authenticate(x_owner_secret or ''):
        raise HTTPException(401, 'missing or incorrect X-Owner-Secret header')
    return OWNER.owner_email()

@app.get('/owner/identity')
def owner_identity(owner: str = Depends(require_owner)):
    """Non-sensitive: who the configured owner is and whether a secret has been set.
    Never returns the secret or its hash."""
    return OWNER.identity()
class Ask(BaseModel): question:str
class Remember(BaseModel): content:str; kind:str='fact'; source:str=''; confidence:float=.5
class Knowledge(BaseModel): content:str; source:str='manual'; metadata:dict={}
class Canary(BaseModel): version:str; traffic:float=.1
class LearningExample(BaseModel): instruction:str; response:str; source:str='api'; track:str|None=None; metadata:dict={}
class IngestBatch(BaseModel): items:list[LearningExample]
class CodeCheck(BaseModel): code:str; test_code:str=''
class CodeBestOfN(BaseModel): candidates:list[str]; test_code:str=''
class CodeSolve(BaseModel): instruction:str; test_code:str; source:str='api'; reference_urls:list[str]=[]
class RegressionCaptureRequest(BaseModel): title:str; broken_code:str; fixed_code:str; test_code:str
class RunCycle(BaseModel):
    version:str
    score:float|None=None
    notes:str=''
@app.get('/health')
def health():
    return runtime.health(extra={
        'owner_configured': bool(OWNER.owner_email()) and bool(os.environ.get('PFAI_OWNER_SECRET_HASH')),
        'continuous': continuous_gate_status(),
        'network_enabled': RESEARCH_GATE.policy.network,
    })

@app.get('/system')
def system():
    return {
        'health': health(),
        'metrics': runtime.metrics.snapshot(),
        'deployments': runtime.deploy.history(),
        'recovery': {
            'history_valid': RECOVERY.verify_history(),
            'drills': RECOVERY.history(),
        },
        'continuous_gate': continuous_gate_status(),
        'version': __version__,
    }

@app.get('/modules')
def modules():
    return {'modules': [
        'reasoning','memory','vector_memory','rag','agents','research','evaluation_lab',
        'model_lab','model_registry','model_upgrade_gate','global_orchestrator',
        'global_fabric','distributed_research_fabric','global_job_scheduler',
        'project_scheduler','recovery_scheduler','disaster_recovery','backup_manager',
        'forensic_recovery','persistent_ledger','security_sentinel','security_autonomy',
        'adaptive_defense','active_defense','threat_intelligence','security_knowledge_graph',
        'security_learning','zero_trust_gateway','permission_gate','runtime_security',
        'owner_control','policy','control_plane','continuous_training','synthetic_lab',
        'learning_loop','learning_curriculum','data_factory','data_acquisition',
        'resource_intelligence','gpu_orchestrator','command_center','metrics',
        'continuous_learning_orchestrator','learning_curriculum','data_acquisition','learning_loop',
        'code_execution_evaluator','code_best_of_n','regression_capture','code_learning_pipeline'
    ]}
@app.get('/metrics')
def metrics(): return runtime.metrics.snapshot()
@app.post('/memory')
def remember(x:Remember, owner: str = Depends(require_owner)): runtime.memory.add(x.kind,x.content,x.source,x.confidence); return {'ok':True}
@app.post('/knowledge')
def knowledge(x:Knowledge, owner: str = Depends(require_owner)): runtime.store.add(x.content,x.source,x.metadata); return {'ok':True}
@app.get('/knowledge/search')
def ksearch(q:str,limit:int=5): return {'results':runtime.store.search(q,limit)}
@app.post('/ask')
def ask(x:Ask, owner: str = Depends(require_owner)):
    if not x.question.strip(): raise HTTPException(400,'question is required')
    return runtime.ask(x.question)
@app.post('/deploy/canary')
def canary(x:Canary, owner:str=Depends(require_owner)):
    OWNER.authorize('DEPLOY_CANARY', f'{owner} requested canary {x.version}@{x.traffic}')
    return runtime.deploy.canary(x.version,x.traffic)
@app.post('/deploy/promote/{version}')
def promote(version:str, owner:str=Depends(require_owner)):
    if not runtime.deploy.promote(version): raise HTTPException(404,'candidate/canary not found')
    OWNER.authorize('DEPLOY_PROMOTE', f'{owner} promoted {version}')
    return {'ok':True,'active':runtime.registry.active()}
@app.post('/deploy/rollback/{version}')
def rollback(version:str, owner:str=Depends(require_owner)):
    if not runtime.deploy.rollback(version): raise HTTPException(404,'deployment not found')
    OWNER.authorize('DEPLOY_ROLLBACK', f'{owner} rolled back to {version}')
    return {'ok':True}
@app.get('/deployments')
def deployments(): return {'items':runtime.deploy.history()}

@app.get('/continuous/status')
def continuous_status():
    status = CONTINUOUS.status()
    status['gate'] = continuous_gate_status()
    status['auto_promote'] = False
    status['require_human_approval'] = True
    return status

@app.get('/continuous/auto_score')
def continuous_auto_score(limit:int|None=None, owner: str = Depends(require_owner)): return CONTINUOUS.auto_score(limit)

@app.post('/continuous/ingest')
def continuous_ingest(x: IngestBatch, owner: str = Depends(require_owner)):
    rows=[{'instruction':i.instruction,'response':i.response,'source':i.source,'track':i.track,'metadata':i.metadata} for i in x.items]
    return CONTINUOUS.register_batch(rows)

@app.post('/continuous/cycle')
def continuous_cycle(x: RunCycle, owner: str = Depends(require_owner)):
    result=CONTINUOUS.run_cycle(x.version, x.score, x.notes)
    if not result.get('evaluated'):
        raise HTTPException(409, result.get('reason','cycle rejected'))
    return result

@app.post('/continuous/start')
def continuous_start(owner:str=Depends(require_owner)):
    if not is_continuous_enabled():
        raise HTTPException(409, 'continuous training disabled by config/env gate')
    OWNER.authorize('CONTINUOUS_START', f'{owner} started the continuous-training service')
    log.info('continuous_start owner=%s', owner)
    return CONTINUOUS.start()
@app.post('/continuous/pause')
def continuous_pause(owner:str=Depends(require_owner)):
    OWNER.authorize('CONTINUOUS_PAUSE', f'{owner} paused the continuous-training service')
    log.info('continuous_pause owner=%s', owner)
    return CONTINUOUS.pause()
@app.post('/continuous/resume')
def continuous_resume(owner:str=Depends(require_owner)):
    if not is_continuous_enabled():
        raise HTTPException(409, 'continuous training disabled by config/env gate')
    OWNER.authorize('CONTINUOUS_RESUME', f'{owner} resumed the continuous-training service')
    log.info('continuous_resume owner=%s', owner)
    return CONTINUOUS.resume()
@app.post('/continuous/stop')
def continuous_stop(owner:str=Depends(require_owner)):
    OWNER.authorize('CONTINUOUS_STOP', f'{owner} stopped the continuous-training service')
    log.info('continuous_stop owner=%s', owner)
    return CONTINUOUS.stop(f'stopped by {owner}')

@app.post('/continuous/approve/{version}')
def continuous_approve(version:str, owner:str=Depends(require_owner)):
    if not CONTINUOUS.approve(version): raise HTTPException(404,'no pending candidate with that version')
    OWNER.authorize('CONTINUOUS_APPROVE', f'{owner} approved candidate {version}')
    log.info('continuous_approve owner=%s version=%s', owner, version)
    return {'ok':True}
@app.post('/continuous/reject/{version}')
def continuous_reject(version:str, owner:str=Depends(require_owner)):
    if not CONTINUOUS.reject(version): raise HTTPException(404,'no pending candidate with that version')
    OWNER.authorize('CONTINUOUS_REJECT', f'{owner} rejected candidate {version}')
    log.info('continuous_reject owner=%s version=%s', owner, version)
    return {'ok':True}
@app.post('/continuous/promote/{version}')
def continuous_promote(version:str, owner:str=Depends(require_owner)):
    if not CONTINUOUS.promote(version): raise HTTPException(404,'candidate must be approved before promotion')
    OWNER.authorize('CONTINUOUS_PROMOTE', f'{owner} promoted candidate {version}')
    log.info('continuous_promote owner=%s version=%s', owner, version)
    return {'ok':True,'active':CONTINUOUS.loop.active()}
@app.post('/continuous/rollback')
def continuous_rollback(version:str|None=None, owner:str=Depends(require_owner)):
    if not CONTINUOUS.rollback(version): raise HTTPException(404,'no accepted candidate to roll back to')
    OWNER.authorize('CONTINUOUS_ROLLBACK', f'{owner} rolled back continuous learning to {version or "previous"}')
    log.info('continuous_rollback owner=%s version=%s', owner, version)
    return {'ok':True,'active':CONTINUOUS.loop.active()}


@app.post('/code/evaluate')
def code_evaluate(x: CodeCheck, owner: str = Depends(require_owner)):
    """Ground-truth sandboxed execution, not a heuristic guess -- see
    code_execution_evaluator.py. Read-only: never writes anything, so no owner
    gate is needed, same as /continuous/auto_score."""
    from dataclasses import asdict as _asdict
    return _asdict(CODE_EVAL.evaluate(x.code, x.test_code))

@app.post('/code/best_of_n')
def code_best_of_n(x: CodeBestOfN, owner: str = Depends(require_owner)):
    """Evaluate several candidate solutions in the sandbox and return the best
    passing one, if any. Read-only, same reasoning as /code/evaluate."""
    from dataclasses import asdict as _asdict
    r = select_best_solution(x.candidates, x.test_code, CODE_EVAL)
    return {'best_index': r.best_index, 'best_code': r.best_code,
            'passing_indices': r.passing_indices,
            'results': [_asdict(res) for res in r.results]}

@app.post('/code/solve')
def code_solve(x: CodeSolve, owner: str = Depends(require_owner)):
    """Closes the full code-learning loop: the connected model proposes several
    candidate solutions, every one is ground-truth checked in the sandbox (never
    graded by how plausible it looks), and only a genuinely passing candidate is
    curated as a training example. Never promotes anything -- the curated example
    still needs an explicit /continuous/cycle + /continuous/approve, exactly like
    any example added via /continuous/ingest.

    reference_urls is optional. Each one is only ever fetched if the operator has
    set security.allow_network=true AND listed that exact hostname in
    security.allowed_domains in configs/default.json (see research_gate.py) -- by
    default this list is empty, so passing URLs here is a no-op until an operator
    explicitly opts a domain in. Every fetch attempt, allowed or denied, is
    recorded to data/security/research_ledger.jsonl, and whatever gets curated
    carries the exact source URLs and content hashes in its metadata."""
    if not x.instruction.strip() or not x.test_code.strip():
        raise HTTPException(400, 'instruction and test_code are both required')
    return CODE_LEARNING.solve_and_learn(x.instruction, x.test_code, x.source,
                                          reference_urls=x.reference_urls or None)

@app.get('/regression/pending')
def regression_pending(): return {'items': REGRESSIONS.pending()}

@app.post('/regression/capture')
def regression_capture(x: RegressionCaptureRequest, owner: str = Depends(require_owner)):
    """Queues a candidate regression test only after verifying it in the
    sandbox (broken really fails, fixed really passes). Read-only with
    respect to the live test suite -- it never touches tests/ itself."""
    return REGRESSIONS.capture(x.title, x.broken_code, x.fixed_code, x.test_code)

@app.post('/regression/materialize/{case_id}')
def regression_materialize(case_id: str, owner: str = Depends(require_owner)):
    """Owner-gated: this is the one call in this module that writes into the
    tests/ directory that PFAI's own promotion gate runs against."""
    result = REGRESSIONS.materialize(case_id)
    if not result.get('materialized'):
        raise HTTPException(404, result.get('reason', 'case not found'))
    OWNER.authorize('REGRESSION_MATERIALIZE', f'{owner} materialized regression case {case_id}')
    return result

@app.post('/regression/reject/{case_id}')
def regression_reject(case_id: str, owner: str = Depends(require_owner)):
    OWNER.authorize('REGRESSION_REJECT', f'{owner} rejected regression case {case_id}')
    return REGRESSIONS.reject(case_id)

@app.get('/')
def dashboard():
    return FileResponse(STATIC/'index.html')

@app.get('/recovery/verify')
def recovery_verify():
    return {'valid': RECOVERY.verify_history(), 'history_path': str(RECOVERY.history_path)}

@app.get('/research/verify')
def research_verify():
    """Tamper-evidence check for the research ledger (research_gate.py) -- every
    URL fetch attempt made on behalf of /code/solve, allowed or denied, is
    recorded there. Read-only, same reasoning as /recovery/verify."""
    return {'valid': RESEARCH_GATE.verify_chain(), 'ledger_path': str(RESEARCH_GATE.ledger),
            'network_enabled': RESEARCH_GATE.policy.network,
            'allowed_domains': sorted(RESEARCH_GATE.policy.domains)}

@app.get('/recovery/history')
def recovery_history():
    return {'items': RECOVERY.history()}

class RecoveryDrillRequest(BaseModel):
    snapshot: str
    expected_sha256: str | None = None

@app.post('/recovery/drill')
def recovery_drill(x: RecoveryDrillRequest, owner:str=Depends(require_owner)):
    if not x.snapshot.strip():
        raise HTTPException(400, 'snapshot is required')
    try:
        rec=RECOVERY.run(x.snapshot.strip(), x.expected_sha256)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    OWNER.authorize('RECOVERY_DRILL', f'{owner} ran a recovery drill on {x.snapshot.strip()}')
    return {'record': rec.__dict__ if hasattr(rec, '__dict__') else {'snapshot':rec.snapshot,'started_at':rec.started_at,'finished_at':rec.finished_at,'duration_ms':rec.duration_ms,'verified':rec.verified,'restored':rec.restored,'integrity_ok':rec.integrity_ok,'state_rows':rec.state_rows,'error':rec.error}}


# --- Command Chat API (Brain ↔ Heart) ---------------------------------
class ChatMessage(BaseModel):
    message: str
    conversation_id: str | None = None
    language: str | None = None

class ChatMemoryWrite(BaseModel):
    kind: str = 'approved_knowledge'
    content: str
    confidence: float = 0.8

class ChatMemoryCorrect(BaseModel):
    content: str
    confidence: float = 0.9

@app.get('/chat/tools')
def chat_tools(owner: str = Depends(require_owner)):
    return {'provider': COMMAND_AGENT.provider_name(), 'tools': TOOL_ROUTER.catalog()}

@app.get('/chat/conversations')
def chat_conversations(owner: str = Depends(require_owner), limit: int = 30):
    return {'items': COMMAND_MEMORY.list_conversations(limit)}

@app.get('/chat/conversations/{conversation_id}')
def chat_conversation(conversation_id: str, owner: str = Depends(require_owner)):
    return {
        'conversation_id': conversation_id,
        'messages': COMMAND_MEMORY.get_messages(conversation_id),
    }

@app.post('/chat/message')
def chat_message(x: ChatMessage, owner: str = Depends(require_owner)):
    if not x.message.strip():
        raise HTTPException(400, 'message is required')
    result = COMMAND_AGENT.handle(x.message.strip(), owner=owner, conversation_id=x.conversation_id, language=x.language)
    OWNER.authorize('CHAT_COMMAND', f'{owner} chat turn status={result.get("status")}')
    return result

@app.post('/chat/approve/{pending_id}')
def chat_approve(pending_id: str, owner: str = Depends(require_owner)):
    result = COMMAND_AGENT.approve(pending_id, owner=owner)
    if not result.get('ok') and result.get('error'):
        raise HTTPException(404 if 'not found' in result['error'] else 409, result['error'])
    OWNER.authorize('CHAT_APPROVE', f'{owner} approved pending {pending_id}')
    return result

@app.post('/chat/reject/{pending_id}')
def chat_reject(pending_id: str, owner: str = Depends(require_owner)):
    result = COMMAND_AGENT.reject(pending_id, owner=owner)
    if not result.get('ok') and result.get('error'):
        raise HTTPException(404, result['error'])
    OWNER.authorize('CHAT_REJECT', f'{owner} rejected pending {pending_id}')
    return result

@app.get('/chat/audit')
def chat_audit(owner: str = Depends(require_owner), limit: int = 50):
    return {'items': COMMAND_AUDIT.recent(limit)}

@app.get('/chat/memory/search')
def chat_memory_search(q: str, owner: str = Depends(require_owner), limit: int = 8):
    return {'results': COMMAND_MEMORY.relevant(q, limit)}

@app.post('/chat/memory/remember')
def chat_memory_remember(x: ChatMemoryWrite, owner: str = Depends(require_owner)):
    mid = COMMAND_MEMORY.remember(x.kind, x.content, source=f'owner:{owner}', confidence=x.confidence)
    OWNER.authorize('CHAT_MEMORY_REMEMBER', f'{owner} remembered kind={x.kind} id={mid}')
    return {'ok': True, 'memory_id': mid}

@app.post('/chat/memory/forget/{memory_id}')
def chat_memory_forget(memory_id: int, owner: str = Depends(require_owner)):
    if not COMMAND_MEMORY.forget(memory_id):
        raise HTTPException(404, 'memory not found')
    OWNER.authorize('CHAT_MEMORY_FORGET', f'{owner} forgot memory {memory_id}')
    return {'ok': True, 'forgotten': memory_id}

@app.post('/chat/memory/correct/{memory_id}')
def chat_memory_correct(memory_id: int, x: ChatMemoryCorrect, owner: str = Depends(require_owner)):
    if not COMMAND_MEMORY.correct(memory_id, x.content, confidence=x.confidence):
        raise HTTPException(404, 'memory not found')
    OWNER.authorize('CHAT_MEMORY_CORRECT', f'{owner} corrected memory {memory_id}')
    return {'ok': True, 'memory_id': memory_id}


# --- Coding Academy API -----------------------------------------------
class CodingChat(BaseModel):
    message: str
    mode: str | None = None
    code: str = ''
    language: str = 'python'

class AssessmentSubmit(BaseModel):
    answers: dict[str, int]

class ExerciseSubmit(BaseModel):
    track_id: str
    lesson_id: str
    code: str

class HintRequest(BaseModel):
    track_id: str
    lesson_id: str

class SolutionRequest(BaseModel):
    track_id: str
    lesson_id: str
    confirm: bool = False

class SandboxRequest(BaseModel):
    code: str
    test_code: str = ''

class ReviewRequest(BaseModel):
    code: str
    language: str = 'python'
    context: str = ''

class DebugStart(BaseModel):
    code: str
    test_code: str = ''
    description: str = ''

class DebugRespond(BaseModel):
    session_id: str
    hypothesis: str = ''

class ModeSet(BaseModel):
    mode: str

@app.get('/coding/tracks')
def coding_tracks(owner: str = Depends(require_owner)):
    return {'tracks': CODING_CURRICULUM.list_tracks()}

@app.get('/coding/profile')
def coding_profile(owner: str = Depends(require_owner)):
    return CODING_PROFILES.get_profile(owner)

@app.post('/coding/mode')
def coding_mode(x: ModeSet, owner: str = Depends(require_owner)):
    return CODING_PROFILES.set_mode(owner, x.mode)

@app.get('/coding/assessment')
def coding_assessment(owner: str = Depends(require_owner)):
    return CODING_PROFILES.start_assessment()

@app.post('/coding/assessment/submit')
def coding_assessment_submit(x: AssessmentSubmit, owner: str = Depends(require_owner)):
    result = CODING_PROFILES.grade_assessment(owner, x.answers)
    CODING_MEMORY.sync_from_profile(owner, result.get('profile') or {})
    OWNER.authorize('CODING_ASSESSMENT', f'{owner} completed skill assessment')
    return result

@app.post('/coding/path')
def coding_path(track_id: str = 'python', goal: str = '', owner: str = Depends(require_owner)):
    path = CODING_AGENT.tutor.start_path(owner, track_id, goal=goal)
    return path

@app.get('/coding/lesson/{track_id}/{lesson_id}')
def coding_lesson(track_id: str, lesson_id: str, owner: str = Depends(require_owner), reveal_solution: bool = False):
    return CODING_AGENT.tutor.lesson(track_id, lesson_id, reveal_solution=reveal_solution)

@app.post('/coding/hint')
def coding_hint(x: HintRequest, owner: str = Depends(require_owner)):
    return CODING_AGENT.tutor.hint(owner, x.track_id, x.lesson_id)

@app.post('/coding/exercise/submit')
def coding_exercise_submit(x: ExerciseSubmit, owner: str = Depends(require_owner)):
    return CODING_AGENT.tutor.submit_exercise(owner, x.track_id, x.lesson_id, x.code)

@app.post('/coding/solution')
def coding_solution(x: SolutionRequest, owner: str = Depends(require_owner)):
    result = CODING_AGENT.tutor.solution(owner, x.track_id, x.lesson_id, confirmed=bool(x.confirm))
    if result.get('needs_confirmation'):
        return result
    OWNER.authorize('CODING_SOLUTION_REVEAL', f'{owner} revealed solution {x.track_id}/{x.lesson_id}')
    return result

@app.post('/coding/sandbox')
def coding_sandbox(x: SandboxRequest, owner: str = Depends(require_owner)):
    return _tool_run_sandbox(x.code, x.test_code)

@app.post('/coding/review')
def coding_review(x: ReviewRequest, owner: str = Depends(require_owner)):
    return CODING_AGENT.reviewer.review(x.code, language=x.language, context=x.context)

@app.post('/coding/debug/start')
def coding_debug_start(x: DebugStart, owner: str = Depends(require_owner)):
    return CODING_AGENT.debugger.start(owner, x.code, x.test_code, x.description)

@app.post('/coding/debug/respond')
def coding_debug_respond(x: DebugRespond, owner: str = Depends(require_owner)):
    return CODING_AGENT.debugger.respond(x.session_id, x.hypothesis)

@app.get('/coding/projects')
def coding_projects(owner: str = Depends(require_owner), level: str | None = None):
    return {'projects': CODING_CURRICULUM.projects(level)}

@app.get('/coding/projects/{project_id}')
def coding_project(project_id: str, owner: str = Depends(require_owner)):
    p = CODING_CURRICULUM.get_project(project_id)
    if not p:
        raise HTTPException(404, 'project not found')
    return p

@app.get('/coding/knowledge')
def coding_knowledge(q: str = '', owner: str = Depends(require_owner), limit: int = 8):
    return {'results': CODING_CURRICULUM.knowledge_search(q, limit)}

@app.get('/coding/progress')
def coding_progress(owner: str = Depends(require_owner)):
    return CODING_PROFILES.progress(owner)

@app.get('/coding/training/status')
def coding_training_status(owner: str = Depends(require_owner)):
    return CODING_TRAINING.status()

@app.post('/coding/chat')
def coding_chat(x: CodingChat, owner: str = Depends(require_owner)):
    result = CODING_AGENT.handle(x.message, owner=owner, mode=x.mode, code=x.code, language=x.language)
    OWNER.authorize('CODING_CHAT', f'{owner} coding intent={result.get("intent")}')
    return result

@app.get('/assets/{asset_path:path}')
def dashboard_assets(asset_path: str):
    target = (STATIC / 'assets' / asset_path).resolve()
    root = (STATIC / 'assets').resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, 'asset not found')
    return FileResponse(target)
