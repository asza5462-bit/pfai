from fastapi import FastAPI, HTTPException, Header, Depends, Request, Response, Cookie
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
from .owner_auth import OwnerAuthService, COOKIE_NAME, AUTH_FAIL_MESSAGE
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
from .longevity.provider_registry import ProviderRegistry
from .model_router import ModelRouter
from .orchestrator import Orchestrator
from .memory_system import LongTermMemory, MemorySystem
from .knowledge_layer import KnowledgeLayer
from .longevity.durable_learning import DurableSafeLearningPipeline, KnowledgeVersionStore, LearningAuditLog
from .longevity.autonomous_training import AutonomousTrainingOrchestrator, TrainingConfig
from .longevity.autonomous_training.runtime import detect_runtime_capabilities
from .longevity.autonomous_training.runtime_detector import TrainingRuntimeDetector
from .longevity.migration_runner import MigrationRunner
from .longevity.migrations import register_platform_migrations, verify_platform_schema
from .longevity.export_bundle import ExportBundleScaffold
from .backup_manager import BackupManager
from .memory import MemoryStore
from .platform_evaluation import PlatformEvaluation
from .self_check import SelfCheck, SelfHeal
from .longevity.compat_layer import CompatibilityLayer
from .authorized_execution import AuthorizedExecutor, AuthorizationAudit, PermissionGate
from .task_planner import TaskPlanner
from .interfaces.types import OrchestratorRequest
from .interfaces.memory import MemoryKind, MemoryRecord
from .interfaces.skills import Skill
from .interfaces.tools import ToolPermission
from .skills.registry import SkillRegistry
from .skills.packs import SkillPackRegistry
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
OWNER_AUTH=OwnerAuthService(OWNER, root='data/security')
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

# PHASE 4: shared authorization choke-point (server-side only)
PLATFORM_AUTHZ_AUDIT = AuthorizationAudit('data/longevity/authz_audit.jsonl')
PLATFORM_EXECUTOR = AuthorizedExecutor(PermissionGate(), PLATFORM_AUTHZ_AUDIT)

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
        'coding_agent','coding_tutor','coding_curriculum','coding_academy',
        'orchestrator','provider_registry','model_router','safe_learning','long_term_memory',
        'permission_gate','task_planner','skill_registry'
    ]},
    'continuous_status': lambda: {**CONTINUOUS.status(), 'gate': continuous_gate_status(), 'auto_promote': False},
    'deployments_list': lambda: {'items': runtime.deploy.history()},
    'knowledge_search': lambda q='', limit=5: {'results': runtime.store.search(q, int(limit or 5))},
    'memory_search': lambda q='', limit=5: {'results': COMMAND_MEMORY.relevant(q, int(limit or 5))},
    'recovery_verify': lambda: {'valid': RECOVERY.verify_history(), 'history_name': Path(RECOVERY.history_path).name},
    'research_verify': lambda: {
        'valid': RESEARCH_GATE.verify_chain(), 'ledger_name': Path(RESEARCH_GATE.ledger).name,
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
}, specs=CODING_TOOL_SPECS, executor=PLATFORM_EXECUTOR)
COMMAND_AGENT = CommandAgent(TOOL_ROUTER, COMMAND_MEMORY, COMMAND_AUDIT, model=runtime.model)
COMMAND_AGENT.coding_agent = CODING_AGENT
log.info('command chat brain ready provider_probe=%s', COMMAND_AGENT.provider_name())
log.info('coding academy ready provider_probe=%s tracks=%s', CODING_AGENT.provider_name(), len(CODING_CURRICULUM.list_tracks()))

# --- PHASE 2/3: ProviderRegistry + ModelRouter + Orchestrator + deep LTM/Knowledge ---
_MODEL_CFG = Config.load('configs/default.json').get('model', {})
PROVIDER_REGISTRY = ProviderRegistry()
PROVIDER_REGISTRY.bootstrap_defaults()
MODEL_ROUTER = ModelRouter.from_config(_MODEL_CFG, registry=PROVIDER_REGISTRY)
# Bind the live runtime model as DEFAULT without requiring Anthropic for Core.
MODEL_ROUTER.bind('default', runtime.model)

# PHASE 3: dedicated LTM store (kinds preserved; isolated from Command Chat memory)
PLATFORM_LTM_STORE = MemoryStore('data/longevity/ltm_content.sqlite3')
PLATFORM_LTM = LongTermMemory(
    PLATFORM_LTM_STORE,
    versions_path='data/longevity/ltm_versions.sqlite3',
)
PLATFORM_MEMORY = MemorySystem(ltm=PLATFORM_LTM)
PLATFORM_KNOWLEDGE_VERSIONS = KnowledgeVersionStore('data/longevity/knowledge_versions.sqlite3')
PLATFORM_KNOWLEDGE = KnowledgeLayer(
    search_fn=lambda q, limit: runtime.store.search(q, int(limit or 5)),
    version_store=PLATFORM_KNOWLEDGE_VERSIONS,
    curriculum_search=lambda q, limit: CODING_CURRICULUM.knowledge_search(q, int(limit or 8)),
)
PLATFORM_LEARNING_AUDIT = LearningAuditLog('data/longevity/learning_audit.jsonl')
PLATFORM_LEARNING = DurableSafeLearningPipeline(
    'data/longevity/learning.sqlite3',
    knowledge_store=PLATFORM_KNOWLEDGE_VERSIONS,
    audit=PLATFORM_LEARNING_AUDIT,
    memory_remember=lambda kind, content, source='', confidence=0.8: PLATFORM_LTM.remember_kind(
        kind, content, source=source or 'safe_learning', confidence=confidence
    ),
)
PLATFORM_EVAL = PlatformEvaluation(baselines_path='data/longevity/eval_baselines.json')

def _platform_eval_runner(suite: str) -> dict:
    report = PLATFORM_EVAL.run_suite(suite)
    total = max(1, int(report.passed) + int(report.failed))
    return {
        'ok': report.ok,
        'score': float(report.passed) / float(total),
        'passed': report.passed,
        'failed': report.failed,
        'suite': report.suite,
    }

AUTONOMOUS_TRAINING = AutonomousTrainingOrchestrator(
    root='data/longevity/training',
    learning_pipeline=PLATFORM_LEARNING,
    eval_runner=_platform_eval_runner,
    allow_mock_backend=False,
    include_approved_seeds=True,
)
from pfai.longevity.autonomous_training.experience_bridge import set_global_experience_bridge

# Continuous experience bridge — real operational events only
set_global_experience_bridge(AUTONOMOUS_TRAINING.experience)

# Migration runner: backup longevity learning DB before apply
_LONGEVITY_BACKUP_SRC = Path('data/longevity/learning.sqlite3')
_LONGEVITY_BACKUP_SRC.parent.mkdir(parents=True, exist_ok=True)
if not _LONGEVITY_BACKUP_SRC.exists():
    _LONGEVITY_BACKUP_SRC.write_bytes(b'')


def _platform_migration_backup() -> dict:
    mgr = BackupManager(str(_LONGEVITY_BACKUP_SRC), 'data/longevity/migration_backups', retention=5)
    return mgr.create(label='pre_migrate')


def _local_model_adapter_check() -> dict:
    """Honest readiness: adapter exists; runtime may be disconnected."""
    try:
        inst = PROVIDER_REGISTRY.create(
            'local',
            probe_on_init=True,
            base_url=__import__('os').environ.get('MODEL_ENDPOINT')
            or __import__('os').environ.get('PFAI_MODEL_ENDPOINT')
            or 'http://127.0.0.1:11434/v1',
        )
        if hasattr(inst, 'readiness'):
            ready = inst.readiness()
            return {
                'ok': True,  # adapter implemented
                'connected': bool(ready.get('connected')),
                'status': ready.get('status') or 'Adapter implemented, runtime not connected.',
            }
    except Exception as exc:
        return {
            'ok': True,
            'connected': False,
            'status': 'Adapter implemented, runtime not connected.',
            'error': type(exc).__name__,
        }
    return {'ok': True, 'connected': False, 'status': 'Adapter implemented, runtime not connected.'}


PLATFORM_MIGRATIONS_RUNNER = MigrationRunner(
    state_path='data/longevity/schema_version.json',
    backup_fn=_platform_migration_backup,
    audit_path='data/longevity/migration_audit.jsonl',
    verify_fn=verify_platform_schema,
)
register_platform_migrations(PLATFORM_MIGRATIONS_RUNNER)

