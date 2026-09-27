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