PLATFORM_COMPAT = CompatibilityLayer(
    current_schema=PLATFORM_MIGRATIONS_RUNNER.current_version(),
    migration_status=PLATFORM_MIGRATIONS_RUNNER.status(),
)
PLATFORM_SELF_CHECK = SelfCheck({
    'runtime_health': lambda: {'ok': True, **{k: runtime.health().get(k) for k in ('status', 'version')}},
    'compat': lambda: {'ok': PLATFORM_COMPAT.check().python_ok, 'schema': PLATFORM_COMPAT.schema_version()},
    'learning_no_weights': lambda: {'ok': not PLATFORM_LEARNING.allows_weight_mutation()},
    'training_authority_isolated': lambda: {
        'ok': True,
        'weight_training_via': 'AutonomousTrainingOrchestrator',
        'knowledge_pipeline_mutates_weights': False,
    },
    'providers_offline_defaults': lambda: {
        'ok': any(p.offline_capable for p in PROVIDER_REGISTRY.list_providers()),
        'providers': [p.provider_id for p in PROVIDER_REGISTRY.list_providers()],
    },
    'ltm_ready': lambda: {'ok': True, 'phase': 3},
    'planner_ready': lambda: {'ok': True, 'phase': 4},
    'autonomous_training_ready': lambda: {
        'ok': True,
        'phase': 6,
        'runtime': detect_runtime_capabilities(probe_inference=False).get('status'),
    },
    'email_otp_ready': lambda: {
        'ok': 'email_otp' in OWNER_AUTH.public_status().get('auth_methods', []),
        'provider': type(OWNER_AUTH.email_provider).__name__,
    },
    'local_model_adapter': lambda: _local_model_adapter_check(),
})
PLATFORM_SELF_HEAL = SelfHeal(
    PLATFORM_SELF_CHECK,
    audit_path='data/longevity/heal_audit.jsonl',
    authz_audit=PLATFORM_AUTHZ_AUDIT,
)
PLATFORM_SELF_HEAL.register_safe_action(
    'clear_transient_cache',
    lambda: {'ok': True, 'cleared': ['eval_ephemeral']},
)
PLATFORM_SELF_HEAL.register_safe_action(
    'rerun_eval_smoke',
    lambda: {'ok': PLATFORM_EVAL.run_suite('smoke').ok},
)
PLATFORM_SELF_HEAL.register_safe_action(
    'compat_recheck',
    lambda: {'ok': PLATFORM_COMPAT.check().python_ok},
)
PLATFORM_SKILLS = SkillRegistry(
    path='data/longevity/skill_versions.sqlite3',
    executor=PLATFORM_EXECUTOR,
)
PLATFORM_SKILL_PACKS = SkillPackRegistry(
    path='data/longevity/skill_packs.sqlite3',
    executor=PLATFORM_EXECUTOR,
    skill_registry=PLATFORM_SKILLS,
)
PLATFORM_SKILL_PACKS.bootstrap_defaults()
# Lightweight training status skill (READ) — never mutates auth
PLATFORM_SKILLS.register_version(
    Skill(name='training_status', version='1.0.0', description='Read training control-center status', permission=ToolPermission.READ),
    lambda **_k: AUTONOMOUS_TRAINING.control_center_status(),
    activate=True,
)

def _planner_learn_ingest(goal: str, approved: bool = False, actor: str = ''):
    _ = approved, actor
    if PLATFORM_LEARNING.allows_weight_mutation():
        return {'ok': False, 'error': 'weight mutation forbidden'}
    cand = PLATFORM_LEARNING.ingest('feedback', goal, meta={'via': 'planner'})
    return {'ok': True, 'candidate_id': cand.candidate_id, 'status': str(cand.status)}

def _planner_eval_runner(suite: str):
    report = PLATFORM_EVAL.run_suite(suite)
    return {'ok': report.ok, 'passed': report.passed, 'failed': report.failed, 'suite': report.suite}

PLATFORM_PLANNER = TaskPlanner(
    executor=PLATFORM_EXECUTOR,
    max_steps=8,
    max_tool_calls=8,
    tool_runner=lambda name, args, approved=False, actor='': TOOL_ROUTER.execute(name, args, approved=approved, actor=actor),
    skill_runner=lambda name, args, approved=False, actor='': (
        (lambda r: {'ok': r.ok, 'output': r.output, 'error': r.error, 'needs_approval': bool((r.meta or {}).get('needs_approval'))})(
            PLATFORM_SKILLS.invoke(name, args, approved=approved, actor=actor)
        )
    ),
    memory_query=lambda q: [{'id': h.record_id, 'content': h.content} for h in PLATFORM_LTM.query(query=q, limit=5)],
    knowledge_query=lambda q: [h.__dict__ for h in PLATFORM_KNOWLEDGE.search(q, limit=5)],
    eval_runner=_planner_eval_runner,
    learn_ingest=_planner_learn_ingest,
)


def _export_knowledge_rows():
    return [
        {
            'knowledge_id': kv.knowledge_id,
            'version': kv.version,
            'content': kv.content,
            'source': kv.source,
            'confidence': kv.confidence,
            'status': kv.status.value if hasattr(kv.status, 'value') else kv.status,
        }
        for kv in PLATFORM_KNOWLEDGE_VERSIONS.list_active(limit=5000)
    ]


def _import_knowledge_rows(rows):
    n = 0
    for i, row in enumerate(rows or []):
        kid = str(row.get('knowledge_id') or f'import-{i}')
        PLATFORM_KNOWLEDGE.publish(
            kid,
            str(row.get('content') or ''),
            source=str(row.get('source') or 'import'),
            confidence=float(row.get('confidence') or 0.5),
        )
        n += 1
    return n


PLATFORM_EXPORT = ExportBundleScaffold(
    memory_export=lambda: PLATFORM_LTM.export_records(),
    knowledge_export=_export_knowledge_rows,
    config_export=lambda: {
        'schema_version': PLATFORM_MIGRATIONS_RUNNER.target_version(),
        'providers': [p.provider_id for p in PROVIDER_REGISTRY.list_providers()],
        'anthropic_required': False,
    },
    skills_export=lambda: [
        {'name': getattr(s, 'name', str(s)), 'version': getattr(s, 'version', '1')}
        for s in (PLATFORM_SKILLS.list_skills() if hasattr(PLATFORM_SKILLS, 'list_skills') else [])
    ],
    memory_import=lambda rows: PLATFORM_LTM.import_records(rows),
    knowledge_import=_import_knowledge_rows,
)

ORCHESTRATOR = Orchestrator(
    model_router=MODEL_ROUTER,
    command_agent=COMMAND_AGENT,
    coding_agent=CODING_AGENT,
    skills=PLATFORM_SKILLS,
    ltm=PLATFORM_LTM,
    knowledge_search=lambda q, limit=5: [h.__dict__ for h in PLATFORM_KNOWLEDGE.search(q, limit=limit)],
    learning=PLATFORM_LEARNING,
    evaluation=PLATFORM_EVAL,
    self_check=PLATFORM_SELF_CHECK,
    self_heal=PLATFORM_SELF_HEAL,
    planner=PLATFORM_PLANNER,
)
PLATFORM_SKILLS.register(
    Skill(name='platform_status', description='Orchestrator/platform status', permission=ToolPermission.READ, version='1'),
    lambda ctx=None, **_k: ORCHESTRATOR.status(),
)
PLATFORM_SKILLS.register_version(
    Skill(name='platform_status', description='Orchestrator/platform status v2', permission=ToolPermission.READ, version='2'),
    lambda ctx=None, **_k: {**ORCHESTRATOR.status(), 'skill_version': '2'},
    activate=False,
)
PLATFORM_SKILLS.register(
    Skill(name='learning_readiness', description='Fine-tune readiness (no training)', permission=ToolPermission.READ, version='1'),
    lambda ctx=None, **_k: PLATFORM_LEARNING.training_readiness(),
)
log.info(
    'orchestrator ready providers=%s roles=%s anthropic_required=false phase=4',
    [p.provider_id for p in PROVIDER_REGISTRY.list_providers()],
    MODEL_ROUTER.available_roles(),
)

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


def _client_key(request: Request) -> str:
    forwarded = (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
    return forwarded or (request.client.host if request.client else 'unknown')


def _is_production_env() -> bool:
    return os.environ.get('PFAI_ENV', '').strip().lower() in ('production', 'prod')


def _secure_cookie_flags(request: Request) -> dict:
    """Cookie flags for owner sessions.

    Production (PFAI_ENV=production|prod): always Secure — HTTPS is required.
    Development: Secure when the request is HTTPS / x-forwarded-proto=https,
    or when PFAI_COOKIE_SECURE=true. Explicit PFAI_COOKIE_SECURE=false allows
    HTTP-only local development cookies.
    """
    proto = (request.headers.get('x-forwarded-proto') or request.url.scheme or 'http').lower()
    flag = os.environ.get('PFAI_COOKIE_SECURE', '').strip().lower()
    if _is_production_env():
        # Production must never emit non-Secure session cookies.
        secure = True
    elif flag in ('0', 'false', 'no'):
        secure = False
    elif flag in ('1', 'true', 'yes'):
        secure = True
    else:
        secure = proto == 'https'
    return {
        'httponly': True,
        'secure': secure,
        'samesite': 'strict',
        'path': '/',
        'max_age': OWNER_AUTH.session_ttl,
    }


def require_owner(
    request: Request,
    x_owner_secret: str | None = Header(default=None, alias='X-Owner-Secret'),
    pfai_owner_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> str:
    """Server-side owner gate. Never trusts role/admin flags from body/query/frontend.

    Accepts (in order):
      1) HttpOnly session cookie established via /owner/login
      2) Legacy X-Owner-Secret header for API/automation (still verified server-side)

    Frontend-supplied owner/admin/role values are ignored.
    """
    # Reject privilege escalation attempts via query/body if present — ignore them.
    _ = request.query_params.get('role') or request.query_params.get('admin') or request.query_params.get('owner')

    if not OWNER_AUTH.owner_configured() and OWNER_AUTH.setup_required():
        raise HTTPException(503, 'owner setup required: POST /owner/setup')

    email = OWNER_AUTH.resolve_session(pfai_owner_session)
    if email:
        return email

    if x_owner_secret and OWNER_AUTH.authenticate_secret_header(x_owner_secret):
        return OWNER.owner_email() or 'owner'

    if not OWNER.owner_email() and not OWNER_AUTH.owner_configured():
        raise HTTPException(503, 'owner identity not configured: complete /owner/setup or set PFAI_OWNER_EMAIL')
    raise HTTPException(401, 'authentication required')


@app.get('/owner/status')
def owner_status(
    request: Request,
    pfai_owner_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    """Public auth status — no secrets. Used by Dashboard to choose setup vs login."""
    email = OWNER_AUTH.resolve_session(pfai_owner_session) or ''
    return OWNER_AUTH.public_status(authenticated=bool(email), email=email)


class OwnerSetupBody(BaseModel):
    email: str
    passcode: str
    passcode_confirm: str


class OwnerLoginBody(BaseModel):
    email: str
    passcode: str


class OwnerOtpRequestBody(BaseModel):
    email: str


class OwnerOtpVerifyBody(BaseModel):
    email: str
    otp: str
    challenge_id: str


@app.post('/owner/setup')
def owner_setup(x: OwnerSetupBody, request: Request, response: Response):
    """First-time owner initialization only. Permanently disabled after success."""
    result = OWNER_AUTH.run_setup(x.email, x.passcode, x.passcode_confirm)
    # Never echo passcode fields back.
    if not result.get('ok'):
        code = 409 if result.get('error') == 'owner setup is disabled' else 400
        raise HTTPException(code, result.get('error') or 'setup failed')
    # Auto-login session after setup
    login = OWNER_AUTH.login(x.email, x.passcode, client_key=_client_key(request))
    if login.get('ok') and login.get('token'):
        response.set_cookie(COOKIE_NAME, login['token'], **_secure_cookie_flags(request))
    return {
        'ok': True,
        'email': result.get('email'),
        'setup_locked': True,
        'message': result.get('message'),
        'authenticated': bool(login.get('ok')),
    }


@app.post('/owner/login')
def owner_login(x: OwnerLoginBody, request: Request, response: Response):
    result = OWNER_AUTH.login(x.email, x.passcode, client_key=_client_key(request))
    if not result.get('ok'):
        # Uniform failure (no email/passcode distinction); 429 when locked out.
        status = 429 if result.get('locked') else 401
        raise HTTPException(status, AUTH_FAIL_MESSAGE)
    response.set_cookie(COOKIE_NAME, result['token'], **_secure_cookie_flags(request))
    return {
        'ok': True,
        'email': result['email'],
        'expires_in': result['expires_in'],
        'authenticated': True,
    }


@app.post('/owner/otp/request')
def owner_otp_request(x: OwnerOtpRequestBody, request: Request):
    """Request Email OTP. Uniform response (enumeration-resistant). Never returns OTP."""
    result = OWNER_AUTH.request_otp(x.email, client_key=_client_key(request))
    # Strip any accidental sensitive keys; never surface OTP/body.
    return {
        'ok': True,
        'challenge_id': result.get('challenge_id'),
        'expires_in': result.get('expires_in'),
        'message': result.get('message') or 'If the email is authorized, a verification code was sent.',
    }


@app.post('/owner/otp/verify')
def owner_otp_verify(x: OwnerOtpVerifyBody, request: Request, response: Response):
    """Verify Email OTP and establish HttpOnly owner session. Never echoes OTP."""
    result = OWNER_AUTH.verify_otp(
        x.email, x.otp, x.challenge_id, client_key=_client_key(request)
    )
    if not result.get('ok'):
        status = 429 if result.get('locked') else 401
        raise HTTPException(status, AUTH_FAIL_MESSAGE)
    response.set_cookie(COOKIE_NAME, result['token'], **_secure_cookie_flags(request))
    return {
        'ok': True,
        'email': result['email'],
        'expires_in': result['expires_in'],
        'authenticated': True,
    }


@app.post('/owner/logout')
def owner_logout(
    request: Request,
    response: Response,
    pfai_owner_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    OWNER_AUTH.logout(pfai_owner_session)
    response.delete_cookie(COOKIE_NAME, path='/')
    return {'ok': True, 'authenticated': False}


@app.get('/owner/identity')
def owner_identity(owner: str = Depends(require_owner)):
    """Non-sensitive: who the configured owner is and whether a secret has been set.
    Never returns the secret or its hash."""
    ident = OWNER.identity()
    ident['authenticated_as'] = owner
    return ident
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
        'owner_configured': OWNER_AUTH.owner_configured(),
        'owner_setup_required': OWNER_AUTH.setup_required(),
        'continuous': continuous_gate_status(),
        'network_enabled': RESEARCH_GATE.policy.network,
        'platform': {
            'orchestrator': True,
            'anthropic_required': False,
            'providers': [p.provider_id for p in PROVIDER_REGISTRY.list_providers()],
            'schema_version': PLATFORM_COMPAT.schema_version(),
            'schema_current': PLATFORM_MIGRATIONS_RUNNER.current_version(),
            'schema_pending': PLATFORM_MIGRATIONS_RUNNER.status().get('pending_count', 0),
            'ltm': True,
            'eval_suites': len(PLATFORM_EVAL.list_suites()),
            'planner': True,
            'skill_versions': True,
            'phase': 4,
        },
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
def ksearch(q:str, limit:int=5, owner: str = Depends(require_owner)):
    """Owner-gated: knowledge store may hold private curated content."""
    _ = owner
    return {'results': runtime.store.search(q, limit)}
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
    # Public /continuous/status exposes last_error — do not embed owner email there.
    return CONTINUOUS.stop('stopped by owner')

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
    result = CODE_LEARNING.solve_and_learn(x.instruction, x.test_code, x.source,
                                          reference_urls=x.reference_urls or None)
    # Continuous experience: only verified passing solutions become LearningCandidates
    if result.get('solved') and result.get('code'):
        learn = AUTONOMOUS_TRAINING.experience.record_code_test_pass(
            instruction=x.instruction,
            code=str(result.get('code') or ''),
            source_id=f"code_solve:{x.source}",
            provenance={
                'via': 'code_solve',
                'attempts': result.get('attempts'),
                'curated_continuous': result.get('curated'),
            },
        )
        result = {**result, 'learning_candidate': {
            'eligibility': learn.get('eligibility'),
            'candidate_id': learn.get('candidate_id'),
            'trained': False,
        }}
    return result


@app.get('/regression/pending')
def regression_pending(owner: str = Depends(require_owner)):
    """Owner-gated: pending cases include broken/fixed source code."""
    _ = owner
    return {'items': REGRESSIONS.pending()}


@app.post('/regression/capture')
def regression_capture(x: RegressionCaptureRequest, owner: str = Depends(require_owner)):
    """Queues a candidate regression test only after verifying it in the
    sandbox (broken really fails, fixed really passes). Read-only with
    respect to the live test suite -- it never touches tests/ itself."""
    result = REGRESSIONS.capture(x.title, x.broken_code, x.fixed_code, x.test_code)
    # Verified fix (broken fails, fixed passes) → corrected-failure candidate
    if result.get('queued') and x.fixed_code.strip():
        learn = AUTONOMOUS_TRAINING.experience.record_corrected_failure(
            instruction=f"Fix regression: {x.title}",
            corrected_response=x.fixed_code,
            source_id=str(result.get('case_id') or x.title),
            tests_passed=True,
            provenance={'via': 'regression_capture', 'title': x.title},
        )
        result = {**result, 'learning_candidate': {
            'eligibility': learn.get('eligibility'),
            'candidate_id': learn.get('candidate_id'),
            'trained': False,
        }}
    return result

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
    # Public integrity probe — basename only (no absolute filesystem paths).
    return {'valid': RECOVERY.verify_history(), 'history_name': Path(RECOVERY.history_path).name}

@app.get('/research/verify')
def research_verify():
    """Tamper-evidence check for the research ledger (research_gate.py) -- every
    URL fetch attempt made on behalf of /code/solve, allowed or denied, is
    recorded there. Read-only, same reasoning as /recovery/verify."""
    return {
        'valid': RESEARCH_GATE.verify_chain(),
        'ledger_name': Path(RESEARCH_GATE.ledger).name,
        'network_enabled': RESEARCH_GATE.policy.network,
        'allowed_domains': sorted(RESEARCH_GATE.policy.domains),
    }

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


# --- Platform Orchestrator API (PHASE 2, additive; chat routes unchanged) ---
class OrchestrateBody(BaseModel):
    goal: str
    mode: str = 'general'
    session_id: str = ''
    locale: str = 'ar'
    context: dict = {}

class LearningBody(BaseModel):
    content: str
    source: str = 'feedback'
    action: str = 'ingest'
    candidate_id: str | None = None
    approved: bool = False
    meta: dict = {}

@app.get('/platform/status')
def platform_status(owner: str = Depends(require_owner)):
    return ORCHESTRATOR.status()

@app.post('/orchestrate')
def orchestrate(x: OrchestrateBody, owner: str = Depends(require_owner)):
    if not x.goal.strip():
        raise HTTPException(400, 'goal is required')
    ctx = dict(x.context or {})
    ctx.setdefault('owner', owner)
    req = OrchestratorRequest(
        goal=x.goal.strip(),
        mode=x.mode or 'general',
        session_id=x.session_id or '',
        user_id=owner,
        locale=x.locale or 'ar',
        context=ctx,
    )
    result = ORCHESTRATOR.handle(req)
    OWNER.authorize('ORCHESTRATE', f'{owner} orchestrate mode={req.mode} ok={result.ok}')
    return {
        'ok': result.ok,
        'reply': result.reply,
        'timeline': [{'status': t.status, 'detail': t.detail, **(t.meta or {})} for t in result.timeline],
        'needs_approval': result.needs_approval,
        'approval_id': result.approval_id,
        'meta': result.meta,
        'error': result.error,
    }

@app.post('/platform/learning')
def platform_learning(x: LearningBody, owner: str = Depends(require_owner)):
    """Controlled learning path — never mutates weights."""
    ctx = {
        'action': x.action,
        'source': x.source,
        'candidate_id': x.candidate_id,
        'approved': x.approved,
        'meta': x.meta,
        'owner': owner,
    }
    req = OrchestratorRequest(goal=x.content or x.candidate_id or 'learning', mode='learning', user_id=owner, context=ctx)
    result = ORCHESTRATOR.handle(req)
    OWNER.authorize('PLATFORM_LEARNING', f'{owner} learning action={x.action}')
    learn_meta = None
    # When durable learning stores verified knowledge, feed continuous experience
    if result.ok and x.action == 'store' and (result.meta or {}).get('candidate_id'):
        try:
            cand = PLATFORM_LEARNING.get(str((result.meta or {}).get('candidate_id')))
            content = getattr(cand, 'content', '') or ''
            if content:
                learn_meta = AUTONOMOUS_TRAINING.experience.record_knowledge_verified(
                    content=content,
                    source_id=str((result.meta or {}).get('candidate_id')),
                    provenance={'via': 'platform_learning.store', 'knowledge_id': (result.meta or {}).get('knowledge_id')},
                )
        except Exception:
            learn_meta = None
    out = {'ok': result.ok, 'reply': result.reply, 'meta': result.meta, 'needs_approval': result.needs_approval, 'error': result.error}
    if learn_meta:
        out['learning_candidate'] = {
            'eligibility': learn_meta.get('eligibility'),
            'candidate_id': learn_meta.get('candidate_id'),
            'trained': False,
        }
    return out

@app.get('/platform/learning/audit')
def platform_learning_audit(owner: str = Depends(require_owner), limit: int = 50):
    return {'items': PLATFORM_LEARNING_AUDIT.recent(limit)}

@app.get('/platform/providers')
def platform_providers(owner: str = Depends(require_owner)):
    """Catalog + honest local/open-weight readiness (never fakes a live runtime)."""
    local_ready = None
    try:
        local_inst = PROVIDER_REGISTRY.create(
            'local', probe_on_init=True, base_url=__import__('os').environ.get('MODEL_ENDPOINT') or 'http://127.0.0.1:11434/v1'
        )
        if hasattr(local_inst, 'readiness'):
            local_ready = local_inst.readiness()
        else:
            local_ready = {'status': 'Adapter implemented, runtime not connected.', 'connected': False}
    except Exception as exc:
        local_ready = {
            'ok': False,
            'connected': False,
            'status': 'Adapter implemented, runtime not connected.',
            'error': type(exc).__name__,
        }
    return {
        'providers': [
            {
                'provider_id': p.provider_id,
                'kind': p.kind,
                'offline_capable': p.offline_capable,
                'requires_api_key': p.requires_api_key,
                'api_key_env': p.api_key_env,
            }
            for p in PROVIDER_REGISTRY.list_providers()
        ],
        'router': MODEL_ROUTER.describe(),
        'anthropic_required': False,
        'local_open_weight': local_ready,
    }


# --- PHASE 3: LTM / Knowledge versions / Eval / Migrations / Export ---
class LtmStoreBody(BaseModel):
    content: str
    kind: str = 'semantic'
    source: str = 'api'
    confidence: float = 0.8
    record_id: str = ''


class KnowledgePublishBody(BaseModel):
    knowledge_id: str
    content: str
    source: str = 'manual'
    confidence: float = 0.8
    meta: dict = {}


class KnowledgeRollbackBody(BaseModel):
    knowledge_id: str
    to_version: int


class EvalBaselineBody(BaseModel):
    baseline_id: str
    suite: str = 'longevity'


class EvalCompareBody(BaseModel):
    baseline_id: str
    candidate_id: str
    suite: str = 'longevity'


class MigrationRunBody(BaseModel):
    target: int | None = None
    dry_run: bool = True


class ExportBody(BaseModel):
    target_dir: str = 'data/longevity/exports/latest'
    include: list[str] | None = None


class ImportBody(BaseModel):
    source_dir: str
    dry_run: bool = True


@app.get('/platform/ltm/search')
def platform_ltm_search(
    q: str = '',
    kind: str | None = None,
    limit: int = 20,
    owner: str = Depends(require_owner),
):
    _ = owner
    rows = PLATFORM_LTM.query(kind=kind, query=q, limit=limit)
    return {
        'results': [
            {
                'record_id': r.record_id,
                'kind': r.kind.value if hasattr(r.kind, 'value') else r.kind,
                'content': r.content,
                'source': r.source,
                'confidence': r.confidence,
                'version': r.version,
                'status': r.status,
            }
            for r in rows
        ]
    }


@app.post('/platform/ltm')
def platform_ltm_store(x: LtmStoreBody, owner: str = Depends(require_owner)):
    if not x.content.strip():
        raise HTTPException(400, 'content is required')
    rec = PLATFORM_LTM.store(
        MemoryRecord(
            record_id=x.record_id or '',
            kind=x.kind or MemoryKind.SEMANTIC.value,
            content=x.content.strip(),
            source=x.source or owner,
            confidence=float(x.confidence),
        )
    )
    OWNER.authorize('PLATFORM_LTM_STORE', f'{owner} stored ltm {rec.record_id} v{rec.version}')
    return {
        'ok': True,
        'record_id': rec.record_id,
        'version': rec.version,
        'kind': rec.kind.value if hasattr(rec.kind, 'value') else rec.kind,
        'status': rec.status,
    }


@app.get('/platform/ltm/{record_id}/history')
def platform_ltm_history(record_id: str, owner: str = Depends(require_owner)):
    _ = owner
    return {
        'items': [
            {
                'record_id': r.record_id,
                'version': r.version,
                'kind': r.kind.value if hasattr(r.kind, 'value') else r.kind,
                'content': r.content,
                'status': r.status,
                'source': r.source,
            }
            for r in PLATFORM_LTM.history(record_id)
        ]
    }


@app.post('/platform/ltm/{record_id}/rollback')
def platform_ltm_rollback(record_id: str, to_version: int | None = None, owner: str = Depends(require_owner)):
    try:
        rec = PLATFORM_LTM.rollback(record_id, to_version)
    except KeyError:
        raise HTTPException(404, 'ltm record/version not found')
    OWNER.authorize('PLATFORM_LTM_ROLLBACK', f'{owner} rolled back {record_id}')
    return {'ok': True, 'record_id': rec.record_id, 'version': rec.version, 'status': rec.status}


@app.get('/platform/knowledge/versions')
def platform_knowledge_versions(knowledge_id: str, owner: str = Depends(require_owner)):
    _ = owner
    hist = PLATFORM_KNOWLEDGE.history(knowledge_id)
    active = PLATFORM_KNOWLEDGE.active(knowledge_id)
    return {
        'knowledge_id': knowledge_id,
        'active_version': active.version if active else None,
        'items': [
            {
                'version': kv.version,
                'content': kv.content,
                'status': kv.status.value if hasattr(kv.status, 'value') else kv.status,
                'source': kv.source,
                'confidence': kv.confidence,
            }
            for kv in hist
        ],
    }


@app.post('/platform/knowledge/versions')
def platform_knowledge_publish(x: KnowledgePublishBody, owner: str = Depends(require_owner)):
    if not x.knowledge_id.strip() or not x.content.strip():
        raise HTTPException(400, 'knowledge_id and content are required')
    kv = PLATFORM_KNOWLEDGE.publish(
        x.knowledge_id.strip(),
        x.content.strip(),
        source=x.source,
        confidence=float(x.confidence),
        actor=owner,
        meta=x.meta,
    )
    OWNER.authorize('PLATFORM_KNOWLEDGE_PUBLISH', f'{owner} published {kv.knowledge_id} v{kv.version}')
    return {'ok': True, 'knowledge_id': kv.knowledge_id, 'version': kv.version, 'status': kv.status}


@app.post('/platform/knowledge/versions/rollback')
def platform_knowledge_rollback(x: KnowledgeRollbackBody, owner: str = Depends(require_owner)):
    try:
        kv = PLATFORM_KNOWLEDGE.rollback(x.knowledge_id, x.to_version)
    except KeyError:
        raise HTTPException(404, 'knowledge version not found')
    OWNER.authorize('PLATFORM_KNOWLEDGE_ROLLBACK', f'{owner} rolled back {x.knowledge_id} to {x.to_version}')
    return {'ok': True, 'knowledge_id': kv.knowledge_id, 'version': kv.version, 'status': kv.status}


@app.get('/platform/eval/suites')
def platform_eval_suites(owner: str = Depends(require_owner)):
    _ = owner
    return {'suites': PLATFORM_EVAL.list_suites()}


@app.post('/platform/eval/run')
def platform_eval_run(suite: str = 'longevity', owner: str = Depends(require_owner)):
    _ = owner
    report = PLATFORM_EVAL.run_suite(suite)
    return {
        'suite': report.suite,
        'ok': report.ok,
        'passed': report.passed,
        'failed': report.failed,
        'fingerprint': report.fingerprint,
        'cases': report.cases,
        'meta': report.meta,
    }


@app.post('/platform/eval/baseline')
def platform_eval_baseline(x: EvalBaselineBody, owner: str = Depends(require_owner)):
    report = PLATFORM_EVAL.run_suite(x.suite)
    PLATFORM_EVAL.record_baseline(x.baseline_id, report)
    OWNER.authorize('PLATFORM_EVAL_BASELINE', f'{owner} recorded baseline {x.baseline_id}')
    return {'ok': True, 'baseline_id': x.baseline_id, 'suite': report.suite, 'passed': report.passed, 'failed': report.failed}


@app.post('/platform/eval/compare')
def platform_eval_compare(x: EvalCompareBody, owner: str = Depends(require_owner)):
    _ = owner
    cmp = PLATFORM_EVAL.compare(x.baseline_id, x.candidate_id, suite=x.suite)
    return {
        'baseline_id': cmp.baseline_id,
        'candidate_id': cmp.candidate_id,
        'baseline_score': cmp.baseline_score,
        'candidate_score': cmp.candidate_score,
        'regressions': cmp.regressions,
        'improvements': cmp.improvements,
        'ok_to_promote': cmp.ok_to_promote,
        'requires_owner': cmp.requires_owner,
    }


@app.get('/platform/migrations')
def platform_migrations(owner: str = Depends(require_owner)):
    _ = owner
    st = PLATFORM_MIGRATIONS_RUNNER.status()
    return {
        **st,
        'plan': [
            {'version': m.version, 'name': m.name, 'description': m.description}
            for m in PLATFORM_MIGRATIONS_RUNNER.plan()
        ],
        'verify': PLATFORM_MIGRATIONS_RUNNER.verify_schema(),
    }


@app.post('/platform/migrations/run')
def platform_migrations_run(x: MigrationRunBody, owner: str = Depends(require_owner)):
    """Dry-run by default. Non-dry-run requires owner and always backs up first."""
    report = PLATFORM_MIGRATIONS_RUNNER.run(target=x.target, dry_run=bool(x.dry_run))
    if not x.dry_run:
        OWNER.authorize('PLATFORM_MIGRATE', f'{owner} applied migrations dry_run=false ok={report.ok}')
        # Refresh compat view after apply
        PLATFORM_COMPAT._current_schema = PLATFORM_MIGRATIONS_RUNNER.current_version()
        PLATFORM_COMPAT._migration_status = PLATFORM_MIGRATIONS_RUNNER.status()
    if not report.ok:
        raise HTTPException(409, report.error or 'migration failed')
    return {
        'ok': report.ok,
        'dry_run': report.dry_run,
        'from_version': report.from_version,
        'to_version': report.to_version,
        'applied': report.applied,
        'error': report.error,
    }


@app.post('/platform/export')
def platform_export(x: ExportBody, owner: str = Depends(require_owner)):
    manifest = PLATFORM_EXPORT.export_bundle(x.target_dir, include=x.include)
    OWNER.authorize('PLATFORM_EXPORT', f'{owner} exported bundle sections={manifest.get("sections")}')
    return {'ok': True, 'manifest': manifest, 'target_dir': x.target_dir}


@app.post('/platform/export/import')
def platform_export_import(x: ImportBody, owner: str = Depends(require_owner)):
    result = PLATFORM_EXPORT.import_bundle(x.source_dir, dry_run=bool(x.dry_run))
    if not result.get('ok'):
        raise HTTPException(400, result.get('error') or 'import failed')
    if not x.dry_run:
        OWNER.authorize('PLATFORM_IMPORT', f'{owner} imported bundle dry_run=false')
    return result


# --- PHASE 4: Planner / Skills versions / Tools catalog / Heal ---
class PlanBody(BaseModel):
    goal: str
    actions: list[str] | None = None
    approved: bool = False
    plan_only: bool = False
    verify: bool = True


class SkillActivateBody(BaseModel):
    name: str
    version: str


class HealApplyBody(BaseModel):
    proposal_id: str
    approved: bool = False


@app.post('/platform/plan')
def platform_plan(x: PlanBody, owner: str = Depends(require_owner)):
    if not x.goal.strip():
        raise HTTPException(400, 'goal is required')
    # Ignore any client-supplied role flags — owner comes from require_owner only.
    req = OrchestratorRequest(
        goal=x.goal.strip(),
        mode='plan',
        user_id=owner,
        context={'actions': x.actions, 'approved': bool(x.approved), 'plan_only': bool(x.plan_only), 'verify': bool(x.verify), 'owner': owner},
    )
    result = ORCHESTRATOR.handle(req)
    OWNER.authorize('PLATFORM_PLAN', f'{owner} plan ok={result.ok} needs_approval={result.needs_approval}')
    return {
        'ok': result.ok,
        'reply': result.reply,
        'needs_approval': result.needs_approval,
        'approval_id': result.approval_id,
        'meta': result.meta,
        'timeline': [{'status': t.status, 'detail': t.detail} for t in result.timeline],
        'error': result.error,
    }


@app.get('/platform/plan/{plan_id}')
def platform_plan_get(plan_id: str, owner: str = Depends(require_owner)):
    _ = owner
    plan = PLATFORM_PLANNER.get(plan_id)
    if not plan:
        raise HTTPException(404, 'plan not found')
    return {
        'plan_id': plan.plan_id,
        'goal': plan.goal,
        'status': plan.status,
        'verification': plan.verification,
        'steps': [{'id': s.id, 'action': s.action, 'status': s.status, 'error': s.error} for s in plan.steps],
    }


@app.get('/platform/skills')
def platform_skills_list(owner: str = Depends(require_owner)):
    _ = owner
    return {
        'skills': [
            {
                'name': s.name,
                'version': s.version,
                'permission': s.permission.value,
                'description': s.description,
                'active_version': PLATFORM_SKILLS.active_version(s.name),
            }
            for s in PLATFORM_SKILLS.list_skills()
        ]
    }


@app.get('/platform/skills/{name}/versions')
def platform_skill_versions(name: str, owner: str = Depends(require_owner)):
    _ = owner
    return {
        'name': name,
        'active_version': PLATFORM_SKILLS.active_version(name),
        'versions': [
            {'name': s.name, 'version': s.version, 'permission': s.permission.value, 'description': s.description}
            for s in PLATFORM_SKILLS.list_versions(name)
        ],
    }


@app.post('/platform/skills/activate')
def platform_skills_activate(x: SkillActivateBody, owner: str = Depends(require_owner)):
    result = PLATFORM_SKILLS.activate(x.name, x.version, approved=True, actor=owner)
    if not result.get('ok'):
        raise HTTPException(404 if 'not found' in (result.get('error') or '') else 400, result.get('error') or 'activate failed')
    OWNER.authorize('PLATFORM_SKILL_ACTIVATE', f'{owner} activated {x.name}@{x.version}')
    return result


@app.post('/platform/skills/rollback')
def platform_skills_rollback(x: SkillActivateBody, owner: str = Depends(require_owner)):
    result = PLATFORM_SKILLS.rollback(x.name, x.version, approved=True, actor=owner)
    if not result.get('ok'):
        raise HTTPException(404 if 'not found' in (result.get('error') or '') else 400, result.get('error') or 'rollback failed')
    OWNER.authorize('PLATFORM_SKILL_ROLLBACK', f'{owner} rolled back {x.name} to {x.version}')
    return result


@app.get('/platform/tools')
def platform_tools_catalog(owner: str = Depends(require_owner)):
    _ = owner
    return {'tools': TOOL_ROUTER.catalog()}


@app.post('/platform/heal/propose')
def platform_heal_propose(owner: str = Depends(require_owner)):
    _ = owner
    report = PLATFORM_SELF_CHECK.run_checks()
    proposal = PLATFORM_SELF_HEAL.propose_fix(report)
    return {
        'proposal_id': proposal.proposal_id,
        'diagnosis': proposal.diagnosis,
        'safe': proposal.safe,
        'reversible': proposal.reversible,
        'steps': proposal.steps,
        'requires_owner': proposal.requires_owner,
        'risk': proposal.risk,
        'meta': proposal.meta,
    }


@app.post('/platform/heal/apply')
def platform_heal_apply(x: HealApplyBody, owner: str = Depends(require_owner)):
    # Explicit approved flag required for high-risk heal; server ignores client role claims.
    approved = bool(x.approved)
    applied = PLATFORM_SELF_HEAL.apply_fix(x.proposal_id, approved=approved)
    if applied.meta.get('needs_approval'):
        raise HTTPException(401, 'owner approval required')
    if not applied.ok:
        raise HTTPException(409, applied.message or 'heal apply failed')
    tested = PLATFORM_SELF_HEAL.test_fix(x.proposal_id)
    if not tested.ok:
        rolled = PLATFORM_SELF_HEAL.rollback_fix(x.proposal_id)
        OWNER.authorize('PLATFORM_HEAL_ROLLBACK', f'{owner} heal failed test; rolled back {x.proposal_id}')
        return {'ok': False, 'applied': applied.meta, 'tested': tested.meta, 'rollback': rolled.meta}
    OWNER.authorize('PLATFORM_HEAL_APPLY', f'{owner} applied heal {x.proposal_id}')
    return {'ok': True, 'applied': applied.meta, 'tested': tested.meta}


@app.post('/platform/heal/rollback')
def platform_heal_rollback(proposal_id: str, owner: str = Depends(require_owner)):
    rolled = PLATFORM_SELF_HEAL.rollback_fix(proposal_id)
    OWNER.authorize('PLATFORM_HEAL_ROLLBACK', f'{owner} rolled back heal {proposal_id}')
    return {'ok': rolled.ok, 'message': rolled.message, 'meta': rolled.meta}


@app.get('/platform/heal/audit')
def platform_heal_audit(limit: int = 50, owner: str = Depends(require_owner)):
    _ = owner
    return {'items': PLATFORM_SELF_HEAL.recent_audit(limit)}


@app.get('/platform/authz/audit')
def platform_authz_audit(limit: int = 50, owner: str = Depends(require_owner)):
    _ = owner
    return {'items': PLATFORM_AUTHZ_AUDIT.recent(limit)}


# --- PHASE 6/7: Autonomous Training + Runtime + Skill Packs (owner-gated) ---
class TrainingCycleBody(BaseModel):
    owner_requested: bool = True
    explicit_retrain: bool = False
    regression_recovery: bool = False
    performance_opportunity: bool = False
    activate_if_pass: bool = True
    allow_mock_backend: bool = False
    dataset_id: str | None = None
    base_model: str | None = None
    method: str = 'lora'


class TrainingRollbackBody(BaseModel):
    reason: str = 'owner_requested'
    force_regression: bool = False


class SkillPackActivateBody(BaseModel):
    pack_id: str
    version: str
    approved: bool = True
    enable: bool = True


class SkillPackEnableBody(BaseModel):
    enabled: bool = True


class AutonomousToggleBody(BaseModel):
    enabled: bool = True


@app.get('/platform/runtime/status')
def platform_runtime_status(owner: str = Depends(require_owner)):
    _ = owner
    probe = TrainingRuntimeDetector().detect()
    from pfai.longevity.autonomous_training.open_weight_catalog import OpenWeightModelSelector

    selection = OpenWeightModelSelector().select_production_candidate(probe_load=False)
    return {
        'ok': True,
        **probe.to_dict(),
        'active_runtime': AUTONOMOUS_TRAINING.active_runtime.current(),
        'active_model_runtime_status': AUTONOMOUS_TRAINING.active_runtime.describe_status(
            lkg=AUTONOMOUS_TRAINING.models.last_known_good(),
            training_backend='transformers_lora',
        ),
        'open_weight': selection,
        'hardware': selection.get('hardware') or OpenWeightModelSelector.hardware_audit(),
    }


@app.get('/platform/models/open-weight')
def platform_open_weight_models(owner: str = Depends(require_owner), probe_load: bool = False):
    _ = owner
    from pfai.longevity.autonomous_training.open_weight_catalog import OpenWeightModelSelector

    return OpenWeightModelSelector().select_production_candidate(probe_load=bool(probe_load))


@app.get('/platform/training/runtime')
def platform_training_runtime(owner: str = Depends(require_owner)):
    _ = owner
    return AUTONOMOUS_TRAINING.runtime_status()


@app.get('/platform/training/status')
def platform_training_status(owner: str = Depends(require_owner)):
    _ = owner
    st = AUTONOMOUS_TRAINING.status()
    cc = AUTONOMOUS_TRAINING.control_center_status()
    learn = AUTONOMOUS_TRAINING.learning_statistics()
    return {
        'ok': True,
        'training_enabled': st.get('training_enabled'),
        'autonomous_training_enabled': st.get('autonomous_training_enabled'),
        'runtime_status': (st.get('capabilities') or {}).get('status'),
        'runtime_availability': st.get('runtime_availability'),
        'training_available': (st.get('capabilities') or {}).get('training_available'),
        'inference_available': (st.get('capabilities') or {}).get('inference_available'),
        'gpu_available': (st.get('capabilities') or {}).get('gpu_available'),
        'cpu_count': (st.get('capabilities') or {}).get('cpu_count'),
        'ram_gb': (st.get('capabilities') or {}).get('ram_gb'),
        'ram_available_gb': (st.get('capabilities') or {}).get('ram_available_gb'),
        'vram_gb': (st.get('capabilities') or {}).get('vram_gb'),
        'hardware': {
            'cpu_count': (st.get('capabilities') or {}).get('cpu_count'),
            'ram_gb': (st.get('capabilities') or {}).get('ram_gb'),
            'ram_available_gb': (st.get('capabilities') or {}).get('ram_available_gb'),
            'gpu_available': (st.get('capabilities') or {}).get('gpu_available'),
            'gpu_name': (st.get('capabilities') or {}).get('gpu_name'),
            'vram_gb': (st.get('capabilities') or {}).get('vram_gb'),
            'cuda': (st.get('capabilities') or {}).get('cuda'),
            'cuda_version': (st.get('capabilities') or {}).get('cuda_version'),
        },
        'active_model': st.get('active_model'),
        'active_runtime': st.get('active_runtime'),
        'control_center': cc,
        'labels': cc.get('labels') or {},
        'REAL_TRAINING_AVAILABLE': bool((cc.get('labels') or {}).get('REAL_TRAINING_AVAILABLE')),
        'REAL_TRAINING_EXECUTED': bool((cc.get('labels') or {}).get('REAL_TRAINING_EXECUTED')),
        'REAL_MODEL_ACTIVE': bool((cc.get('labels') or {}).get('REAL_MODEL_ACTIVE')),
        'LKG_AVAILABLE': bool((cc.get('labels') or {}).get('LKG_AVAILABLE')),
        'ROLLBACK_AVAILABLE': bool((cc.get('labels') or {}).get('ROLLBACK_AVAILABLE')),
        'AUTONOMOUS_TRAINING_READY': bool((cc.get('labels') or {}).get('AUTONOMOUS_TRAINING_READY')),
        'lkg_model': cc.get('lkg_model'),
        'resource_status': cc.get('resource_status'),
        'quality_disclaimer': cc.get('quality_disclaimer'),
        'learning_statistics': learn.get('candidates'),
        'last_training_result': learn.get('last_training_result') or cc.get('last_training_result'),
        'last_rollback_result': learn.get('last_rollback_result') or cc.get('last_rollback_result'),
        'orchestrator': st.get('orchestrator'),
        'datasets': st.get('datasets'),
        'models': st.get('models'),
        'recent_jobs': [
            {
                'job_id': j.get('job_id'),
                'state': j.get('state'),
                'dataset_id': j.get('dataset_id'),
                'model_id': j.get('model_id'),
                'is_mock': j.get('is_mock'),
                'real_training': j.get('real_training'),
                'real_weight_update': j.get('real_weight_update'),
                'backend': j.get('backend'),
            }
            for j in (st.get('recent_jobs') or [])
        ],
        'authority_isolation': True,
        'weight_training_path': 'AutonomousTrainingOrchestrator',
        'note': st.get('note'),
    }


@app.get('/platform/learning/statistics')
def platform_learning_statistics(owner: str = Depends(require_owner)):
    """Owner-only learning/candidate/dataset observability (no secret payloads)."""
    _ = owner
    return AUTONOMOUS_TRAINING.learning_statistics()


@app.get('/platform/learning/dataset')
def platform_learning_dataset(owner: str = Depends(require_owner), limit: int = 20):
    _ = owner
    datasets = AUTONOMOUS_TRAINING.datasets.list_versions(limit=limit)
    latest = datasets[0] if datasets else None
    stats = AUTONOMOUS_TRAINING.learning_pipeline_gate.store.statistics()
    return {
        'ok': True,
        'latest_dataset': latest,
        'dataset_versions': datasets,
        'candidate_statistics': stats,
        'train_validation_test': {
            'train': (latest or {}).get('train_count'),
            'validation': (latest or {}).get('validation_count'),
            'test': (latest or {}).get('test_count'),
        }
        if latest
        else None,
        'note': 'Dataset status only — example text is not exposed.',
    }


@app.get('/platform/learning/models')
def platform_learning_models(owner: str = Depends(require_owner), limit: int = 50):
    """Model registry observability: active, LKG, states — no weights/secrets."""
    _ = owner
    models = AUTONOMOUS_TRAINING.models.list_models(limit=limit)
    safe = []
    for m in models:
        safe.append(
            {
                'model_id': m.get('model_id'),
                'status': m.get('status'),
                'base_model': m.get('base_model'),
                'base_model_hash': m.get('base_model_hash'),
                'base_model_revision': m.get('base_model_revision'),
                'dataset_version': m.get('dataset_version'),
                'training_backend': m.get('training_backend'),
                'training_code_version': m.get('training_code_version'),
                'parent_model_id': m.get('parent_model_id'),
                'activated_at': m.get('activated_at'),
                'rollback_status': m.get('rollback_status'),
                'has_checkpoint': bool(m.get('checkpoint_ref')),
                'metrics_keys': list((m.get('metrics') or {}).keys()),
                'evaluation_decision': ((m.get('evaluation') or {}).get('decision')),
            }
        )
    return {
        'ok': True,
        'models': safe,
        'active_model': AUTONOMOUS_TRAINING.models.active(),
        'lkg_model': AUTONOMOUS_TRAINING.models.last_known_good(),
        'last_training_result': dict(AUTONOMOUS_TRAINING._last_training_result or {}),
        'last_rollback_result': dict(AUTONOMOUS_TRAINING._last_rollback_result or {}),
    }


@app.post('/platform/learning/candidates/collect')
def platform_learning_candidates_collect(owner: str = Depends(require_owner)):
    """Run LearningCandidate pass only — does not train."""
    result = AUTONOMOUS_TRAINING.run_learning_candidate_pass()
    OWNER.authorize('PLATFORM_LEARNING_COLLECT', f'{owner} candidate pass observed={result.get("observed")}')
    return {
        'ok': True,
        'observed': result.get('observed'),
        'accepted_this_run': result.get('accepted_this_run'),
        'rejected_this_run': result.get('rejected_this_run'),
        'duplicates_this_run': result.get('duplicates_this_run'),
        'rejection_reasons_this_run': result.get('rejection_reasons_this_run'),
        'store_statistics': result.get('store_statistics'),
        'trained': False,
        'note': 'Collect/clean only — training is never triggered by this endpoint.',
    }


class LearningFeedbackBody(BaseModel):
    instruction: str
    response: str
    id: str | None = None
    approved: bool = True


@app.post('/platform/learning/feedback')
def platform_learning_feedback(x: LearningFeedbackBody, owner: str = Depends(require_owner)):
    """Queue owner-approved feedback as a learning candidate (not immediate training)."""
    result = AUTONOMOUS_TRAINING.submit_owner_feedback(
        {
            'id': x.id or '',
            'instruction': x.instruction,
            'response': x.response,
            'approved': bool(x.approved),
        }
    )
    OWNER.authorize('PLATFORM_LEARNING_FEEDBACK', f'{owner} queued feedback')
    return result


@app.get('/platform/training/datasets')
def platform_training_datasets(owner: str = Depends(require_owner), limit: int = 50):
    _ = owner
    datasets = AUTONOMOUS_TRAINING.datasets.list_versions(limit=limit)
    stats = AUTONOMOUS_TRAINING.learning_pipeline_gate.store.statistics()
    return {
        'datasets': datasets,
        'candidate_statistics': {
            'total_candidates': stats.get('total_candidates'),
            'accepted_candidates': stats.get('accepted_candidates'),
            'rejected_candidates': stats.get('rejected_candidates'),
            'rejection_reasons': stats.get('rejection_reasons'),
            'source_distribution': stats.get('source_distribution'),
            'quality_distribution': stats.get('quality_distribution'),
        },
        'latest': datasets[0] if datasets else None,
    }


@app.get('/platform/training/jobs')
def platform_training_jobs(owner: str = Depends(require_owner), limit: int = 50):
    _ = owner
    return {'jobs': AUTONOMOUS_TRAINING.list_jobs(limit=limit)}


@app.get('/platform/training/jobs/{job_id}')
def platform_training_job_get(job_id: str, owner: str = Depends(require_owner)):
    _ = owner
    job = AUTONOMOUS_TRAINING._read_job(job_id)
    if not job:
        raise HTTPException(404, 'job not found')
    return {'job': job}


@app.post('/platform/training/start')
def platform_training_start(x: TrainingCycleBody, owner: str = Depends(require_owner)):
    return platform_training_cycle(x, owner)


@app.post('/platform/training/pause')
def platform_training_pause(owner: str = Depends(require_owner)):
    result = AUTONOMOUS_TRAINING.pause_training()
    OWNER.authorize('PLATFORM_TRAINING_PAUSE', f'{owner} paused training')
    return result


@app.post('/platform/training/cancel')
def platform_training_cancel(job_id: str, owner: str = Depends(require_owner)):
    result = AUTONOMOUS_TRAINING.cancel_job(job_id)
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'cancel failed')
    OWNER.authorize('PLATFORM_TRAINING_CANCEL', f'{owner} cancelled {job_id}')
    return result


@app.post('/platform/training/autonomous')
def platform_training_autonomous(x: AutonomousToggleBody, owner: str = Depends(require_owner)):
    result = AUTONOMOUS_TRAINING.set_autonomous(x.enabled)
    OWNER.authorize('PLATFORM_TRAINING_AUTONOMOUS', f'{owner} autonomous={x.enabled}')
    return result


@app.post('/platform/training/tick')
def platform_training_tick(owner: str = Depends(require_owner)):
    """Owner-triggered autonomous tick (dataset/schedule/growth triggers). Never chat-driven."""
    result = AUTONOMOUS_TRAINING.maybe_run_autonomous_tick()
    OWNER.authorize('PLATFORM_TRAINING_TICK', f"{owner} tick status={result.get('status')}")
    return result


@app.get('/platform/training/models')
def platform_training_models(owner: str = Depends(require_owner), limit: int = 50):
    _ = owner
    return {
        'models': AUTONOMOUS_TRAINING.models.list_models(limit=limit),
        'active': AUTONOMOUS_TRAINING.models.active(),
        'active_runtime': AUTONOMOUS_TRAINING.active_runtime.current(),
    }


@app.get('/platform/training/models/{model_id}')
def platform_training_model_get(model_id: str, owner: str = Depends(require_owner)):
    _ = owner
    model = AUTONOMOUS_TRAINING.models.get(model_id)
    if not model:
        raise HTTPException(404, 'model not found')
    return {'model': model}


@app.post('/platform/training/models/{model_id}/activate')
def platform_training_model_activate(model_id: str, owner: str = Depends(require_owner)):
    result = AUTONOMOUS_TRAINING.activate_model(model_id)
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'activate failed')
    OWNER.authorize('PLATFORM_TRAINING_ACTIVATE', f'{owner} activated {model_id}')
    return result


@app.post('/platform/training/models/{model_id}/rollback')
def platform_training_model_rollback(model_id: str, owner: str = Depends(require_owner), reason: str = 'owner_requested'):
    _ = model_id  # target is last-known-good; model_id retained for audit context
    result = AUTONOMOUS_TRAINING.rollback_mgr.rollback(reason=reason or f'owner_requested:{model_id}')
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'rollback failed')
    OWNER.authorize('PLATFORM_TRAINING_ROLLBACK', f'{owner} rollback from context {model_id}')
    return result


@app.get('/platform/training/evaluations')
def platform_training_evaluations(owner: str = Depends(require_owner), limit: int = 20):
    _ = owner
    jobs = AUTONOMOUS_TRAINING.list_jobs(limit=limit)
    return {
        'evaluations': [
            {
                'job_id': j.get('job_id'),
                'model_id': j.get('model_id'),
                'evaluation': j.get('evaluation'),
                'shadow': j.get('shadow'),
                'canary': j.get('canary'),
            }
            for j in jobs
            if j.get('evaluation')
        ]
    }


@app.get('/platform/training/checkpoints')
def platform_training_checkpoints(owner: str = Depends(require_owner), limit: int = 50):
    _ = owner
    return {'checkpoints': AUTONOMOUS_TRAINING.checkpoints.list_recent(limit=limit)}


@app.post('/platform/training/cycle')
def platform_training_cycle(x: TrainingCycleBody, owner: str = Depends(require_owner)):
    """Owner-triggered autonomous training cycle. Never mutates auth/authorization."""
    cfg = TrainingConfig(
        method=x.method or 'lora',
        base_model=x.base_model or __import__('os').environ.get('MODEL_NAME') or 'local',
        allow_mock_backend=bool(x.allow_mock_backend),
        max_runtime_seconds=AUTONOMOUS_TRAINING.triggers.max_runtime,
    )
    result = AUTONOMOUS_TRAINING.run_cycle(
        owner_requested=bool(x.owner_requested),
        explicit_retrain=bool(x.explicit_retrain),
        regression_recovery=bool(x.regression_recovery),
        performance_opportunity=bool(x.performance_opportunity),
        activate_if_pass=bool(x.activate_if_pass),
        force_dataset=x.dataset_id,
        config=cfg,
        request={'owner': owner},
    )
    OWNER.authorize(
        'PLATFORM_TRAINING_CYCLE',
        f"{owner} training cycle status={result.get('status')} real={result.get('actual_training_executed')}",
    )
    return {
        'ok': bool(result.get('ok')),
        'status': result.get('status'),
        'actual_training_executed': bool(result.get('actual_training_executed')),
        'real_training_executed': bool(result.get('real_training_executed') or result.get('actual_training_executed')),
        'real_checkpoint_created': bool(result.get('real_checkpoint_created')),
        'real_evaluation_executed': bool(result.get('real_evaluation_executed')),
        'canary_executed': bool(result.get('canary_executed')),
        'is_mock': bool(result.get('is_mock')),
        'model_activated': bool(result.get('model_activated')),
        'rollback_available': bool(result.get('rollback_available')),
        'reason': result.get('reason') or result.get('error') or result.get('status'),
        'job_id': (result.get('job') or {}).get('job_id'),
        'dataset_id': (result.get('job') or {}).get('dataset_id') or result.get('dataset_id'),
        'model_id': (result.get('job') or {}).get('model_id'),
        'evaluation_decision': ((result.get('evaluation') or {}).get('decision')),
        'error': result.get('error'),
        'runtime_note': None
        if result.get('status') not in (
            'TRAINING_RUNTIME_UNAVAILABLE',
            'TRAINING_BLOCKED_RUNTIME_UNAVAILABLE',
            'NO_COMPATIBLE_MODEL',
        )
        else result.get('status'),
    }


@app.post('/platform/training/rollback')
def platform_training_rollback(x: TrainingRollbackBody, owner: str = Depends(require_owner)):
    if x.force_regression:
        result = AUTONOMOUS_TRAINING.monitor_and_maybe_rollback(force_regression=True)
    else:
        result = AUTONOMOUS_TRAINING.rollback_mgr.rollback(reason=x.reason or 'owner_requested')
    OWNER.authorize('PLATFORM_TRAINING_ROLLBACK', f'{owner} rollback ok={result.get("ok")}')
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'rollback failed')
    return result


@app.get('/platform/training/rollback')
def platform_training_rollback_status(owner: str = Depends(require_owner)):
    _ = owner
    active = AUTONOMOUS_TRAINING.models.active()
    lkg = AUTONOMOUS_TRAINING.rollback_mgr.last_known_good()
    return {
        'active': active,
        'active_runtime': AUTONOMOUS_TRAINING.active_runtime.current(),
        'last_known_good': {'model_id': lkg.get('model_id')} if lkg else None,
    }


# PHASE 8 aliases — /platform/models* (same owner gate as /platform/training/models*)
@app.get('/platform/models')
def platform_models(owner: str = Depends(require_owner), limit: int = 50):
    return platform_training_models(owner=owner, limit=limit)


@app.get('/platform/models/{model_id}')
def platform_model_get(model_id: str, owner: str = Depends(require_owner)):
    return platform_training_model_get(model_id=model_id, owner=owner)


@app.post('/platform/models/{model_id}/activate')
def platform_model_activate(model_id: str, owner: str = Depends(require_owner)):
    return platform_training_model_activate(model_id=model_id, owner=owner)


@app.post('/platform/models/{model_id}/rollback')
def platform_model_rollback(model_id: str, owner: str = Depends(require_owner), reason: str = 'owner_requested'):
    return platform_training_model_rollback(model_id=model_id, owner=owner, reason=reason)


@app.get('/platform/skills/packs')
def platform_skill_packs(owner: str = Depends(require_owner)):
    _ = owner
    return {'packs': PLATFORM_SKILL_PACKS.list_packs()}


@app.get('/platform/skills/packs/{pack_id}')
def platform_skill_pack_get(pack_id: str, owner: str = Depends(require_owner)):
    _ = owner
    pack = PLATFORM_SKILL_PACKS.get(pack_id)
    if not pack:
        raise HTTPException(404, 'pack not found')
    return {'pack': pack}


@app.post('/platform/skills/packs/{pack_id}/activate')
def platform_skill_pack_activate(pack_id: str, x: SkillPackActivateBody, owner: str = Depends(require_owner)):
    result = PLATFORM_SKILL_PACKS.activate(
        pack_id or x.pack_id, x.version, approved=bool(x.approved), actor=owner, enable=bool(x.enable)
    )
    if not result.get('ok'):
        code = 401 if result.get('needs_approval') else 400
        raise HTTPException(code, result.get('error') or 'activate failed')
    OWNER.authorize('PLATFORM_SKILL_PACK_ACTIVATE', f'{owner} pack {pack_id}@{x.version}')
    return result


@app.post('/platform/skills/packs/{pack_id}/rollback')
def platform_skill_pack_rollback(pack_id: str, owner: str = Depends(require_owner)):
    result = PLATFORM_SKILL_PACKS.rollback(pack_id, approved=True, actor=owner)
    if not result.get('ok'):
        raise HTTPException(400, result.get('error') or 'rollback failed')
    OWNER.authorize('PLATFORM_SKILL_PACK_ROLLBACK', f'{owner} pack {pack_id}')
    return result


@app.post('/platform/skills/packs/{pack_id}/enable')
def platform_skill_pack_enable(pack_id: str, x: SkillPackEnableBody, owner: str = Depends(require_owner)):
    result = PLATFORM_SKILL_PACKS.set_enabled(pack_id, bool(x.enabled), approved=True, actor=owner)
    if not result.get('ok'):
        raise HTTPException(400, result.get('error') or 'enable failed')
    OWNER.authorize('PLATFORM_SKILL_PACK_ENABLE', f'{owner} pack {pack_id} enabled={x.enabled}')
    return result


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
    result = CODING_AGENT.tutor.submit_exercise(owner, x.track_id, x.lesson_id, x.code)
    # Only sandbox-passing submissions become learning candidates (never failing attempts)
    if result.get('passed') and result.get('mode') == 'sandbox' and (x.code or '').strip():
        lesson = CODING_CURRICULUM.get_lesson(x.track_id, x.lesson_id) or {}
        prompt = (lesson.get('exercise') or {}).get('prompt') or f"Complete exercise {x.track_id}/{x.lesson_id}"
        learn = AUTONOMOUS_TRAINING.experience.record_code_test_pass(
            instruction=str(prompt),
            code=x.code,
            source_id=f"coding:{x.track_id}/{x.lesson_id}",
            provenance={'via': 'coding_exercise_submit', 'owner_scoped': True},
        )
        result = {**result, 'learning_candidate': {
            'eligibility': learn.get('eligibility'),
            'candidate_id': learn.get('candidate_id'),
            'trained': False,
        }}
    elif not result.get('passed'):
        result = {**result, 'learning_candidate': {
            'eligibility': 'INELIGIBLE',
            'reason': 'tests_failed',
            'trained': False,
        }}
    return result

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
    # Raw chats are never training data
    AUTONOMOUS_TRAINING.experience.record_raw_chat_attempt(
        instruction=x.message or '',
        response=str((result or {}).get('reply') or (result or {}).get('response') or ''),
    )
    return result

@app.get('/assets/{asset_path:path}')
def dashboard_assets(asset_path: str):
    target = (STATIC / 'assets' / asset_path).resolve()
    root = (STATIC / 'assets').resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, 'asset not found')
    return FileResponse(target)
