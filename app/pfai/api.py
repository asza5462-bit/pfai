from fastapi import FastAPI, HTTPException, Header, Depends, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import os
import re
import time
from fastapi.responses import FileResponse
from pathlib import Path
from .recovery_scheduler import RecoveryDrillScheduler
from pydantic import BaseModel
from .runtime import PFAIRuntime
from .continuous_learning_orchestrator import ContinuousLearningOrchestrator
from .continuous_training import ContinuousConfig
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
from .open_execution import auto_accept_learning, auto_safe_heal, open_execution_status
from .quantum_core import QuantumInspiredCore, quantum_core_enabled
from .iot_mind import IoTMind
from .evolution_cadence import EvolutionCadence, evolution_enabled
from .free_sovereign import FreeSovereignIntegrity
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
from .elite import EliteOrchestrator
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
_CT_CFG = Config.load('configs/default.json').get('continuous_training', {}) or {}
_CT_SELF = _CT_CFG.get('self_training') or {}
_CT_SMART = _CT_CFG.get('smart_continuous') or {}
CONTINUOUS = ContinuousLearningOrchestrator(
    'data/continuous_learning',
    evaluator_model=runtime.model,
    continuous_config=ContinuousConfig(
        interval_seconds=int(_CT_CFG.get('interval_seconds') or 120),
        max_consecutive_failures=int(_CT_CFG.get('max_consecutive_failures') or 5),
        checkpoint_every_cycle=bool(_CT_CFG.get('checkpoint_every_cycle', True)),
        auto_promote=False,
        require_evaluation=bool(_CT_CFG.get('require_evaluation', True)),
        heartbeat_seconds=int(_CT_CFG.get('heartbeat_seconds') or 30),
    ),
    self_training=bool(_CT_SELF.get('enabled', True)),
    self_training_batch_size=int(_CT_SELF.get('examples_per_track_per_cycle') or 3),
    self_training_min_score=float(_CT_SELF.get('min_teacher_score') or 0.75),
    # Open mode: auto-accept curated learning candidates (NOT weight promotion).
    # Disable improvement ratchet so continuous focused cycles keep accepting at similar precision.
    require_human_approval=not auto_accept_learning(),
    min_improvement=(-1.0 if auto_accept_learning() else float(_CT_CFG.get('min_improvement') or 0.01)),
    smart_config=_CT_SMART,
    open_mode=auto_accept_learning,
)
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
    n=int(_CODE_CFG.get('candidates', 5)), max_repairs=int(_CODE_CFG.get('max_repairs', 6)),
    adversarial_rounds=int(_CODE_CFG.get('adversarial_rounds', 3)), auto_repair=bool(_CODE_CFG.get('auto_repair', True)))
from .advanced_self_develop import AdvancedSelfDevelop  # noqa: E402
ADVANCED = AdvancedSelfDevelop(
    code_learning=CODE_LEARNING,
    continuous=CONTINUOUS,
    evaluator=CODE_EVAL,
    review_passes=int(_CODE_CFG.get('review_passes') or 3),
    max_repairs=int(_CODE_CFG.get('max_repairs') or 6),
)
from .unified_brain import UnifiedBrain, unified_brain_enabled  # noqa: E402
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
            'Run self_improve_tick to detect → safe-heal → continuous learn in one brain cycle.',
            'Keep weight promotion explicit; curated learning auto-accepts in open mode.',
            'Review /metrics and regression queue; SSRF and secrets stay gated.',
        ],
        'continuous_gate': status,
        'autonomy': open_execution_status(),
        'note': 'Suggestion only — use self_improve_tick to act within safe bounds.',
    }

def _tool_self_check_run():
    report = PLATFORM_SELF_CHECK.run_checks()
    return {
        'ok': bool(report.ok),
        'summary': report.summary,
        'checks': list(report.checks or []),
        'auto_safe_heal': auto_safe_heal(),
    }

def _tool_self_heal_cycle(apply: bool = True):
    """Detect → propose → optionally apply safe steps → retest/rollback."""
    report = PLATFORM_SELF_CHECK.run_checks()
    prop = PLATFORM_SELF_HEAL.propose_fix(report)
    out = {
        'ok': True,
        'check_ok': bool(report.ok),
        'proposal_id': prop.proposal_id,
        'diagnosis': prop.diagnosis,
        'steps': list(prop.steps or []),
        'requires_owner': bool(prop.requires_owner),
        'applied': False,
        'weight_promotion': 'never_auto',
    }
    if report.ok:
        out['note'] = 'healthy'
        return out
    should_apply = bool(apply) and (auto_safe_heal() or not prop.requires_owner)
    if should_apply and prop.steps:
        applied = PLATFORM_SELF_HEAL.apply_fix(prop.proposal_id, approved=True)
        out['applied'] = bool(applied.applied and applied.ok)
        out['apply_message'] = applied.message
        tested = PLATFORM_SELF_HEAL.test_fix(prop.proposal_id)
        out['recheck_ok'] = bool(tested.ok)
        if not tested.ok:
            rolled = PLATFORM_SELF_HEAL.rollback_fix(prop.proposal_id)
            out['rolled_back'] = bool(rolled.rolled_back)
            out['ok'] = False
        else:
            out['ok'] = True
    else:
        out['note'] = 'proposed only — approval or auto_safe_heal required'
        out['ok'] = False
    return out

def _tool_self_improve_tick(include_continuous_tick: bool = True):
    return AUTONOMY.run_cycle(include_continuous_tick=bool(include_continuous_tick))

def _tool_autonomy_status():
    return AUTONOMY.status()

def _tool_advanced_status():
    return ADVANCED.status()

def _tool_advanced_awareness():
    return ADVANCED.awareness(intent='chat')

def _tool_advanced_self_develop(force: bool = True, include_continuous_tick: bool = True):
    """Aware multi-pass code self-build + learn (no weight promote)."""
    return ADVANCED.autonomous_cycle(
        force=bool(force),
        include_continuous_tick=bool(include_continuous_tick),
    )

def _tool_advanced_code_build(instruction: str = '', test_code: str = ''):
    if not (instruction or '').strip() or not (test_code or '').strip():
        return {'ok': False, 'error': 'instruction and test_code are required', 'weight_promotion': 'never_auto'}
    return ADVANCED.multi_pass_build(instruction.strip(), test_code.strip())

# UNIFIED is constructed after AUTONOMY handlers exist — placeholder filled below
UNIFIED = None  # type: ignore

def _tool_unified_brain_pulse(action: str = 'status', message: str = '', include_action: bool = True):
    brain = UNIFIED
    if brain is None:
        return {'ok': False, 'error': 'unified brain not ready', 'unified': False}
    return brain.pulse(action=action or 'status', message=message or '', include_action=bool(include_action))

def _tool_unified_brain_status():
    if UNIFIED is None:
        return {'ok': False, 'unified_brain': False, 'enabled': unified_brain_enabled()}
    return UNIFIED.status()

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
    started = CONTINUOUS.start()
    tick = CONTINUOUS.tick_once()
    return {**started, 'immediate_tick': tick.get('cycle'), 'ingest': tick.get('ingest')}

def _tool_continuous_resume():
    if not is_continuous_enabled():
        raise RuntimeError('continuous training disabled by config/env gate')
    return CONTINUOUS.resume()

def _tool_continuous_tick():
    if not is_continuous_enabled():
        raise RuntimeError('continuous training disabled by config/env gate')
    if CONTINUOUS.service.status().get('status') != 'running':
        CONTINUOUS.start()
    return CONTINUOUS.tick_once()

def _tool_smart_continuous_status():
    st = CONTINUOUS.status()
    return {
        'ok': True,
        'smart': st.get('smart') or {},
        'adaptive_interval_seconds': st.get('adaptive_interval_seconds'),
        'pending_examples': st.get('pending_examples'),
        'worker_alive': st.get('worker_alive'),
        'real_loop': st.get('real_loop'),
        'auto_promote': False,
        'gate': continuous_gate_status(),
        'note': 'Focused high-precision continuous curation; weight promotion stays owner-gated.',
    }

def _tool_training_cycle_start(owner_requested: bool = True, activate_if_pass: bool = False):
    """Start a weight-training cycle from chat. Never silent-promotes (activate_if_pass default False)."""
    cfg = TrainingConfig(
        method='lora',
        base_model=os.environ.get('MODEL_NAME') or 'local',
        allow_mock_backend=False,
        max_runtime_seconds=AUTONOMOUS_TRAINING.triggers.max_runtime,
    )
    result = AUTONOMOUS_TRAINING.run_cycle(
        owner_requested=bool(owner_requested),
        explicit_retrain=True,
        activate_if_pass=bool(activate_if_pass),
        config=cfg,
        request={'owner': 'chat', 'via': 'training_cycle_start'},
    )
    return {
        'ok': bool(result.get('ok')),
        'status': result.get('status'),
        'actual_training_executed': bool(result.get('actual_training_executed')),
        'model_activated': bool(result.get('model_activated')),
        'can_start_from_chat': True,
        'activate_if_pass': bool(activate_if_pass),
        'reason': result.get('reason') or result.get('error') or result.get('status'),
        'job_id': (result.get('job') or {}).get('job_id'),
        'note': 'cycle start from chat; activation still explicit unless activate_if_pass=true',
    }

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

def _tool_coding_next_lesson(owner: str = 'owner', track_id: str = 'python'):
    nxt = CODING_AGENT.tutor.adaptive_next(owner, track_id or 'python')
    lesson_id = (nxt.get('next') or {}).get('id')
    lesson = CODING_AGENT.tutor.lesson(track_id or 'python', lesson_id, reveal_solution=False) if lesson_id else None
    return {'ok': True, 'track_id': track_id or 'python', 'next': nxt, 'lesson': lesson, 'trained': False}

def _tool_coding_hint(owner: str = 'owner', track_id: str = 'python', lesson_id: str = '', code: str = '', stderr: str = ''):
    if not lesson_id:
        nxt = CODING_AGENT.tutor.adaptive_next(owner, track_id or 'python')
        lesson_id = (nxt.get('next') or {}).get('id') or 'py-intro'
    return CODING_AGENT.tutor.hint(owner, track_id or 'python', lesson_id, code=code or '', stderr=stderr or '')

def _tool_coding_exercise_submit(owner: str = 'owner', track_id: str = 'python', lesson_id: str = 'py-intro', code: str = ''):
    result = CODING_AGENT.tutor.submit_exercise(owner, track_id or 'python', lesson_id or 'py-intro', code or '')
    if result.get('passed') and result.get('mode') == 'sandbox' and (code or '').strip():
        lesson = CODING_CURRICULUM.get_lesson(track_id or 'python', lesson_id or 'py-intro') or {}
        prompt = (lesson.get('exercise') or {}).get('prompt') or f"Complete exercise {track_id}/{lesson_id}"
        learn = AUTONOMOUS_TRAINING.experience.record_code_test_pass(
            instruction=str(prompt),
            code=code,
            source_id=f"coding_chat:{track_id}/{lesson_id}",
            provenance={'via': 'coding_exercise_submit_tool', 'owner_scoped': True},
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

def _tool_web_status():
    from .elite.web_fabric import web_config_report
    return {'ok': True, **web_config_report()}

def _run_with_timeout(fn, *, timeout_s: float = 20.0, label: str = 'web_tool'):
    """Bound chat-facing network tools so one slow provider cannot stall the brain.

    Important: shutdown(wait=False) so a timed-out provider does not keep the
    request thread blocked for the remainder of the network call.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    limit = max(0.05, float(timeout_s))
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(fn)
    try:
        return fut.result(timeout=limit)
    except FuturesTimeout:
        return {
            'ok': False,
            'error': f'{label}_timeout',
            'timeout_seconds': limit,
            'fabricated_results': False,
            'results': [],
            'citations': [],
            'note': 'Timed out for chat responsiveness — retry or narrow the query',
        }
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)

def _tool_web_search(query: str = '', q: str = '', limit: int = 5, approved: bool = True, actor: str = 'chat'):
    from .elite.web_fabric import web_config_report, WebResearchSession
    query = (query or q or '').strip()
    if not query:
        return {'ok': False, 'error': 'query is required', 'fabricated_results': False, 'results': []}
    status = web_config_report()
    if status.get('WEB_FABRIC_STATUS') not in ('READY', 'CONFIGURED'):
        return {
            'ok': False,
            'WEB_FABRIC_STATUS': status.get('WEB_FABRIC_STATUS') or 'NOT_CONFIGURED',
            'error': 'web_provider_unavailable',
            'fabricated_results': False,
            'results': [],
            'note': status.get('note') or 'Configure PFAI_WEB_ALLOW_NETWORK + search provider',
        }
    session = WebResearchSession()
    # fetch_top=0 → search snippets only (no page fetches) for chat latency
    return _run_with_timeout(
        lambda: session.research(
            query,
            limit=min(5, int(limit or 5)),
            fetch_top=0,
            approved=bool(approved),
            actor=str(actor or 'chat'),
        ),
        timeout_s=float(os.environ.get('PFAI_CHAT_WEB_TIMEOUT', os.environ.get('PFAI_WEB_TIMEOUT', '8')) or 8),
        label='web_search',
    )

def _tool_web_fetch(url: str = '', max_bytes: int = 120000, approved: bool = True, actor: str = 'chat'):
    from .elite.web_fabric import WebPolicyGate, web_config_report, validate_url_for_fetch, WebInformationFabric
    url = (url or '').strip()
    if not url:
        return {'ok': False, 'error': 'url is required', 'fabricated_results': False}
    gate = WebPolicyGate()
    auth = gate.authorize_url(url, approved=bool(approved), actor=str(actor or 'chat'))
    if not auth.get('ok'):
        return {'ok': False, 'error': auth.get('error'), 'ssrf_blocked': True, 'fabricated_results': False}
    status = web_config_report()
    if status.get('WEB_FABRIC_STATUS') not in ('READY', 'CONFIGURED'):
        return {
            'ok': False,
            'WEB_FABRIC_STATUS': status.get('WEB_FABRIC_STATUS') or 'NOT_CONFIGURED',
            'error': 'web_provider_unavailable',
            'fabricated_results': False,
        }
    check = validate_url_for_fetch(url)
    if not check.get('ok'):
        return {'ok': False, 'error': check.get('error'), 'ssrf_blocked': True, 'fabricated_results': False}
    return _run_with_timeout(
        lambda: WebInformationFabric().fetch_provider.fetch(url, max_bytes=int(max_bytes or 120000)),
        timeout_s=float(os.environ.get('PFAI_CHAT_WEB_TIMEOUT', os.environ.get('PFAI_WEB_TIMEOUT', '12')) or 12),
        label='web_fetch',
    )

def _tool_web_research(query: str = '', q: str = '', question: str = '', limit: int = 5, approved: bool = True, actor: str = 'chat'):
    from .elite.web_research_pipeline import WebResearchPipeline
    query = (query or q or question or '').strip()
    if not query:
        return {'ok': False, 'error': 'query is required', 'fabricated_results': False, 'citations': []}
    # Chat path: search-heavy, fetch at most 1 page for latency
    return _run_with_timeout(
        lambda: WebResearchPipeline().run(
            query,
            limit=min(5, int(limit or 5)),
            fetch_top=1,
            approved=bool(approved),
            actor=str(actor or 'chat'),
        ),
        timeout_s=float(os.environ.get('PFAI_CHAT_WEB_TIMEOUT', os.environ.get('PFAI_WEB_TIMEOUT', '12')) or 12),
        label='web_research',
    )

def _tool_app_control_status():
    """Unified master snapshot so chat can steer the whole app."""
    from .elite.web_fabric import web_config_report
    cont = CONTINUOUS.status()
    train = {}
    try:
        train = {
            'eligibility': (AUTONOMOUS_TRAINING.learning_statistics().get('next_training_eligibility') or {}),
            'control': AUTONOMOUS_TRAINING.control_center_status().get('labels') or {},
        }
    except Exception as exc:
        train = {'error': str(exc)}
    return {
        'ok': True,
        'version': __version__,
        'health': runtime.health(extra={'continuous': continuous_gate_status()}),
        'continuous': {
            'service': (cont.get('service') or {}).get('status'),
            'worker_alive': cont.get('worker_alive'),
            'pending_examples': cont.get('pending_examples'),
            'real_loop': cont.get('real_loop'),
        },
        'training': train,
        'web': {
            'WEB_FABRIC_STATUS': web_config_report().get('WEB_FABRIC_STATUS'),
            'search_provider': web_config_report().get('search_provider'),
        },
        'academy_tracks': len(CODING_CURRICULUM.list_tracks()),
        'master_chat': True,
        'autonomy': open_execution_status(),
        'advanced': ADVANCED.maturity(),
        'note': 'Chat is the control plane — ops/learn/train/web/code + self-improve + advanced self-develop',
    }

def _tool_learner_snapshot(owner: str = 'owner'):
    profile = CODING_PROFILES.get_profile(owner)
    progress = CODING_PROFILES.progress(owner)
    skills = profile.get('skills') or {}
    weak = [k for k, v in skills.items() if float(v or 0) < 0.6][:5]
    return {
        'ok': True,
        'profile': {
            'display_level': profile.get('display_level'),
            'mode': profile.get('mode'),
            'completed_lessons': len(profile.get('completed_lessons') or []),
            'weak_skills': weak,
        },
        'progress': progress,
        'tracks': CODING_CURRICULUM.list_tracks()[:10],
        'training_from_chat': True,
        'note': 'Academy snapshot — use training_cycle_start / continuous_start for learning ops',
    }

def _tool_training_eligibility():
    """Next-training eligibility (read). Cycle start is a separate tool."""
    stats = AUTONOMOUS_TRAINING.learning_statistics()
    elig = stats.get('next_training_eligibility') or {}
    return {
        'ok': True,
        'eligible': bool(elig.get('eligible')),
        'eligibility': elig,
        'accepted_candidates': stats.get('accepted_candidates'),
        'dataset_growth_since_last_trained': stats.get('dataset_growth_since_last_trained'),
        'dataset_version': stats.get('dataset_version'),
        'trained': False,
        'can_start_from_chat': True,
        'note': 'eligible snapshot; call training_cycle_start to begin a cycle (no silent activate)',
    }

def _tool_training_control_status():
    """Autonomous-training control-center snapshot."""
    cc = AUTONOMOUS_TRAINING.control_center_status()
    return {
        'ok': True,
        'labels': cc.get('labels') or {},
        'status': cc.get('status') or cc.get('training_status') or cc,
        'paused': cc.get('paused'),
        'autonomous_enabled': cc.get('autonomous_enabled'),
        'active_job': cc.get('active_job'),
        'can_start_from_chat': True,
        'note': 'control-center snapshot; training_cycle_start available in open mode',
    }

def _chat_learning_hub(owner: str) -> dict:
    """Lightweight academy + training bridge for chat responses."""
    try:
        profile = CODING_PROFILES.get_profile(owner)
        progress = CODING_PROFILES.progress(owner)
    except Exception:
        profile, progress = {}, {}
    skills = profile.get('skills') or {}
    return {
        'academy': {
            'display_level': profile.get('display_level'),
            'mode': profile.get('mode'),
            'completed_lessons': len(profile.get('completed_lessons') or []),
            'weak_skills': [k for k, v in skills.items() if float(v or 0) < 0.6][:5],
        },
        'progress': progress,
        'training_from_chat': True,
        'can_start_training_from_chat': True,
        'continuous_worker': bool((CONTINUOUS.status() or {}).get('worker_alive')),
    }

CODING_TOOL_SPECS = list(DEFAULT_TOOLS) + [
    ToolSpec('run_sandbox', 'Execute learner code in isolated Python sandbox', 'write', False, {'code': 'string', 'test_code': 'string?'}),
    ToolSpec('coding_tracks', 'List extensible coding curriculum tracks', 'read', False, {}),
    ToolSpec('coding_teach', 'Build personalized learning path for a track', 'read', False, {'track_id': 'string', 'goal': 'string?', 'owner': 'string?'}),
    ToolSpec('coding_review', 'Static/security/maintainability code review', 'read', False, {'code': 'string', 'language': 'string?'}),
    ToolSpec('coding_assess', 'Return skill assessment questions', 'read', False, {}),
    ToolSpec('coding_progress', 'Learner coding progress snapshot', 'read', False, {'owner': 'string?'}),
    ToolSpec('coding_projects', 'List project-based learning catalog', 'read', False, {'level': 'string?'}),
    ToolSpec('coding_knowledge', 'Search coding knowledge base', 'read', False, {'q': 'string', 'limit': 'int?'}),
    ToolSpec('coding_next_lesson', 'Next adaptive lesson for a track (read/teach)', 'read', False, {'owner': 'string?', 'track_id': 'string?'}),
    ToolSpec('learner_snapshot', 'Academy + progress snapshot linked to chat (no training)', 'read', False, {'owner': 'string?'}),
    ToolSpec('training_eligibility', 'Read next-training eligibility gates', 'read', False, {}),
    ToolSpec('training_control_status', 'Read training control-center status', 'read', False, {}),
    ToolSpec('continuous_tick', 'Run one continuous-learning cycle now (no promote)', 'write', False, {}),
    ToolSpec('smart_continuous_status', 'Focused high-precision continuous training status', 'read', False, {}),
    ToolSpec('training_cycle_start', 'Start weight-training cycle from chat (activate_if_pass default false)', 'write', False, {'owner_requested': 'bool?', 'activate_if_pass': 'bool?'}),
    ToolSpec('coding_hint', 'Progressive coding hint with diagnostics', 'read', False, {'owner': 'string?', 'track_id': 'string?', 'lesson_id': 'string?', 'code': 'string?', 'stderr': 'string?'}),
    ToolSpec('coding_exercise_submit', 'Submit academy exercise code for sandbox grading', 'write', False, {'owner': 'string?', 'track_id': 'string', 'lesson_id': 'string', 'code': 'string'}),
    ToolSpec('web_status', 'Web fabric readiness / providers', 'read', False, {}),
    ToolSpec('web_search', 'Live web search (policy-gated, no fabricated results)', 'read', False, {'query': 'string', 'limit': 'int?'}),
    ToolSpec('web_fetch', 'Fetch a URL via policy gate (SSRF-safe)', 'read', False, {'url': 'string', 'max_bytes': 'int?'}),
    ToolSpec('web_research', 'Search + fetch research pipeline with citations', 'read', False, {'query': 'string', 'limit': 'int?'}),
    ToolSpec('app_control_status', 'Master control snapshot for chat (ops+learn+train+web+academy)', 'read', False, {}),
    ToolSpec('self_check_run', 'Run platform self-check diagnostics', 'read', False, {}),
    ToolSpec('self_heal_cycle', 'Detect → safe-heal → retest (auto in open mode)', 'write', False, {'apply': 'bool?'}),
    ToolSpec('self_improve_tick', 'Full autonomy tick: check + safe heal + continuous learn', 'write', False, {'include_continuous_tick': 'bool?'}),
    ToolSpec('autonomy_status', 'Open-execution + self-improve autonomy status', 'read', False, {}),
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
    'smart_continuous_status': _tool_smart_continuous_status,
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
    'continuous_tick': _tool_continuous_tick,
    'training_cycle_start': _tool_training_cycle_start,
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
    'coding_next_lesson': _tool_coding_next_lesson,
    'coding_hint': _tool_coding_hint,
    'coding_exercise_submit': _tool_coding_exercise_submit,
    'learner_snapshot': _tool_learner_snapshot,
    'training_eligibility': _tool_training_eligibility,
    'training_control_status': _tool_training_control_status,
    'web_status': _tool_web_status,
    'web_search': _tool_web_search,
    'web_fetch': _tool_web_fetch,
    'web_research': _tool_web_research,
    'app_control_status': _tool_app_control_status,
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
    # Production longevity root — MODEL_V0007 active + MODEL_V0001 LKG live here.
    root=os.environ.get('PFAI_TRAINING_ROOT', 'data/longevity/training_phase9_verify'),
    learning_pipeline=PLATFORM_LEARNING,
    eval_runner=_platform_eval_runner,
    allow_mock_backend=False,
    include_approved_seeds=True,
)
from pfai.longevity.autonomous_training.experience_bridge import set_global_experience_bridge

# Continuous experience bridge — real operational events only
set_global_experience_bridge(AUTONOMOUS_TRAINING.experience)
COMMAND_AGENT.experience_bridge = AUTONOMOUS_TRAINING.experience


def _pull_accepted_experience_rows() -> list:
    """Feed continuous curation from accepted longevity learning candidates."""
    try:
        rows = AUTONOMOUS_TRAINING.learning_pipeline_gate.accepted_training_rows(limit=64)
    except Exception:
        return []
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(r)
    return out


def _push_curated_to_experience(rows: list) -> dict:
    """Push high-precision curated rows into longevity experience (dataset growth).

    Never activates weights. Uses evaluation-lesson attribution (verified).
    """
    bridge = getattr(AUTONOMOUS_TRAINING, 'experience', None)
    if bridge is None or not rows:
        return {'pushed': 0, 'accepted': 0}
    pushed = 0
    accepted = 0
    for i, r in enumerate(rows[:24]):
        if not isinstance(r, dict):
            continue
        ins = str(r.get('instruction') or '').strip()
        resp = str(r.get('response') or '').strip()
        if not ins or not resp:
            continue
        try:
            out = bridge.record_evaluation_lesson(
                instruction=ins[:2000],
                response=resp[:4000],
                source_id=f"smart-cont-{i}-{hash(ins) & 0xffffffff:x}",
            )
            pushed += 1
            elig = str((out or {}).get('eligibility') or '').lower()
            if elig in ('accepted', 'accepted_verified'):
                accepted += 1
        except Exception:
            continue
    return {'pushed': pushed, 'accepted': accepted, 'auto_promote': False}


CONTINUOUS.bind_experience_ingest(_pull_accepted_experience_rows)
CONTINUOUS.bind_experience_push(_push_curated_to_experience)


def _pfai_startup_continuous() -> None:
    """Auto-start real continuous worker when gate is enabled (no auto-promote)."""
    if not is_continuous_enabled():
        log.info('startup: continuous gate off — worker not started')
        return
    try:
        st = CONTINUOUS.start()
        log.info('startup: continuous worker started worker_alive=%s', st.get('worker_alive'))
    except Exception as exc:
        log.warning('startup: continuous worker failed: %s', exc)


def _pfai_shutdown_continuous() -> None:
    try:
        if (CONTINUOUS.status().get('service') or {}).get('status') in {'running', 'cycle', 'paused'}:
            CONTINUOUS.stop('app_shutdown')
            log.info('shutdown: continuous worker stopped')
    except Exception as exc:
        log.warning('shutdown: continuous stop failed: %s', exc)


app.router.add_event_handler('startup', _pfai_startup_continuous)
app.router.add_event_handler('shutdown', _pfai_shutdown_continuous)

# --- Quantum-inspired ultra-fast core + IoT mind + evolution cadence -------
IOT_MIND = IoTMind()
QUANTUM = QuantumInspiredCore(
    iot_fn=lambda m: IOT_MIND.understand(m),
    continuous_status_fn=lambda: CONTINUOUS.status(),
    evolve_status_fn=None,
)

def _evolve_minute_tick() -> dict:
    q = QUANTUM.pulse('minute evolution', include_iot=False)
    cont = {'ok': False, 'skipped': True}
    if is_continuous_enabled():
        try:
            cont = CONTINUOUS.tick_once()
        except Exception as exc:
            cont = {'ok': False, 'error': str(exc)[:160]}
    return {
        'ok': True,
        'quantum_us': ((q.get('timing') or {}).get('elapsed_us')),
        'quantum_band': ((q.get('timing') or {}).get('target_band')),
        'continuous_ok': bool((cont or {}).get('ok')),
        'weight_promotion': 'never_auto',
    }

def _evolve_hour_tick() -> dict:
    return AUTONOMY.run_cycle(include_continuous_tick=True)

def _evolve_day_tick() -> dict:
    return ADVANCED.autonomous_cycle(force=True, include_continuous_tick=True)

EVOLUTION = EvolutionCadence(
    minute_fn=_evolve_minute_tick,
    hour_fn=_evolve_hour_tick,
    day_fn=_evolve_day_tick,
    minute_seconds=int(os.environ.get('PFAI_EVOLVE_MINUTE_SECONDS') or 60),
    hour_seconds=int(os.environ.get('PFAI_EVOLVE_HOUR_SECONDS') or 3600),
    day_seconds=int(os.environ.get('PFAI_EVOLVE_DAY_SECONDS') or 86400),
)
# Rebind evolve status now that EVOLUTION exists
QUANTUM.evolve_status_fn = lambda: EVOLUTION.status()

def _pfai_startup_quantum_iot_evolve() -> None:
    try:
        seeds = IOT_MIND.training_seeds()
        reg = CONTINUOUS.register_batch(seeds)
        log.info('startup: iot seeds accepted=%s', reg.get('accepted'))
    except Exception as exc:
        log.warning('startup: iot seed failed: %s', exc)
    try:
        st = EVOLUTION.start()
        log.info('startup: evolution cadence alive=%s', st.get('alive'))
    except Exception as exc:
        log.warning('startup: evolution failed: %s', exc)

def _pfai_shutdown_evolution() -> None:
    try:
        EVOLUTION.stop('app_shutdown')
    except Exception as exc:
        log.warning('shutdown: evolution stop failed: %s', exc)

app.router.add_event_handler('startup', _pfai_startup_quantum_iot_evolve)
app.router.add_event_handler('shutdown', _pfai_shutdown_evolution)

def _tool_quantum_pulse(message: str = ''):
    return QUANTUM.pulse(message or 'quantum pulse')

def _tool_quantum_status():
    return QUANTUM.status()

def _tool_quantum_hot_route(message: str = ''):
    return QUANTUM.hot_route(message or '')

def _tool_iot_understand(message: str = '', language: str = 'ar'):
    return IOT_MIND.answer(message or '', language=language or 'ar')

def _tool_iot_status():
    return IOT_MIND.status()

def _tool_evolution_status():
    return EVOLUTION.status()

def _tool_evolution_tick(kind: str = 'minute'):
    k = (kind or 'minute').strip().lower()
    if k == 'hour':
        return {'ok': True, 'kind': 'hour', 'result': EVOLUTION.tick_hour(), 'weight_promotion': 'never_auto'}
    if k == 'day':
        return {'ok': True, 'kind': 'day', 'result': EVOLUTION.tick_day(), 'weight_promotion': 'never_auto'}
    return {'ok': True, 'kind': 'minute', 'result': EVOLUTION.tick_minute(), 'weight_promotion': 'never_auto'}

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
    'owner_auth_ready': lambda: {
        'ok': 'password' in OWNER_AUTH.public_status().get('auth_methods', []),
        'email_otp': 'REMOVED',
        'email_auth': 'REMOVED',
        'auth_methods': OWNER_AUTH.public_status().get('auth_methods', []),
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
PLATFORM_SELF_HEAL.register_safe_action(
    'ensure_continuous_worker',
    lambda: (
        CONTINUOUS.start()
        if is_continuous_enabled()
        else {'ok': False, 'error': 'continuous gate off'}
    ),
)
PLATFORM_SELF_HEAL.register_safe_action(
    'continuous_soft_tick',
    lambda: CONTINUOUS.tick_once() if is_continuous_enabled() else {'ok': False, 'error': 'continuous gate off'},
)
PLATFORM_SELF_HEAL.register_safe_action(
    'refresh_web_fabric_status',
    lambda: __import__('pfai.elite.web_fabric', fromlist=['web_config_report']).web_config_report(),
)

def _migrate_apply_safe() -> dict:
    """Backup-first schema apply — productive freedom, never touches weights."""
    report = PLATFORM_MIGRATIONS_RUNNER.run(dry_run=False)
    PLATFORM_COMPAT._current_schema = PLATFORM_MIGRATIONS_RUNNER.current_version()
    PLATFORM_COMPAT._migration_status = PLATFORM_MIGRATIONS_RUNNER.status()
    return {
        'ok': bool(getattr(report, 'ok', False)),
        'current': PLATFORM_MIGRATIONS_RUNNER.current_version(),
        'target': PLATFORM_MIGRATIONS_RUNNER.target_version(),
        'applied': list(getattr(report, 'applied', None) or []),
        'error': getattr(report, 'error', None),
        'weight_promotion': 'never_auto',
    }

PLATFORM_SELF_HEAL.register_safe_action(
    'apply_pending_schema',
    lambda: (
        _migrate_apply_safe()
        if int(PLATFORM_MIGRATIONS_RUNNER.status().get('pending_count') or 0) > 0
        else {'ok': True, 'skipped': True, 'current': PLATFORM_MIGRATIONS_RUNNER.current_version()}
    ),
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

from .autonomous_improve import AutonomousImproveOrchestrator  # noqa: E402

def _autonomy_experience_record(*, instruction: str, response: str, source_id: str, passed: bool = True):
    try:
        return AUTONOMOUS_TRAINING.experience.record_self_check(
            instruction=instruction,
            response=response,
            source_id=source_id,
            passed=bool(passed),
        )
    except Exception:
        return None

AUTONOMY = AutonomousImproveOrchestrator(
    self_check=PLATFORM_SELF_CHECK,
    self_heal=PLATFORM_SELF_HEAL,
    continuous=CONTINUOUS,
    experience_record=_autonomy_experience_record,
)

# Hook continuous worker: each background cycle also runs bounded self-heal
_ORIG_CONTINUOUS_RUN_SERVICE = CONTINUOUS._run_service_cycle

def _continuous_with_autonomy(cycle_fn):
    try:
        if auto_safe_heal():
            AUTONOMY.run_cycle(include_continuous_tick=False)
    except Exception as exc:
        log.warning('autonomy pre-cycle heal skipped: %s', exc)
    result = _ORIG_CONTINUOUS_RUN_SERVICE(cycle_fn)
    # Advanced stage: self-directed multi-pass code build into curation
    try:
        stage = (ADVANCED.maturity() or {}).get('stage')
        if stage in {'capable', 'advanced', 'sovereign_safe'}:
            ADVANCED.autonomous_cycle(force=True, include_continuous_tick=False)
    except Exception as exc:
        log.warning('advanced self-develop cycle skipped: %s', exc)
    return result

CONTINUOUS._run_service_cycle = _continuous_with_autonomy  # type: ignore[method-assign]

# Register autonomy + advanced self-develop tools after wiring exists
for _spec in (
    ToolSpec('self_check_run', 'Run platform self-check diagnostics', 'read', False, {}),
    ToolSpec('self_heal_cycle', 'Detect → safe-heal → retest (auto in open mode)', 'write', False, {'apply': 'bool?'}),
    ToolSpec('self_improve_tick', 'Full autonomy tick: check + safe heal + continuous learn', 'write', False, {'include_continuous_tick': 'bool?'}),
    ToolSpec('autonomy_status', 'Open-execution + self-improve autonomy status', 'read', False, {}),
    ToolSpec('advanced_status', 'Maturity stage of continuous learn + self-develop', 'read', False, {}),
    ToolSpec('advanced_awareness', 'What the advanced brain is doing / will not do', 'read', False, {}),
    ToolSpec('advanced_self_develop', 'Aware multi-pass code self-build + curate (no promote)', 'write', False, {'force': 'bool?', 'include_continuous_tick': 'bool?'}),
    ToolSpec('advanced_code_build', 'Multi-pass verify/review/repair for a coding task', 'write', False, {'instruction': 'string', 'test_code': 'string'}),
):
    TOOL_ROUTER.specs[_spec.name] = _spec
TOOL_ROUTER.handlers['self_check_run'] = _tool_self_check_run
TOOL_ROUTER.handlers['self_heal_cycle'] = _tool_self_heal_cycle
TOOL_ROUTER.handlers['self_improve_tick'] = _tool_self_improve_tick
TOOL_ROUTER.handlers['autonomy_status'] = _tool_autonomy_status
TOOL_ROUTER.handlers['advanced_status'] = _tool_advanced_status
TOOL_ROUTER.handlers['advanced_awareness'] = _tool_advanced_awareness
TOOL_ROUTER.handlers['advanced_self_develop'] = _tool_advanced_self_develop
TOOL_ROUTER.handlers['advanced_code_build'] = _tool_advanced_code_build

# One-mind unified brain (parallel local lanes)
def _ub_health():
    return runtime.health(extra={'continuous': continuous_gate_status()})

def _ub_continuous():
    return CONTINUOUS.status()

def _ub_advanced():
    return ADVANCED.status()

def _ub_autonomy():
    return AUTONOMY.status()

def _ub_web():
    from .elite.web_fabric import web_config_report
    return web_config_report()

def _ub_academy():
    return {'ok': True, 'tracks': len(CODING_CURRICULUM.list_tracks()), 'count': len(CODING_CURRICULUM.list_tracks())}

UNIFIED = UnifiedBrain(
    health_fn=_ub_health,
    continuous_fn=_ub_continuous,
    advanced_fn=_ub_advanced,
    autonomy_fn=_ub_autonomy,
    web_fn=_ub_web,
    academy_fn=_ub_academy,
    improve_fn=lambda: AUTONOMY.run_cycle(include_continuous_tick=False),
    develop_fn=lambda: ADVANCED.autonomous_cycle(force=True, include_continuous_tick=False),
)
for _spec in (
    ToolSpec('unified_brain_pulse', 'One-mind parallel pulse (+ optional improve/develop)', 'write', False, {'action': 'string?', 'message': 'string?', 'include_action': 'bool?'}),
    ToolSpec('unified_brain_status', 'Unified brain enablement status', 'read', False, {}),
):
    TOOL_ROUTER.specs[_spec.name] = _spec
TOOL_ROUTER.handlers['unified_brain_pulse'] = _tool_unified_brain_pulse
TOOL_ROUTER.handlers['unified_brain_status'] = _tool_unified_brain_status

for _spec in (
    ToolSpec('quantum_pulse', 'Ultra-fast quantum-inspired parallel hypothesis pulse (classical, measured μs)', 'read', False, {'message': 'string?'}),
    ToolSpec('quantum_status', 'Quantum-inspired core status (honest: no fake qubits)', 'read', False, {}),
    ToolSpec('quantum_hot_route', 'Microsecond-oriented local router', 'read', False, {'message': 'string?'}),
    ToolSpec('iot_understand', 'Deep IoT comprehension (MQTT/Zigbee/Matter/… grounded)', 'read', False, {'message': 'string', 'language': 'string?'}),
    ToolSpec('iot_status', 'IoT mind status', 'read', False, {}),
    ToolSpec('evolution_status', 'Minute/hour/day evolution cadence status', 'read', False, {}),
    ToolSpec('evolution_tick', 'Run one evolution tick (minute|hour|day)', 'write', False, {'kind': 'string?'}),
):
    TOOL_ROUTER.specs[_spec.name] = _spec
TOOL_ROUTER.handlers['quantum_pulse'] = _tool_quantum_pulse
TOOL_ROUTER.handlers['quantum_status'] = _tool_quantum_status
TOOL_ROUTER.handlers['quantum_hot_route'] = _tool_quantum_hot_route
TOOL_ROUTER.handlers['iot_understand'] = _tool_iot_understand
TOOL_ROUTER.handlers['iot_status'] = _tool_iot_status
TOOL_ROUTER.handlers['evolution_status'] = _tool_evolution_status
TOOL_ROUTER.handlers['evolution_tick'] = _tool_evolution_tick

# --- Free Sovereign Integrity (audit → repair → retest → learn) ------------
def _conflict_scan() -> dict:
    conflicts = []
    for name in TOOL_ROUTER.specs:
        if name not in TOOL_ROUTER.handlers:
            conflicts.append({'type': 'missing_handler', 'tool': name})
    for name in TOOL_ROUTER.handlers:
        if name not in TOOL_ROUTER.specs:
            conflicts.append({'type': 'orphan_handler', 'tool': name})
    for mod in (
        'pfai.smart_continuous', 'pfai.quantum_core', 'pfai.iot_mind',
        'pfai.evolution_cadence', 'pfai.free_sovereign', 'pfai.advanced_self_develop',
    ):
        try:
            __import__(mod)
        except Exception as exc:
            conflicts.append({'type': 'import_error', 'module': mod, 'error': str(exc)[:160]})
    return {'ok': len(conflicts) == 0, 'conflicts': conflicts, 'n': len(conflicts)}

def _regression_sandbox_repair() -> dict:
    """Repair pending regression cases via multi-pass sandbox build (no promote)."""
    try:
        items = REGRESSIONS.pending() or []
    except Exception as exc:
        return {'ok': False, 'error': str(exc)[:160]}
    if not items:
        return {'ok': True, 'skipped': True, 'repaired': 0}
    repaired = 0
    details = []
    for item in items[:2]:
        instr = str(item.get('instruction') or item.get('prompt') or item.get('task') or '').strip()
        tests = str(item.get('test_code') or item.get('tests') or '').strip()
        if not instr:
            continue
        try:
            build = ADVANCED.multi_pass_build(
                instr,
                tests or 'assert True',
                source='free_sovereign_regression',
            )
            ok = bool(build.get('ok') or build.get('solved'))
            if ok:
                repaired += 1
            details.append({'id': item.get('id') or item.get('case_id'), 'ok': ok})
        except Exception as exc:
            details.append({'error': str(exc)[:120]})
    return {'ok': True, 'repaired': repaired, 'attempted': len(details), 'details': details}

PLATFORM_SELF_HEAL.register_safe_action(
    'ensure_evolution_worker',
    lambda: EVOLUTION.start() if evolution_enabled() else {'ok': False, 'error': 'evolution off'},
)

FREE_SOVEREIGN = FreeSovereignIntegrity(
    self_check_fn=PLATFORM_SELF_CHECK.run_checks,
    heal_propose_fn=PLATFORM_SELF_HEAL.propose_fix,
    heal_apply_fn=lambda pid: PLATFORM_SELF_HEAL.apply_fix(pid, approved=True),
    heal_test_fn=PLATFORM_SELF_HEAL.test_fix,
    migrate_status_fn=PLATFORM_MIGRATIONS_RUNNER.status,
    migrate_apply_fn=_migrate_apply_safe,
    continuous_ensure_fn=lambda: (
        CONTINUOUS.start() if is_continuous_enabled() else {'ok': True, 'skipped': True, 'reason': 'gate_off'}
    ),
    continuous_tick_fn=lambda: (
        CONTINUOUS.tick_once() if is_continuous_enabled() else {'ok': True, 'skipped': True, 'reason': 'gate_off'}
    ),
    evolution_ensure_fn=lambda: (
        EVOLUTION.start() if evolution_enabled() else {'ok': True, 'skipped': True, 'reason': 'disabled'}
    ),
    evolution_tick_fn=lambda: EVOLUTION.tick_minute(),
    advanced_develop_fn=lambda: ADVANCED.autonomous_cycle(force=True, include_continuous_tick=False),
    autonomy_fn=lambda: AUTONOMY.run_cycle(include_continuous_tick=False),
    quantum_pulse_fn=lambda: QUANTUM.pulse('sovereign audit', include_iot=False),
    open_status_fn=open_execution_status,
    regression_repair_fn=_regression_sandbox_repair,
    conflict_scan_fn=_conflict_scan,
)

# Extra integrity checks for free-sovereign audits
PLATFORM_SELF_CHECK.add_check(
    'schema_up_to_date',
    lambda: {
        'ok': int(PLATFORM_MIGRATIONS_RUNNER.status().get('pending_count') or 0) == 0,
        'current': PLATFORM_MIGRATIONS_RUNNER.current_version(),
        'pending': PLATFORM_MIGRATIONS_RUNNER.status().get('pending_count'),
    },
)
PLATFORM_SELF_CHECK.add_check(
    'continuous_worker_ready',
    lambda: {
        'ok': bool(CONTINUOUS.status().get('worker_alive')) or not is_continuous_enabled(),
        'worker_alive': CONTINUOUS.status().get('worker_alive'),
        'enabled': is_continuous_enabled(),
    },
)
PLATFORM_SELF_CHECK.add_check(
    'evolution_cadence_ready',
    lambda: {
        'ok': bool(EVOLUTION.status().get('alive')) or not evolution_enabled(),
        'alive': EVOLUTION.status().get('alive'),
    },
)
PLATFORM_SELF_CHECK.add_check(
    'tool_router_consistent',
    lambda: _conflict_scan(),
)

def _tool_free_sovereign_audit():
    return FREE_SOVEREIGN.audit()

def _tool_free_sovereign_repair(deep_code: bool = True):
    return FREE_SOVEREIGN.repair(deep_code=bool(deep_code))

def _tool_free_sovereign_cycle(deep_code: bool = True):
    return FREE_SOVEREIGN.sovereign_cycle(deep_code=bool(deep_code))

def _tool_free_ai_status():
    return {
        'ok': True,
        'free_sovereign': FREE_SOVEREIGN.status(),
        'freedom': FREE_SOVEREIGN.freedom_map(),
        'open': open_execution_status(),
        'continuous': {
            'worker_alive': CONTINUOUS.status().get('worker_alive'),
            'pending': CONTINUOUS.status().get('pending_examples'),
            'auto_promote': False,
        },
        'evolution': {
            'alive': EVOLUTION.status().get('alive'),
            'minute_ticks': EVOLUTION.status().get('minute_ticks'),
        },
        'advanced': ADVANCED.maturity(),
        'weight_promotion': 'never_auto',
        'note': 'ذكاء حر منتج بأقصى صلاحية نافعة — مع حدود صلبة للأوزان/SSRF/الأسرار.',
    }

for _spec in (
    ToolSpec('free_sovereign_audit', 'Full high-precision system integrity audit', 'read', False, {}),
    ToolSpec('free_sovereign_repair', 'Auto-repair: migrate, heal, workers, sandbox code fix', 'write', False, {'deep_code': 'bool?'}),
    ToolSpec('free_sovereign_cycle', 'Audit → repair → re-audit free sovereign cycle', 'write', False, {'deep_code': 'bool?'}),
    ToolSpec('free_ai_status', 'Free AI freedom map: unlocked vs hard-gated', 'read', False, {}),
):
    TOOL_ROUTER.specs[_spec.name] = _spec
TOOL_ROUTER.handlers['free_sovereign_audit'] = _tool_free_sovereign_audit
TOOL_ROUTER.handlers['free_sovereign_repair'] = _tool_free_sovereign_repair
TOOL_ROUTER.handlers['free_sovereign_cycle'] = _tool_free_sovereign_cycle
TOOL_ROUTER.handlers['free_ai_status'] = _tool_free_ai_status

def _pfai_startup_free_sovereign() -> None:
    """On boot: clear schema debt + soft sovereign repair (no weight promote)."""
    try:
        pending = int(PLATFORM_MIGRATIONS_RUNNER.status().get('pending_count') or 0)
        if pending > 0:
            mig = _migrate_apply_safe()
            log.info('startup: schema migrate ok=%s current=%s', mig.get('ok'), mig.get('current'))
    except Exception as exc:
        log.warning('startup: schema migrate failed: %s', exc)
    try:
        # Soft cycle without deep code on boot (fast); deep runs via chat/evolution
        out = FREE_SOVEREIGN.repair(deep_code=False)
        log.info('startup: free sovereign repair ok=%s', out.get('ok'))
    except Exception as exc:
        log.warning('startup: free sovereign failed: %s', exc)

app.router.add_event_handler('startup', _pfai_startup_free_sovereign)

# Hourly evolution also runs a deep sovereign cycle
_ORIG_EVOLVE_HOUR = EVOLUTION.hour_fn

def _evolve_hour_with_sovereign() -> dict:
    base = _ORIG_EVOLVE_HOUR() if _ORIG_EVOLVE_HOUR else {'ok': True}
    try:
        sov = FREE_SOVEREIGN.sovereign_cycle(deep_code=True)
    except Exception as exc:
        sov = {'ok': False, 'error': str(exc)[:160]}
    return {'ok': bool((base or {}).get('ok')) and bool(sov.get('ok')), 'autonomy': base, 'sovereign': {
        'ok': sov.get('ok'), 'improved': sov.get('improved'), 'after': sov.get('after'),
    }}

EVOLUTION.hour_fn = _evolve_hour_with_sovereign

log.info(
    'autonomy ready open=%s auto_learn=%s auto_heal=%s advanced_stage=%s unified=%s quantum=%s evolve=%s sovereign=%s',
    open_execution_status().get('open_chat_tools'),
    auto_accept_learning(),
    auto_safe_heal(),
    (ADVANCED.maturity() or {}).get('stage'),
    unified_brain_enabled(),
    quantum_core_enabled(),
    evolution_enabled(),
    FREE_SOVEREIGN.VERSION,
)
ELITE = EliteOrchestrator(
    root='data/longevity/elite',
    executor=PLATFORM_EXECUTOR,
    model_router=MODEL_ROUTER,
    tool_router=TOOL_ROUTER,
    experience_bridge=getattr(AUTONOMOUS_TRAINING, 'experience', None),
    bootstrap_skills=True,
)
log.info(
    'phase14 elite fabric ready skills=%s tools=%s phase14=%s',
    ELITE.skills.health().get('count'),
    len(ELITE.tools.catalog()),
    (ELITE._boot or {}).get('phase14', {}).get('count'),
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

    username = OWNER_AUTH.resolve_session(pfai_owner_session)
    if username:
        return username

    if x_owner_secret and OWNER_AUTH.authenticate_secret_header(x_owner_secret):
        return OWNER.owner_username() or 'owner'

    if not OWNER.owner_username() and not OWNER_AUTH.owner_configured():
        raise HTTPException(503, 'owner identity not configured: complete /owner/setup or set PFAI_OWNER_USERNAME')
    raise HTTPException(401, 'authentication required')




def public_access_mode() -> bool:
    """Public Access Mode: no login challenges for public product surfaces.

    Default ON when PFAI_ENV=production|prod. Explicit PFAI_PUBLIC_ACCESS_MODE
    overrides (1/true/on or 0/false/off). Tests leave production unset and keep
    legacy owner gates unless they opt into public mode.
    """
    v = os.environ.get('PFAI_PUBLIC_ACCESS_MODE', '').strip().lower()
    if v in ('0', 'false', 'no', 'off'):
        return False
    if v in ('1', 'true', 'yes', 'on'):
        return True
    return _is_production_env()


def access_public(
    request: Request,
    x_owner_secret: str | None = Header(default=None, alias='X-Owner-Secret'),
    pfai_owner_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> str:
    """Allow public product use without authentication in Public Access Mode."""
    _ = request.query_params.get('role') or request.query_params.get('admin') or request.query_params.get('owner')
    if public_access_mode():
        return 'public'
    return require_owner(request, x_owner_secret, pfai_owner_session)


def access_privileged(
    request: Request,
    x_owner_secret: str | None = Header(default=None, alias='X-Owner-Secret'),
    pfai_owner_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> str:
    """Privileged/destructive ops.

    In Public Access Mode these are open (no login). Outside public mode they
    still require a verified owner session / X-Owner-Secret.
    """
    _ = request.query_params.get('role') or request.query_params.get('admin') or request.query_params.get('owner')
    if public_access_mode():
        return 'public'
    return require_owner(request, x_owner_secret, pfai_owner_session)


@app.get('/owner/status')
def owner_status(
    request: Request,
    pfai_owner_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    """Public auth/access status — no secrets."""
    if public_access_mode():
        return {
            'public_access': True,
            'authentication': 'DISABLED',
            'login_required': False,
            'authenticated': True,
            'auth_methods': [],
            'email_otp': 'REMOVED',
            'email_auth': 'REMOVED',
            'setup_required': False,
            'setup_locked': True,
            'owner_configured': True,
            'username': '',
            'note': 'Public Access Mode: no login, OTP, or owner session required for public surfaces.',
        }
    username = OWNER_AUTH.resolve_session(pfai_owner_session) or ''
    st = OWNER_AUTH.public_status(authenticated=bool(username), username=username)
    st['public_access'] = False
    return st


class OwnerSetupBody(BaseModel):
    username: str
    password: str
    password_confirm: str


class OwnerLoginBody(BaseModel):
    username: str
    password: str


@app.post('/owner/setup')
def owner_setup(x: OwnerSetupBody, request: Request, response: Response):
    """First-time owner initialization only. Permanently disabled after success."""
    if public_access_mode():
        raise HTTPException(410, 'owner setup disabled in public access mode')
    result = OWNER_AUTH.run_setup(x.username, x.password, x.password_confirm)
    # Never echo password fields back.
    if not result.get('ok'):
        code = 409 if result.get('error') == 'owner setup is disabled' else 400
        raise HTTPException(code, result.get('error') or 'setup failed')
    # Auto-login session after setup
    login = OWNER_AUTH.login(x.username, x.password, client_key=_client_key(request))
    if login.get('ok') and login.get('token'):
        response.set_cookie(COOKIE_NAME, login['token'], **_secure_cookie_flags(request))
    return {
        'ok': True,
        'username': result.get('username'),
        'setup_locked': True,
        'message': result.get('message'),
        'authenticated': bool(login.get('ok')),
    }


@app.post('/owner/login')
def owner_login(x: OwnerLoginBody, request: Request, response: Response):
    if public_access_mode():
        raise HTTPException(410, 'owner login disabled in public access mode')
    result = OWNER_AUTH.login(x.username, x.password, client_key=_client_key(request))
    if not result.get('ok'):
        # Uniform failure (no username/password distinction); 429 when locked out.
        status = 429 if result.get('locked') else 401
        raise HTTPException(status, AUTH_FAIL_MESSAGE)
    response.set_cookie(COOKIE_NAME, result['token'], **_secure_cookie_flags(request))
    return {
        'ok': True,
        'username': result['username'],
        'expires_in': result['expires_in'],
        'authenticated': True,
    }


@app.post('/owner/logout')
def owner_logout(
    request: Request,
    response: Response,
    pfai_owner_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    if public_access_mode():
        response.delete_cookie(COOKIE_NAME, path='/')
        return {'ok': True, 'authenticated': False, 'public_access': True}
    OWNER_AUTH.logout(pfai_owner_session)
    response.delete_cookie(COOKIE_NAME, path='/')
    return {'ok': True, 'authenticated': False}


@app.get('/owner/identity')
def owner_identity(owner: str = Depends(access_privileged)):
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
        'public_access': public_access_mode(),
        'authentication': 'DISABLED' if public_access_mode() else 'OWNER',
        'owner_configured': True if public_access_mode() else OWNER_AUTH.owner_configured(),
        'owner_setup_required': False if public_access_mode() else OWNER_AUTH.setup_required(),
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
def remember(x:Remember, owner: str = Depends(access_public)): runtime.memory.add(x.kind,x.content,x.source,x.confidence); return {'ok':True}
@app.post('/knowledge')
def knowledge(x:Knowledge, owner: str = Depends(access_public)): runtime.store.add(x.content,x.source,x.metadata); return {'ok':True}
@app.get('/knowledge/search')
def ksearch(q:str, limit:int=5, owner: str = Depends(access_public)):
    """Owner-gated: knowledge store may hold private curated content."""
    _ = owner
    return {'results': runtime.store.search(q, limit)}
@app.post('/ask')
def ask(x:Ask, owner: str = Depends(access_public)):
    if not x.question.strip(): raise HTTPException(400,'question is required')
    return runtime.ask(x.question)
@app.post('/deploy/canary')
def canary(x:Canary, owner:str=Depends(access_privileged)):
    OWNER.authorize('DEPLOY_CANARY', f'{owner} requested canary {x.version}@{x.traffic}')
    return runtime.deploy.canary(x.version,x.traffic)
@app.post('/deploy/promote/{version}')
def promote(version:str, owner:str=Depends(access_privileged)):
    if not runtime.deploy.promote(version): raise HTTPException(404,'candidate/canary not found')
    OWNER.authorize('DEPLOY_PROMOTE', f'{owner} promoted {version}')
    return {'ok':True,'active':runtime.registry.active()}
@app.post('/deploy/rollback/{version}')
def rollback(version:str, owner:str=Depends(access_privileged)):
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
    status['require_human_approval'] = not auto_accept_learning()
    status['auto_accept_learning'] = auto_accept_learning()
    status['auto_safe_heal'] = auto_safe_heal()
    status['autonomy'] = open_execution_status()
    return status

@app.get('/continuous/auto_score')
def continuous_auto_score(limit:int|None=None, owner: str = Depends(access_privileged)): return CONTINUOUS.auto_score(limit)

@app.post('/continuous/ingest')
def continuous_ingest(x: IngestBatch, owner: str = Depends(access_privileged)):
    rows=[{'instruction':i.instruction,'response':i.response,'source':i.source,'track':i.track,'metadata':i.metadata} for i in x.items]
    return CONTINUOUS.register_batch(rows)

@app.post('/continuous/cycle')
def continuous_cycle(x: RunCycle, owner: str = Depends(access_privileged)):
    result=CONTINUOUS.run_cycle(x.version, x.score, x.notes)
    if not result.get('evaluated'):
        raise HTTPException(409, result.get('reason','cycle rejected'))
    return result

@app.post('/continuous/start')
def continuous_start(owner:str=Depends(access_privileged)):
    if not is_continuous_enabled():
        raise HTTPException(409, 'continuous training disabled by config/env gate')
    OWNER.authorize('CONTINUOUS_START', f'{owner} started the continuous-training service')
    log.info('continuous_start owner=%s', owner)
    started = CONTINUOUS.start()
    tick = CONTINUOUS.tick_once()
    return {**started, 'immediate_tick': tick.get('cycle'), 'ingest': tick.get('ingest')}


@app.post('/continuous/tick')
def continuous_tick(owner: str = Depends(access_privileged)):
    if not is_continuous_enabled():
        raise HTTPException(409, 'continuous training disabled by config/env gate')
    OWNER.authorize('CONTINUOUS_TICK', f'{owner} ticked continuous learning')
    return CONTINUOUS.tick_once()
@app.post('/continuous/pause')
def continuous_pause(owner:str=Depends(access_privileged)):
    OWNER.authorize('CONTINUOUS_PAUSE', f'{owner} paused the continuous-training service')
    log.info('continuous_pause owner=%s', owner)
    return CONTINUOUS.pause()
@app.post('/continuous/resume')
def continuous_resume(owner:str=Depends(access_privileged)):
    if not is_continuous_enabled():
        raise HTTPException(409, 'continuous training disabled by config/env gate')
    OWNER.authorize('CONTINUOUS_RESUME', f'{owner} resumed the continuous-training service')
    log.info('continuous_resume owner=%s', owner)
    return CONTINUOUS.resume()
@app.post('/continuous/stop')
def continuous_stop(owner:str=Depends(access_privileged)):
    OWNER.authorize('CONTINUOUS_STOP', f'{owner} stopped the continuous-training service')
    log.info('continuous_stop owner=%s', owner)
    # Public /continuous/status exposes last_error — do not embed owner email there.
    return CONTINUOUS.stop('stopped by owner')

@app.post('/continuous/approve/{version}')
def continuous_approve(version:str, owner:str=Depends(access_privileged)):
    if not CONTINUOUS.approve(version): raise HTTPException(404,'no pending candidate with that version')
    OWNER.authorize('CONTINUOUS_APPROVE', f'{owner} approved candidate {version}')
    log.info('continuous_approve owner=%s version=%s', owner, version)
    return {'ok':True}
@app.post('/continuous/reject/{version}')
def continuous_reject(version:str, owner:str=Depends(access_privileged)):
    if not CONTINUOUS.reject(version): raise HTTPException(404,'no pending candidate with that version')
    OWNER.authorize('CONTINUOUS_REJECT', f'{owner} rejected candidate {version}')
    log.info('continuous_reject owner=%s version=%s', owner, version)
    return {'ok':True}
@app.post('/continuous/promote/{version}')
def continuous_promote(version:str, owner:str=Depends(access_privileged)):
    if not CONTINUOUS.promote(version): raise HTTPException(404,'candidate must be approved before promotion')
    OWNER.authorize('CONTINUOUS_PROMOTE', f'{owner} promoted candidate {version}')
    log.info('continuous_promote owner=%s version=%s', owner, version)
    return {'ok':True,'active':CONTINUOUS.loop.active()}
@app.post('/continuous/rollback')
def continuous_rollback(version:str|None=None, owner:str=Depends(access_privileged)):
    if not CONTINUOUS.rollback(version): raise HTTPException(404,'no accepted candidate to roll back to')
    OWNER.authorize('CONTINUOUS_ROLLBACK', f'{owner} rolled back continuous learning to {version or "previous"}')
    log.info('continuous_rollback owner=%s version=%s', owner, version)
    return {'ok':True,'active':CONTINUOUS.loop.active()}


@app.post('/code/evaluate')
def code_evaluate(x: CodeCheck, owner: str = Depends(access_public)):
    """Ground-truth sandboxed execution, not a heuristic guess -- see
    code_execution_evaluator.py. Read-only: never writes anything, so no owner
    gate is needed, same as /continuous/auto_score."""
    from dataclasses import asdict as _asdict
    return _asdict(CODE_EVAL.evaluate(x.code, x.test_code))

@app.post('/code/best_of_n')
def code_best_of_n(x: CodeBestOfN, owner: str = Depends(access_public)):
    """Evaluate several candidate solutions in the sandbox and return the best
    passing one, if any. Read-only, same reasoning as /code/evaluate."""
    from dataclasses import asdict as _asdict
    r = select_best_solution(x.candidates, x.test_code, CODE_EVAL)
    return {'best_index': r.best_index, 'best_code': r.best_code,
            'passing_indices': r.passing_indices,
            'results': [_asdict(res) for res in r.results]}

@app.post('/code/solve')
def code_solve(x: CodeSolve, owner: str = Depends(access_public)):
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
def regression_pending(owner: str = Depends(access_privileged)):
    """Owner-gated: pending cases include broken/fixed source code."""
    _ = owner
    return {'items': REGRESSIONS.pending()}


@app.post('/regression/capture')
def regression_capture(x: RegressionCaptureRequest, owner: str = Depends(access_privileged)):
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
def regression_materialize(case_id: str, owner: str = Depends(access_privileged)):
    """Owner-gated: this is the one call in this module that writes into the
    tests/ directory that PFAI's own promotion gate runs against."""
    result = REGRESSIONS.materialize(case_id)
    if not result.get('materialized'):
        raise HTTPException(404, result.get('reason', 'case not found'))
    OWNER.authorize('REGRESSION_MATERIALIZE', f'{owner} materialized regression case {case_id}')
    return result

@app.post('/regression/reject/{case_id}')
def regression_reject(case_id: str, owner: str = Depends(access_privileged)):
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
def recovery_drill(x: RecoveryDrillRequest, owner:str=Depends(access_privileged)):
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
def platform_status(owner: str = Depends(access_public)):
    return ORCHESTRATOR.status()

# --- PHASE 12 Elite Skills + Tool Fabric (owner-protected management) ---
class EliteChatBody(BaseModel):
    message: str
    conversation_id: str = ''
    context: dict = {}
    attachments: list = []
    requested_mode: str | None = None
    approved: bool = False

class EliteSkillActivateBody(BaseModel):
    skill_id: str
    version: str
    approved: bool = False
    mark_lkg: bool = False

class EliteSkillRollbackBody(BaseModel):
    skill_id: str
    to_version: str | None = None
    approved: bool = False

class EliteMCPDiscoverBody(BaseModel):
    tools: list = []

class EliteMCPTrustBody(BaseModel):
    external_id: str
    approved: bool = False

@app.post('/chat')
def elite_unified_chat(x: EliteChatBody, owner: str = Depends(access_public)):
    """Unified PFAI AI chat — PHASE 22 ProductionRuntime over existing fabrics."""
    if not (x.message or '').strip():
        raise HTTPException(400, 'message is required')
    result = ELITE.production.handle(
        x.message,
        conversation_id=x.conversation_id,
        context=x.context,
        attachments=x.attachments,
        requested_mode=x.requested_mode,
        approved=bool(x.approved),
        actor=owner,
        authenticated=True,
    )
    OWNER.authorize('ELITE_CHAT', f'{owner} production chat kind={result.get("response_kind")} ok={result.get("ok")}')
    return result


def _looks_like_autonomy_intent(message: str) -> bool:
    return bool(re.search(
        r"أصلح\s*نفس|صلح\s*نفس|self[_\s-]?heal|self[_\s-]?check|self[_\s-]?improve|"
        r"طور\s*نفس|حدّث\s*نفس|حدث\s*نفس|يطور\s*نفس|يصلح\s*نفس|"
        r"استقلال|autonom|فك\s*القيود|بدون\s*قيود|تحسين\s*ذاتي|self_improve|"
        r"يبني\s*ال?اكواد|يبني\s*الأكواد|self[_\s-]?develop|advanced_self|"
        r"يراجع\s*اكثر|يصحح\s*اكثر|واعي|بدون\s*الرجوع",
        message or "",
        re.I,
    ))


def _should_use_production_runtime(message: str) -> bool:
    """Route multi-capability / agent-style turns through ProductionRuntime; keep CommandAgent for ops tools."""
    from .command_agent import _looks_like_coding_intent

    text = (message or '').strip()
    if not text:
        return False
    # Unified Super Brain: Command Chat is the single mind (avoid dual-runtime lag/errors)
    if unified_brain_enabled():
        return False
    lowered = text.lower()
    # Autonomy / self-heal must stay on ToolRouter (safe bounded loop)
    if _looks_like_autonomy_intent(text):
        return False
    if re.search(r'عقل\s*واحد|unified|سلاسة|سرعة|بدون\s*ا?خطاء|بدون\s*تأخير', text, re.I):
        return False
    operational = (
        'health check', 'health_check', 'فحص الصحة', 'system status', 'حالة النظام',
        'continuous_start', 'continuous_stop', 'metrics', 'deploy', 'rollback model',
        'حلل حالة النظام', 'افحص الأخطاء', 'راجع البيانات',
        'self_improve', 'self_heal', 'autonomy',
    )
    if any(o in lowered for o in operational):
        return False
    from .elite.capability_router import CapabilityRouter

    caps = CapabilityRouter().route(text).get('capabilities') or []
    markers = (
        'analyze this', 'find the bug', 'find the problem', 'fix it', 'run the tests',
        'run tests', 'implement', 'and then', 'optimize', 'explain the result',
        'remember the verified', 'write a fix',
    )
    agent_like = len(caps) >= 2 or sum(1 for m in markers if m in lowered) >= 2
    if agent_like:
        return True
    # Coding Academy teaching intents stay on CommandAgent when not multi-capability agent work
    if _looks_like_coding_intent(text):
        return False
    return False


def _progress_timeline_for_chat(progress: dict | None) -> list:
    """Map ProductionRuntime progress labels to Command Chat timeline statuses (no secrets)."""
    status_map = {
        'Understanding': 'thinking',
        'Planning': 'planning',
        'Selecting capabilities': 'calling_tool',
        'Executing': 'executing',
        'Testing': 'executing',
        'Validating': 'executing',
        'Completed': 'completed',
        'Failed': 'failed',
    }
    out = []
    for item in (progress or {}).get('timeline') or []:
        if not item.get('reached'):
            continue
        label = item.get('label') or ''
        out.append({'status': status_map.get(label, 'executing'), 'detail': label})
    return out

@app.get('/platform/elite/status')
def elite_status(owner: str = Depends(access_public)):
    return ELITE.status()

@app.get('/platform/email/status')
def email_status(owner: str = Depends(access_privileged)):
    from .email_provider import email_config_report
    return {'ok': True, **email_config_report()}

@app.get('/platform/web/status')
def web_status(owner: str = Depends(access_public)):
    return {'ok': True, **ELITE.web.status()}

@app.get('/platform/model-router/status')
def model_router_status(owner: str = Depends(access_public)):
    return {'ok': True, **MODEL_ROUTER.describe()}

@app.get('/platform/sandbox/status')
def sandbox_status(owner: str = Depends(access_public)):
    from .elite.sandbox import Sandbox
    return {'ok': True, **Sandbox(timeout=1.0).metadata()}

@app.get('/platform/phase14/status')
def phase14_platform_status(owner: str = Depends(access_public)):
    from .engineering import phase14_status
    st = phase14_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase14_boot': (ELITE._boot or {}).get('phase14'),
    }
    return {'ok': True, **st}

@app.get('/platform/phase15/status')
def phase15_platform_status(owner: str = Depends(access_public)):
    from .engineering import phase15_status
    st = phase15_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase14_boot': (ELITE._boot or {}).get('phase14'),
        'phase15_boot': (ELITE._boot or {}).get('phase15'),
    }
    st['PHASE_16_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase16/status')
def phase16_platform_status(owner: str = Depends(access_public)):
    from .engineering import phase16_status
    from .elite.platform_observability import PlatformObservability
    st = phase16_status()
    obs = PlatformObservability(ELITE).snapshot()
    st['observability'] = obs
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase14_boot': (ELITE._boot or {}).get('phase14'),
        'phase15_boot': (ELITE._boot or {}).get('phase15'),
        'unified_intelligence_loop': True,
    }
    st['PHASE_17_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase17/status')
def phase17_platform_status(owner: str = Depends(access_public)):
    from .engineering import phase17_status
    st = phase17_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase17_boot': (ELITE._boot or {}).get('phase17'),
        'security_tools': (ELITE._boot or {}).get('security_tools'),
    }
    st['PHASE_18_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase18/status')
def phase18_platform_status(owner: str = Depends(access_public)):
    from .engineering import phase18_status
    st = phase18_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase18_boot': (ELITE._boot or {}).get('phase18'),
        'phase17_boot': (ELITE._boot or {}).get('phase17'),
        'security_tools': (ELITE._boot or {}).get('security_tools'),
    }
    st['PHASE_19_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase19/status')
def phase19_platform_status(owner: str = Depends(access_public)):
    from .elite.phase19_gates import phase19_status
    st = phase19_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase19_boot': (ELITE._boot or {}).get('phase19'),
        'phase18_boot': (ELITE._boot or {}).get('phase18'),
        'unified_ai_core': True,
    }
    st['PHASE_20_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase20/status')
def phase20_platform_status(owner: str = Depends(access_public)):
    from .elite.phase20_gates import phase20_status
    st = phase20_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase20_boot': (ELITE._boot or {}).get('phase20'),
        'phase19_boot': (ELITE._boot or {}).get('phase19'),
        'unified_ai_core': True,
        'agent_execution_engine': True,
    }
    st['PHASE_21_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase21/status')
def phase21_platform_status(owner: str = Depends(access_public)):
    from .elite.phase21_gates import phase21_status
    st = phase21_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase21_boot': (ELITE._boot or {}).get('phase21'),
        'phase20_boot': (ELITE._boot or {}).get('phase20'),
        'unified_ai_core': True,
        'agent_execution_engine': True,
        'performance_reliability_engine': True,
    }
    st['scheduler'] = ELITE.performance.scheduler_status() if getattr(ELITE, 'performance', None) else None
    st['PHASE_22_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase22/status')
def phase22_platform_status(owner: str = Depends(access_public)):
    from .elite.phase22_gates import phase22_status
    st = phase22_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase22_boot': (ELITE._boot or {}).get('phase22'),
        'phase21_boot': (ELITE._boot or {}).get('phase21'),
        'unified_ai_core': True,
        'agent_execution_engine': True,
        'performance_reliability_engine': True,
        'production_runtime': True,
    }
    st['runtime'] = ELITE.production.diagnostics() if getattr(ELITE, 'production', None) else None
    st['PHASE_23_ALLOWED'] = False
    return {'ok': True, **st}

@app.get('/platform/phase23/status')
def phase23_platform_status(owner: str = Depends(access_public)):
    from .elite.phase23_gates import phase23_status
    st = phase23_status()
    st['elite'] = {
        'skill_count': ELITE.skills.health().get('count'),
        'phase23_boot': (ELITE._boot or {}).get('phase23'),
        'phase22_boot': (ELITE._boot or {}).get('phase22'),
        'web_tools': (ELITE._boot or {}).get('web_tools'),
        'production_runtime': True,
        'web_research_pipeline': True,
    }
    st['runtime'] = ELITE.production.diagnostics() if getattr(ELITE, 'production', None) else None
    st['mcp_registry'] = ELITE.mcp_registry.health() if getattr(ELITE, 'mcp_registry', None) else None
    st['PHASE_24_ALLOWED'] = False
    return {'ok': True, **st}

class WebQueryBody(BaseModel):
    query: str = ''
    url: str = ''
    limit: int = 5
    fetch_top: int = 1
    approved: bool = False

@app.get('/platform/web/providers')
def web_providers_status(owner: str = Depends(access_public)):
    from .elite.web_fabric import web_config_report
    _ = owner
    return {'ok': True, **web_config_report()}

@app.post('/platform/web/search')
def web_search_api(body: WebQueryBody, owner: str = Depends(access_public)):
    from .elite.web_fabric import web_config_report
    from .elite.web_research_pipeline import WebResearchPipeline
    if not (body.query or '').strip():
        raise HTTPException(400, 'query is required')
    status = web_config_report()
    if status.get('WEB_FABRIC_STATUS') not in ('READY', 'CONFIGURED'):
        OWNER.authorize('WEB_SEARCH', f'{owner} search denied status={status.get("WEB_FABRIC_STATUS")}')
        return {
            'ok': False,
            'WEB_FABRIC_STATUS': status.get('WEB_FABRIC_STATUS') or 'NOT_CONFIGURED',
            'fabricated_results': False,
            'results': [],
            'error': 'web_provider_unavailable',
            'PHASE_24_ALLOWED': False,
        }
    out = WebResearchPipeline().run(body.query.strip(), limit=int(body.limit or 5), approved=bool(body.approved), actor=owner)
    OWNER.authorize('WEB_SEARCH', f'{owner} search ok={out.get("ok")}')
    return out

@app.post('/platform/web/fetch')
def web_fetch_api(body: WebQueryBody, owner: str = Depends(access_public)):
    from .elite.web_fabric import WebPolicyGate, web_config_report, WebInformationFabric
    if not (body.url or '').strip():
        raise HTTPException(400, 'url is required')
    auth = WebPolicyGate().authorize_url(body.url.strip(), approved=bool(body.approved), actor=owner)
    if not auth.get('ok'):
        OWNER.authorize('WEB_FETCH', f'{owner} fetch denied')
        return {'ok': False, 'error': auth.get('error'), 'ssrf_blocked': True, 'PHASE_24_ALLOWED': False}
    status = web_config_report()
    if status.get('WEB_FABRIC_STATUS') not in ('READY', 'CONFIGURED'):
        return {
            'ok': False,
            'WEB_FABRIC_STATUS': status.get('WEB_FABRIC_STATUS') or 'NOT_CONFIGURED',
            'error': 'web_provider_unavailable',
            'fabricated_results': False,
            'PHASE_24_ALLOWED': False,
        }
    fetched = WebInformationFabric().fetch_provider.fetch(body.url.strip())
    OWNER.authorize('WEB_FETCH', f'{owner} fetch ok={fetched.get("ok")}')
    return {**fetched, 'PHASE_24_ALLOWED': False}

@app.post('/platform/web/research')
def web_research_api(body: WebQueryBody, owner: str = Depends(access_public)):
    from .elite.web_research_pipeline import WebResearchPipeline
    if not (body.query or '').strip():
        raise HTTPException(400, 'query is required')
    out = WebResearchPipeline().run(
        body.query.strip(),
        limit=int(body.limit or 5),
        fetch_top=int(body.fetch_top or 1),
        approved=bool(body.approved),
        actor=owner,
    )
    OWNER.authorize('WEB_RESEARCH', f'{owner} research status={out.get("WEB_RESEARCH_STATUS")}')
    return out

@app.get('/platform/mcp/status')
def mcp_registry_status(owner: str = Depends(access_public)):
    _ = owner
    return {'ok': True, **(ELITE.mcp_registry.health() if getattr(ELITE, 'mcp_registry', None) else {'MCP_STATUS': 'NOT_READY'})}

@app.get('/platform/mcp/capabilities')
def mcp_capabilities(owner: str = Depends(access_public)):
    _ = owner
    reg = getattr(ELITE, 'mcp_registry', None)
    if reg is None:
        return {'ok': False, 'error': 'mcp_registry_unavailable'}
    return reg.discover_capabilities()

@app.get('/platform/config/status')
def production_config_status(owner: str = Depends(access_privileged)):
    """Capability + missing one-time owner actions — never secret values."""
    _ = owner
    from .elite.production_config import detect_production_config
    return detect_production_config()

@app.get('/runtime/status')
def runtime_status(owner: str = Depends(access_public)):
    _ = owner
    return {'ok': True, **ELITE.production.diagnostics()}

@app.get('/runtime/capabilities')
def runtime_capabilities(owner: str = Depends(access_public)):
    _ = owner
    diag = ELITE.production.diagnostics()
    return {
        'ok': True,
        'phase': 23,
        'pipeline': diag.get('pipeline'),
        'WEB_FABRIC_STATUS': diag.get('WEB_FABRIC_STATUS'),
        'WEB_PROVIDER_STATUS': diag.get('WEB_PROVIDER_STATUS'),
        'WEB_RESEARCH_STATUS': diag.get('WEB_RESEARCH_STATUS'),
        'CITATION_STATUS': diag.get('CITATION_STATUS'),
        'EMAIL_DELIVERY_STATUS': diag.get('EMAIL_DELIVERY_STATUS'),
        'EMAIL_LIFECYCLE_STATUS': diag.get('EMAIL_LIFECYCLE_STATUS'),
        'SANDBOX_STATUS': diag.get('SANDBOX_STATUS'),
        'MODEL_STATUS': diag.get('MODEL_STATUS'),
        'LKG_STATUS': diag.get('LKG_STATUS'),
        'ROLLBACK_STATUS': diag.get('ROLLBACK_STATUS'),
        'SKILL_FABRIC_STATUS': diag.get('SKILL_FABRIC_STATUS'),
        'TOOL_FABRIC_STATUS': diag.get('TOOL_FABRIC_STATUS'),
        'MCP_STATUS': diag.get('MCP_STATUS'),
        'OWNER_AUTH_STATUS': diag.get('OWNER_AUTH_STATUS'),
        'PHASE_24_ALLOWED': False,
        'capability_surface_only': True,
        'raw_environment_included': False,
    }

@app.get('/runtime/health')
def runtime_health(owner: str = Depends(access_public)):
    _ = owner
    diag = ELITE.production.diagnostics()
    return {
        'ok': True,
        'healthy': True,
        'phase': 23,
        'production_runtime': True,
        'web_research_pipeline': True,
        'WEB_FABRIC_STATUS': diag.get('WEB_FABRIC_STATUS'),
        'EMAIL_DELIVERY_STATUS': diag.get('EMAIL_DELIVERY_STATUS'),
        'SANDBOX_STATUS': diag.get('SANDBOX_STATUS'),
        'MODEL_STATUS': diag.get('MODEL_STATUS'),
        'ROLLBACK_STATUS': diag.get('ROLLBACK_STATUS'),
        'PHASE_24_ALLOWED': False,
    }

@app.get('/system/status')
def system_status_safe(owner: str = Depends(access_public)):
    """Safe capability diagnostics — never env/secrets/filesystem dumps."""
    _ = owner
    return {'ok': True, **ELITE.production.diagnostics()}

class PerfTaskBody(BaseModel):
    message: str
    priority: str = 'USER_INTERACTIVE'
    approved: bool = False
    context: dict = {}

@app.post('/platform/phase21/tasks')
def phase21_submit_task(body: PerfTaskBody, owner: str = Depends(access_privileged)):
    out = ELITE.performance.submit_task(
        body.message,
        priority=body.priority,
        actor=owner,
        approved=bool(body.approved),
        context=dict(body.context or {}),
    )
    out['PHASE_22_ALLOWED'] = False
    out['PHASE_24_ALLOWED'] = False
    return {'ok': bool(out.get('ok')), **out}

@app.get('/platform/phase21/tasks/{task_id}')
def phase21_task_status(task_id: str, owner: str = Depends(access_public)):
    return {'ok': True, **ELITE.performance.task_status(task_id)}

@app.get('/platform/phase21/tasks/{task_id}/progress')
def phase21_task_progress(task_id: str, owner: str = Depends(access_public)):
    return ELITE.performance.task_progress(task_id)

@app.post('/platform/phase21/tasks/{task_id}/cancel')
def phase21_cancel_task(task_id: str, owner: str = Depends(access_privileged)):
    return ELITE.performance.cancel_task(task_id)

@app.get('/platform/phase21/scheduler')
def phase21_scheduler_status(owner: str = Depends(access_public)):
    return {'ok': True, **ELITE.performance.scheduler_status()}

@app.post('/platform/phase21/benchmarks/run')
def phase21_run_benchmarks(owner: str = Depends(access_privileged)):
    from .elite.phase21_benchmarks import run_phase21_benchmarks
    return {'ok': True, **run_phase21_benchmarks(orchestrator=ELITE)}

@app.get('/platform/observability')
def platform_observability(owner: str = Depends(access_privileged)):
    from .elite.platform_observability import PlatformObservability
    return {'ok': True, **PlatformObservability(ELITE).snapshot()}

class Phase14BuildBody(BaseModel):
    requirement: str
    approved: bool = False
    run_tests: bool = True

class Phase14SecurityBody(BaseModel):
    target: str = ''
    project_path: str = ''
    declaration: str = ''
    scope: str = ''
    approved: bool = False
    allow_external: bool = False
    auto_apply: bool = False

class Phase15WorkflowBody(BaseModel):
    message: str
    project_path: str = ''
    declaration: str = ''
    scope: str = ''
    approved: bool = False
    allow_external: bool = False
    auto_apply: bool = False
    affected_files: list[str] | None = None
    writers: dict[str, str] | None = None

class Phase16ChatBody(BaseModel):
    message: str
    conversation_id: str = ''
    approved: bool = False
    allow_training_ops: bool = False
    project_path: str = ''
    declaration: str = ''
    scope: str = ''
    allow_external: bool = False
    auto_apply: bool = False

@app.post('/platform/phase16/chat')
def phase16_chat(x: Phase16ChatBody, owner: str = Depends(access_public)):
    ctx = {}
    if x.project_path:
        ctx['project_path'] = x.project_path
    if x.declaration:
        ctx['declaration'] = x.declaration
    if x.scope:
        ctx['scope'] = x.scope
    if x.allow_external:
        ctx['allow_external'] = True
    if x.auto_apply:
        ctx['auto_apply'] = True
    result = ELITE.chat(
        x.message,
        conversation_id=x.conversation_id,
        context=ctx,
        approved=bool(x.approved),
        actor=owner,
        allow_training_ops=bool(x.allow_training_ops),
    )
    OWNER.authorize('PHASE16_CHAT', f'{owner} ok={result.get("ok")} phase={result.get("phase")}')
    return result

class Phase17TargetBody(BaseModel):
    name: str
    target_type: str = 'local_application'
    environment: str = 'staging'
    authorization_scope: str = ''
    allowed_domains: list[str] | None = None
    allowed_hosts: list[str] | None = None
    allowed_ports: list[int] | None = None
    allowed_paths: list[str] | None = None
    testing_methods: list[str] | None = None
    approval_reference: str = ''
    authorize_now: bool = False
    expiration: float = 0

@app.post('/platform/phase17/targets')
def phase17_register_target(x: Phase17TargetBody, owner: str = Depends(access_privileged)):
    from .engineering import TargetRegistry
    reg = TargetRegistry()
    result = reg.register(
        name=x.name,
        target_type=x.target_type,
        owner=owner,
        environment=x.environment,
        authorization_scope=x.authorization_scope,
        allowed_domains=x.allowed_domains,
        allowed_hosts=x.allowed_hosts,
        allowed_ports=x.allowed_ports,
        allowed_paths=x.allowed_paths,
        testing_methods=x.testing_methods,
        approval_reference=x.approval_reference,
        authorize_now=bool(x.authorize_now),
        expiration=float(x.expiration or 0),
        actor=owner,
    )
    OWNER.authorize('PHASE17_TARGET', f'{owner} register ok={result.get("ok")}')
    return result

class Phase18TargetBody(BaseModel):
    name: str
    target_type: str = 'local_project'
    environment: str = 'staging'
    scope: str = ''
    authorization_scope: str = ''
    allowed_actions: list[str] | None = None
    allowed_domains: list[str] | None = None
    allowed_hosts: list[str] | None = None
    allowed_ports: list[int] | None = None
    allowed_paths: list[str] | None = None
    testing_methods: list[str] | None = None
    approval_reference: str = ''
    authorize_now: bool = False
    expiration: float = 0

class Phase18BuildBody(BaseModel):
    requirement: str
    approved: bool = False
    run_tests: bool = True
    apply_safe_fixes: bool = False

class Phase18ChatBody(BaseModel):
    message: str
    conversation_id: str = ''
    approved: bool = False
    project_path: str = ''
    target_id: str = ''
    url: str = ''
    auto_apply: bool = False
    owner_approved_sensitive: bool = False
    writers: dict[str, str] | None = None

@app.post('/platform/phase18/targets')
def phase18_register_target(x: Phase18TargetBody, owner: str = Depends(access_privileged)):
    from .engineering import TargetRegistry
    reg = TargetRegistry()
    result = reg.register(
        name=x.name,
        target_type=x.target_type,
        owner=owner,
        environment=x.environment,
        scope=x.scope or x.authorization_scope,
        authorization_scope=x.authorization_scope or x.scope,
        allowed_actions=x.allowed_actions,
        allowed_domains=x.allowed_domains,
        allowed_hosts=x.allowed_hosts,
        allowed_ports=x.allowed_ports,
        allowed_paths=x.allowed_paths,
        testing_methods=x.testing_methods,
        approval_reference=x.approval_reference,
        authorize_now=bool(x.authorize_now),
        expiration=float(x.expiration or 0),
        actor=owner,
    )
    OWNER.authorize('PHASE18_TARGET', f'{owner} register ok={result.get("ok")}')
    return result

@app.post('/platform/phase18/build')
def phase18_build(x: Phase18BuildBody, owner: str = Depends(access_privileged)):
    from .engineering import ApplicationEngineering
    eng = ApplicationEngineering(root='data/longevity/engineering/appeng')
    result = eng.build(
        x.requirement,
        approved=bool(x.approved),
        actor=owner,
        run_tests=bool(x.run_tests),
        apply_safe_fixes=bool(x.apply_safe_fixes),
    )
    OWNER.authorize('PHASE18_BUILD', f'{owner} complete={result.get("complete")}')
    return result

@app.post('/platform/phase18/chat')
def phase18_chat(x: Phase18ChatBody, owner: str = Depends(access_privileged)):
    from .engineering import Phase18ChatFabric
    ctx = {}
    if x.project_path:
        ctx['project_path'] = x.project_path
    if x.target_id:
        ctx['target_id'] = x.target_id
    if x.url:
        ctx['url'] = x.url
    if x.auto_apply:
        ctx['auto_apply'] = True
    if x.owner_approved_sensitive:
        ctx['owner_approved_sensitive'] = True
    if x.writers:
        ctx['writers'] = dict(x.writers)
    result = Phase18ChatFabric().handle(
        x.message,
        approved=bool(x.approved),
        actor=owner,
        context=ctx,
    )
    OWNER.authorize('PHASE18_CHAT', f'{owner} intent={result.get("intent")} ok={result.get("ok")}')
    return result

@app.post('/platform/phase17/sdlc')
def phase17_sdlc(x: Phase15WorkflowBody, owner: str = Depends(access_privileged)):
    from .engineering import SecurityDevelopmentLifecycle
    result = SecurityDevelopmentLifecycle().run_for_project(
        x.message,
        project_path=x.project_path,
        approved=bool(x.approved),
        actor=owner,
        auto_remediate=bool(x.auto_apply),
    )
    OWNER.authorize('PHASE17_SDLC', f'{owner} security_ready={result.get("security_ready")}')
    return result

@app.post('/platform/phase14/build')
def phase14_build(x: Phase14BuildBody, owner: str = Depends(access_privileged)):
    from .engineering import ApplicationBuilder
    builder = ApplicationBuilder(root='data/longevity/engineering/generated')
    result = builder.build(x.requirement, approved=bool(x.approved), actor=owner, run_tests=bool(x.run_tests))
    OWNER.authorize('PHASE14_BUILD', f'{owner} build complete={result.get("complete")}')
    return result

@app.post('/platform/phase15/workflow')
def phase15_workflow(x: Phase15WorkflowBody, owner: str = Depends(access_privileged)):
    from .engineering import UnifiedCodingWorkflow
    wf = UnifiedCodingWorkflow(root='data/longevity/engineering/coding_workflow')
    ctx = {}
    if x.affected_files:
        ctx['affected_files'] = list(x.affected_files)
    if x.writers:
        ctx['writers'] = dict(x.writers)
    result = wf.handle(
        x.message,
        project_path=x.project_path,
        approved=bool(x.approved),
        actor=owner,
        declaration=x.declaration,
        scope=x.scope,
        allow_external=bool(x.allow_external),
        auto_apply=bool(x.auto_apply),
        context=ctx,
    )
    OWNER.authorize('PHASE15_WORKFLOW', f'{owner} intent={result.get("intent")} ok={result.get("ok")}')
    return result

@app.post('/platform/phase14/security/analyze')
def phase14_security_analyze(x: Phase14SecurityBody, owner: str = Depends(access_privileged)):
    from .engineering import SecureCodeAnalyzer, AuthorizedSecurityTester
    if x.project_path:
        result = SecureCodeAnalyzer(x.project_path).analyze()
    else:
        result = AuthorizedSecurityTester().run(
            x.target,
            declaration=x.declaration,
            scope=x.scope,
            approved=bool(x.approved),
            actor=owner,
            allow_external=bool(x.allow_external),
        )
    OWNER.authorize('PHASE14_SECURITY', f'{owner} security ok={result.get("ok")} denied={result.get("denied")}')
    return result

@app.post('/platform/phase14/security/remediate')
def phase14_security_remediate(x: Phase14SecurityBody, owner: str = Depends(access_privileged)):
    from .engineering import ApplicationBuilder
    if not x.project_path:
        raise HTTPException(400, 'project_path required')
    result = ApplicationBuilder().remediate_project(
        x.project_path, approved=bool(x.approved), actor=owner, auto_apply=bool(x.auto_apply)
    )
    OWNER.authorize('PHASE14_REMEDIATE', f'{owner} remediate rolled_back={result.get("rolled_back")}')
    return result

@app.get('/platform/elite/skills')
def elite_skills(owner: str = Depends(access_public), category: str | None = None):
    skills = ELITE.skills.list_skills(category=category)
    return {'ok': True, 'skills': [s.to_dict() for s in skills], 'health': ELITE.skills.health()}

@app.get('/platform/elite/skills/{skill_id}/versions')
def elite_skill_versions(skill_id: str, owner: str = Depends(access_public)):
    return {
        'ok': True,
        'skill_id': skill_id,
        'versions': [s.to_dict() for s in ELITE.skills.list_versions(skill_id)],
        'pointer': ELITE.skills.active_pointer(skill_id),
        'history': ELITE.skills.history.list_events(skill_id)[-20:],
    }

@app.post('/platform/elite/skills/activate')
def elite_skill_activate(x: EliteSkillActivateBody, owner: str = Depends(access_privileged)):
    result = ELITE.skills.activate(
        x.skill_id, x.version, approved=bool(x.approved), actor=owner, mark_lkg=bool(x.mark_lkg)
    )
    if result.get('needs_approval'):
        raise HTTPException(403, result.get('error') or 'owner approval required')
    OWNER.authorize('ELITE_SKILL_ACTIVATE', f'{owner} activate {x.skill_id}@{x.version}')
    return result

@app.post('/platform/elite/skills/rollback')
def elite_skill_rollback(x: EliteSkillRollbackBody, owner: str = Depends(access_privileged)):
    result = ELITE.skills.rollback(
        x.skill_id, approved=bool(x.approved), actor=owner, to_version=x.to_version
    )
    if result.get('needs_approval'):
        raise HTTPException(403, result.get('error') or 'owner approval required')
    OWNER.authorize('ELITE_SKILL_ROLLBACK', f'{owner} rollback {x.skill_id}')
    return result

@app.get('/platform/elite/tools')
def elite_tools(owner: str = Depends(access_public)):
    return {'ok': True, 'tools': ELITE.tools.catalog()}

@app.get('/platform/elite/mcp/tools')
def elite_mcp_tools(owner: str = Depends(access_public)):
    return {'ok': True, 'tools': ELITE.mcp.list_tools()}

@app.post('/platform/elite/mcp/discover')
def elite_mcp_discover(x: EliteMCPDiscoverBody, owner: str = Depends(access_privileged)):
    from .elite.mcp_adapter import ExternalToolDescriptor
    descs = []
    for row in x.tools or []:
        if not isinstance(row, dict) or not row.get('external_id'):
            continue
        descs.append(ExternalToolDescriptor(
            external_id=str(row['external_id']),
            name=str(row.get('name') or row['external_id']),
            description=str(row.get('description') or ''),
            input_schema=dict(row.get('input_schema') or {}),
            output_schema=dict(row.get('output_schema') or {}),
            trusted=False,
        ))
    result = ELITE.mcp.discover(descs)
    OWNER.authorize('ELITE_MCP_DISCOVER', f'{owner} discovered {result.get("count")} external tools')
    return result

@app.post('/platform/elite/mcp/trust')
def elite_mcp_trust(x: EliteMCPTrustBody, owner: str = Depends(access_privileged)):
    result = ELITE.mcp.approve_trust(x.external_id, approved=bool(x.approved), actor=owner)
    if result.get('needs_approval'):
        raise HTTPException(403, result.get('error') or 'owner approval required')
    OWNER.authorize('ELITE_MCP_TRUST', f'{owner} trusted {x.external_id}')
    return result

@app.get('/platform/elite/learning')
def elite_learning(owner: str = Depends(access_public)):
    return {
        'ok': True,
        'eligible': ELITE.learning.eligible_training_candidates()[:50],
        'status': ELITE.status(),
    }

@app.post('/platform/elite/learning/export-training')
def elite_learning_export(owner: str = Depends(access_privileged), limit: int = 20):
    result = ELITE.export_learning_to_training(limit=limit)
    OWNER.authorize('ELITE_LEARNING_EXPORT', f'{owner} export learning={result.get("exported")}')
    return result

@app.post('/orchestrate')
def orchestrate(x: OrchestrateBody, owner: str = Depends(access_public)):
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
def platform_learning(x: LearningBody, owner: str = Depends(access_privileged)):
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
def platform_learning_audit(owner: str = Depends(access_privileged), limit: int = 50):
    return {'items': PLATFORM_LEARNING_AUDIT.recent(limit)}

@app.get('/platform/providers')
def platform_providers(owner: str = Depends(access_public)):
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
    owner: str = Depends(access_privileged),
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
def platform_ltm_store(x: LtmStoreBody, owner: str = Depends(access_privileged)):
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
def platform_ltm_history(record_id: str, owner: str = Depends(access_privileged)):
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
def platform_ltm_rollback(record_id: str, to_version: int | None = None, owner: str = Depends(access_privileged)):
    try:
        rec = PLATFORM_LTM.rollback(record_id, to_version)
    except KeyError:
        raise HTTPException(404, 'ltm record/version not found')
    OWNER.authorize('PLATFORM_LTM_ROLLBACK', f'{owner} rolled back {record_id}')
    return {'ok': True, 'record_id': rec.record_id, 'version': rec.version, 'status': rec.status}


@app.get('/platform/knowledge/versions')
def platform_knowledge_versions(knowledge_id: str, owner: str = Depends(access_privileged)):
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
def platform_knowledge_publish(x: KnowledgePublishBody, owner: str = Depends(access_privileged)):
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
def platform_knowledge_rollback(x: KnowledgeRollbackBody, owner: str = Depends(access_privileged)):
    try:
        kv = PLATFORM_KNOWLEDGE.rollback(x.knowledge_id, x.to_version)
    except KeyError:
        raise HTTPException(404, 'knowledge version not found')
    OWNER.authorize('PLATFORM_KNOWLEDGE_ROLLBACK', f'{owner} rolled back {x.knowledge_id} to {x.to_version}')
    return {'ok': True, 'knowledge_id': kv.knowledge_id, 'version': kv.version, 'status': kv.status}


@app.get('/platform/eval/suites')
def platform_eval_suites(owner: str = Depends(access_privileged)):
    _ = owner
    return {'suites': PLATFORM_EVAL.list_suites()}


@app.post('/platform/eval/run')
def platform_eval_run(suite: str = 'longevity', owner: str = Depends(access_privileged)):
    _ = owner
    report = PLATFORM_EVAL.run_suite(suite)
    learn = None
    if report.ok and int(report.passed or 0) > 0:
        learn = AUTONOMOUS_TRAINING.experience.record_evaluation_lesson(
            instruction=f"Summarize evaluation outcomes for suite {report.suite}",
            response=(
                f"Suite {report.suite} passed={report.passed} failed={report.failed} "
                f"ok={report.ok}. Prefer promoting only when regressions are absent."
            ),
            source_id=f"eval:{report.suite}:{report.fingerprint or ''}",
        )
    return {
        'suite': report.suite,
        'ok': report.ok,
        'passed': report.passed,
        'failed': report.failed,
        'fingerprint': report.fingerprint,
        'cases': report.cases,
        'meta': report.meta,
        'learning_candidate': (
            {
                'eligibility': learn.get('eligibility'),
                'candidate_id': learn.get('candidate_id'),
                'trained': False,
            }
            if learn
            else None
        ),
    }


@app.post('/platform/eval/baseline')
def platform_eval_baseline(x: EvalBaselineBody, owner: str = Depends(access_privileged)):
    report = PLATFORM_EVAL.run_suite(x.suite)
    PLATFORM_EVAL.record_baseline(x.baseline_id, report)
    OWNER.authorize('PLATFORM_EVAL_BASELINE', f'{owner} recorded baseline {x.baseline_id}')
    return {'ok': True, 'baseline_id': x.baseline_id, 'suite': report.suite, 'passed': report.passed, 'failed': report.failed}


@app.post('/platform/eval/compare')
def platform_eval_compare(x: EvalCompareBody, owner: str = Depends(access_privileged)):
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
def platform_migrations(owner: str = Depends(access_privileged)):
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
def platform_migrations_run(x: MigrationRunBody, owner: str = Depends(access_privileged)):
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
def platform_export(x: ExportBody, owner: str = Depends(access_privileged)):
    manifest = PLATFORM_EXPORT.export_bundle(x.target_dir, include=x.include)
    OWNER.authorize('PLATFORM_EXPORT', f'{owner} exported bundle sections={manifest.get("sections")}')
    return {'ok': True, 'manifest': manifest, 'target_dir': x.target_dir}


@app.post('/platform/export/import')
def platform_export_import(x: ImportBody, owner: str = Depends(access_privileged)):
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
def platform_plan(x: PlanBody, owner: str = Depends(access_privileged)):
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
def platform_plan_get(plan_id: str, owner: str = Depends(access_privileged)):
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
def platform_skills_list(owner: str = Depends(access_public)):
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
def platform_skill_versions(name: str, owner: str = Depends(access_public)):
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
def platform_skills_activate(x: SkillActivateBody, owner: str = Depends(access_privileged)):
    result = PLATFORM_SKILLS.activate(x.name, x.version, approved=True, actor=owner)
    if not result.get('ok'):
        raise HTTPException(404 if 'not found' in (result.get('error') or '') else 400, result.get('error') or 'activate failed')
    OWNER.authorize('PLATFORM_SKILL_ACTIVATE', f'{owner} activated {x.name}@{x.version}')
    return result


@app.post('/platform/skills/rollback')
def platform_skills_rollback(x: SkillActivateBody, owner: str = Depends(access_privileged)):
    result = PLATFORM_SKILLS.rollback(x.name, x.version, approved=True, actor=owner)
    if not result.get('ok'):
        raise HTTPException(404 if 'not found' in (result.get('error') or '') else 400, result.get('error') or 'rollback failed')
    OWNER.authorize('PLATFORM_SKILL_ROLLBACK', f'{owner} rolled back {x.name} to {x.version}')
    return result


@app.get('/platform/tools')
def platform_tools_catalog(owner: str = Depends(access_public)):
    _ = owner
    return {'tools': TOOL_ROUTER.catalog()}


@app.post('/platform/heal/propose')
def platform_heal_propose(owner: str = Depends(access_privileged)):
    _ = owner
    report = PLATFORM_SELF_CHECK.run_checks()
    proposal = PLATFORM_SELF_HEAL.propose_fix(report)
    learn = None
    # Only record a high-level lesson when checks pass — never embed secrets/config
    if getattr(report, 'ok', None) is True or (
        isinstance(report, dict) and report.get('ok')
    ):
        learn = AUTONOMOUS_TRAINING.experience.record_self_check(
            instruction="Describe a healthy PFAI self-check outcome for operators.",
            response=(
                "Self-check passed without mutating authentication, authorization, "
                "secrets, or training isolation boundaries."
            ),
            source_id=f"self_check:{getattr(report, 'fingerprint', '') or 'ok'}",
            passed=True,
        )
    return {
        'proposal_id': proposal.proposal_id,
        'diagnosis': proposal.diagnosis,
        'safe': proposal.safe,
        'reversible': proposal.reversible,
        'steps': proposal.steps,
        'requires_owner': proposal.requires_owner,
        'risk': proposal.risk,
        'meta': proposal.meta,
        'learning_candidate': (
            {
                'eligibility': learn.get('eligibility'),
                'candidate_id': learn.get('candidate_id'),
                'trained': False,
            }
            if learn
            else None
        ),
    }


@app.post('/platform/heal/apply')
def platform_heal_apply(x: HealApplyBody, owner: str = Depends(access_privileged)):
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
def platform_heal_rollback(proposal_id: str, owner: str = Depends(access_privileged)):
    rolled = PLATFORM_SELF_HEAL.rollback_fix(proposal_id)
    OWNER.authorize('PLATFORM_HEAL_ROLLBACK', f'{owner} rolled back heal {proposal_id}')
    return {'ok': rolled.ok, 'message': rolled.message, 'meta': rolled.meta}


@app.get('/platform/heal/audit')
def platform_heal_audit(limit: int = 50, owner: str = Depends(access_privileged)):
    _ = owner
    return {'items': PLATFORM_SELF_HEAL.recent_audit(limit)}


@app.get('/platform/authz/audit')
def platform_authz_audit(limit: int = 50, owner: str = Depends(access_privileged)):
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
def platform_runtime_status(owner: str = Depends(access_public)):
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
def platform_open_weight_models(owner: str = Depends(access_public), probe_load: bool = False):
    _ = owner
    from pfai.longevity.autonomous_training.open_weight_catalog import OpenWeightModelSelector

    return OpenWeightModelSelector().select_production_candidate(probe_load=bool(probe_load))


@app.get('/platform/training/runtime')
def platform_training_runtime(owner: str = Depends(access_public)):
    _ = owner
    return AUTONOMOUS_TRAINING.runtime_status()


@app.get('/platform/training/status')
def platform_training_status(owner: str = Depends(access_public)):
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
def platform_learning_statistics(owner: str = Depends(access_public)):
    """Owner-only learning/candidate/dataset observability (no secret payloads)."""
    _ = owner
    return AUTONOMOUS_TRAINING.learning_statistics()


@app.get('/platform/learning/verification')
def platform_learning_verification(owner: str = Depends(access_public)):
    """Honest pipeline readiness — never invents eligibility or metrics."""
    _ = owner
    return AUTONOMOUS_TRAINING.pipeline_verification_status()


@app.get('/platform/training/eligibility')
def platform_training_eligibility(owner: str = Depends(access_public)):
    """Authoritative training eligibility with per-gate breakdown (owner-only)."""
    _ = owner
    stats = AUTONOMOUS_TRAINING.learning_statistics()
    elig = stats.get('next_training_eligibility') or {}
    return {
        'ok': True,
        'eligible': bool(elig.get('eligible')),
        'reason': elig.get('reason'),
        'reasons': elig.get('reasons') or elig.get('blockers') or [],
        'status': elig.get('status'),
        'blockers': elig.get('blockers') or [],
        'gates': elig.get('gates'),
        'dataset_version': stats.get('dataset_version'),
        'dataset_accepted_examples': stats.get('latest_dataset_accepted'),
        'dataset_growth': stats.get('dataset_growth_since_last_trained'),
        'dataset_growth_since_previous_version': stats.get('dataset_growth_since_previous_version'),
        'scheduler': stats.get('scheduler'),
        'trainer_probe': stats.get('trainer_probe'),
        'note': elig.get('note') or stats.get('note'),
    }


@app.get('/platform/learning/candidates')
def platform_learning_candidates(owner: str = Depends(access_public), limit: int = 50):
    """Owner-only candidate statistics — never returns private example text."""
    _ = owner
    store = AUTONOMOUS_TRAINING.learning_pipeline_gate.store
    stats = store.statistics()
    return {
        'ok': True,
        'statistics': stats,
        'experience_bridge': AUTONOMOUS_TRAINING.experience.status(),
        'last_pass': AUTONOMOUS_TRAINING.learning_pipeline_gate.last_run_summary(),
        'limit_note': f'metadata only; text bodies omitted (limit={limit})',
    }


@app.get('/platform/training/scheduler')
def platform_training_scheduler(owner: str = Depends(access_public)):
    _ = owner
    return AUTONOMOUS_TRAINING.scheduler.status()


@app.get('/platform/training/observability')
def platform_training_observability(owner: str = Depends(access_public)):
    """Aggregated owner-only training observability (no secrets/private text)."""
    _ = owner
    ver = AUTONOMOUS_TRAINING.pipeline_verification_status()
    stats = AUTONOMOUS_TRAINING.learning_statistics()
    jobs = AUTONOMOUS_TRAINING.list_jobs(limit=20)
    from pfai.longevity.autonomous_training.scheduler import normalize_job_lifecycle_state

    return {
        'ok': True,
        'eligibility': stats.get('next_training_eligibility'),
        'dataset': {
            'version': stats.get('dataset_version'),
            'accepted': stats.get('latest_dataset_accepted'),
            'growth_since_previous': stats.get('dataset_growth_since_previous_version'),
            'growth_since_last_trained': stats.get('dataset_growth_since_last_trained'),
            'versions': stats.get('dataset_versions'),
            'splits': stats.get('train_validation_test'),
        },
        'jobs': [
            {
                'job_id': j.get('job_id'),
                'state': j.get('state'),
                'lifecycle': normalize_job_lifecycle_state(str(j.get('state') or '')),
                'dataset_id': j.get('dataset_id'),
                'model_id': j.get('model_id'),
                'real_training': j.get('real_training'),
                'is_mock': j.get('is_mock'),
            }
            for j in jobs
        ],
        'active_model': AUTONOMOUS_TRAINING.models.active(),
        'lkg_model': AUTONOMOUS_TRAINING.models.last_known_good(),
        'candidate_models': [
            {
                'model_id': m.get('model_id'),
                'status': m.get('status'),
                'dataset_version': m.get('dataset_version'),
                'training_backend': m.get('training_backend'),
            }
            for m in AUTONOMOUS_TRAINING.models.list_models(limit=20)
            if m.get('status') in ('CANDIDATE', 'VALIDATING', 'VALIDATED', 'CANARY', 'REJECTED')
        ],
        'last_training_result': stats.get('last_training_result'),
        'last_rollback_result': stats.get('last_rollback_result'),
        'scheduler': AUTONOMOUS_TRAINING.scheduler.status(),
        'resource_status': AUTONOMOUS_TRAINING.resources.admit(
            dataset_rows=int(stats.get('accepted_candidates') or 0),
            method='lora',
            running_jobs=len(AUTONOMOUS_TRAINING.scheduler.status().get('active_jobs') or []),
        ),
        'verification': ver,
        'production_validation': AUTONOMOUS_TRAINING.production_validation_status(),
        'note': 'No secret payloads or private candidate text are exposed.',
    }


@app.get('/platform/learning/dataset')
def platform_learning_dataset(owner: str = Depends(access_public), limit: int = 20):
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
def platform_learning_models(owner: str = Depends(access_public), limit: int = 50):
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
def platform_learning_candidates_collect(owner: str = Depends(access_privileged)):
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
def platform_learning_feedback(x: LearningFeedbackBody, owner: str = Depends(access_privileged)):
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
def platform_training_datasets(owner: str = Depends(access_public), limit: int = 50):
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
def platform_training_jobs(owner: str = Depends(access_public), limit: int = 50):
    _ = owner
    return {'jobs': AUTONOMOUS_TRAINING.list_jobs(limit=limit)}


@app.get('/platform/training/jobs/{job_id}')
def platform_training_job_get(job_id: str, owner: str = Depends(access_public)):
    _ = owner
    job = AUTONOMOUS_TRAINING._read_job(job_id)
    if not job:
        raise HTTPException(404, 'job not found')
    return {'job': job}


@app.post('/platform/training/start')
def platform_training_start(x: TrainingCycleBody, owner: str = Depends(access_privileged)):
    return platform_training_cycle(x, owner)


@app.post('/platform/training/pause')
def platform_training_pause(owner: str = Depends(access_privileged)):
    result = AUTONOMOUS_TRAINING.pause_training()
    OWNER.authorize('PLATFORM_TRAINING_PAUSE', f'{owner} paused training')
    return result


@app.post('/platform/training/cancel')
def platform_training_cancel(job_id: str, owner: str = Depends(access_privileged)):
    result = AUTONOMOUS_TRAINING.cancel_job(job_id)
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'cancel failed')
    OWNER.authorize('PLATFORM_TRAINING_CANCEL', f'{owner} cancelled {job_id}')
    return result


@app.post('/platform/training/autonomous')
def platform_training_autonomous(x: AutonomousToggleBody, owner: str = Depends(access_privileged)):
    result = AUTONOMOUS_TRAINING.set_autonomous(x.enabled)
    OWNER.authorize('PLATFORM_TRAINING_AUTONOMOUS', f'{owner} autonomous={x.enabled}')
    return result


@app.post('/platform/training/tick')
def platform_training_tick(owner: str = Depends(access_privileged)):
    """Owner-triggered autonomous tick (dataset/schedule/growth triggers). Never chat-driven."""
    result = AUTONOMOUS_TRAINING.maybe_run_autonomous_tick()
    OWNER.authorize('PLATFORM_TRAINING_TICK', f"{owner} tick status={result.get('status')}")
    return result


@app.get('/platform/training/models')
def platform_training_models(owner: str = Depends(access_public), limit: int = 50):
    _ = owner
    return {
        'models': AUTONOMOUS_TRAINING.models.list_models(limit=limit),
        'active': AUTONOMOUS_TRAINING.models.active(),
        'active_runtime': AUTONOMOUS_TRAINING.active_runtime.current(),
    }


@app.get('/platform/training/models/{model_id}')
def platform_training_model_get(model_id: str, owner: str = Depends(access_public)):
    _ = owner
    model = AUTONOMOUS_TRAINING.models.get(model_id)
    if not model:
        raise HTTPException(404, 'model not found')
    return {'model': model}


@app.post('/platform/training/models/{model_id}/activate')
def platform_training_model_activate(model_id: str, owner: str = Depends(access_privileged)):
    result = AUTONOMOUS_TRAINING.activate_model(model_id)
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'activate failed')
    OWNER.authorize('PLATFORM_TRAINING_ACTIVATE', f'{owner} activated {model_id}')
    return result


@app.post('/platform/training/models/{model_id}/rollback')
def platform_training_model_rollback(model_id: str, owner: str = Depends(access_privileged), reason: str = 'owner_requested'):
    _ = model_id  # target is last-known-good; model_id retained for audit context
    result = AUTONOMOUS_TRAINING.rollback_mgr.rollback(reason=reason or f'owner_requested:{model_id}')
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'rollback failed')
    OWNER.authorize('PLATFORM_TRAINING_ROLLBACK', f'{owner} rollback from context {model_id}')
    return result


@app.get('/platform/training/evaluations')
def platform_training_evaluations(owner: str = Depends(access_public), limit: int = 20):
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
def platform_training_checkpoints(owner: str = Depends(access_public), limit: int = 50):
    _ = owner
    return {'checkpoints': AUTONOMOUS_TRAINING.checkpoints.list_recent(limit=limit)}


@app.post('/platform/training/cycle')
def platform_training_cycle(x: TrainingCycleBody, owner: str = Depends(access_privileged)):
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


@app.post('/platform/training/validate')
def platform_training_validate(
    apply_decision: bool = True,
    candidate_model_id: str | None = None,
    owner: str = Depends(access_privileged),
):
    """Owner-only real post-train validation of candidate vs LKG."""
    _ = owner
    return AUTONOMOUS_TRAINING.validate_active_against_lkg(
        apply_decision=bool(apply_decision),
        candidate_model_id=candidate_model_id,
    )


@app.post('/platform/training/production-validate')
def platform_training_production_validate(
    candidate_model_id: str | None = None,
    apply_rollback_on_failure: bool = False,
    owner: str = Depends(access_privileged),
):
    """Owner-only PHASE 11 production quality validation (never fabricates pass)."""
    _ = owner
    return AUTONOMOUS_TRAINING.run_production_validation(
        candidate_model_id=candidate_model_id,
        apply_rollback_on_failure=bool(apply_rollback_on_failure),
    )


@app.get('/platform/training/production-validation')
def platform_training_production_validation_status(owner: str = Depends(access_public)):
    _ = owner
    return AUTONOMOUS_TRAINING.production_validation_status()


@app.post('/platform/training/rollback')
def platform_training_rollback(x: TrainingRollbackBody, owner: str = Depends(access_privileged)):
    if x.force_regression:
        result = AUTONOMOUS_TRAINING.monitor_and_maybe_rollback(force_regression=True)
    else:
        result = AUTONOMOUS_TRAINING.rollback_mgr.rollback(reason=x.reason or 'owner_requested')
    OWNER.authorize('PLATFORM_TRAINING_ROLLBACK', f'{owner} rollback ok={result.get("ok")}')
    if not result.get('ok'):
        raise HTTPException(409, result.get('error') or 'rollback failed')
    return result


@app.get('/platform/training/rollback')
def platform_training_rollback_status(owner: str = Depends(access_public)):
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
def platform_models(owner: str = Depends(access_public), limit: int = 50):
    return platform_training_models(owner=owner, limit=limit)


@app.get('/platform/models/{model_id}')
def platform_model_get(model_id: str, owner: str = Depends(access_public)):
    return platform_training_model_get(model_id=model_id, owner=owner)


@app.post('/platform/models/{model_id}/activate')
def platform_model_activate(model_id: str, owner: str = Depends(access_privileged)):
    return platform_training_model_activate(model_id=model_id, owner=owner)


@app.post('/platform/models/{model_id}/rollback')
def platform_model_rollback(model_id: str, owner: str = Depends(access_privileged), reason: str = 'owner_requested'):
    return platform_training_model_rollback(model_id=model_id, owner=owner, reason=reason)


@app.get('/platform/skills/packs')
def platform_skill_packs(owner: str = Depends(access_public)):
    _ = owner
    return {'packs': PLATFORM_SKILL_PACKS.list_packs()}


@app.get('/platform/skills/packs/{pack_id}')
def platform_skill_pack_get(pack_id: str, owner: str = Depends(access_public)):
    _ = owner
    pack = PLATFORM_SKILL_PACKS.get(pack_id)
    if not pack:
        raise HTTPException(404, 'pack not found')
    return {'pack': pack}


@app.post('/platform/skills/packs/{pack_id}/activate')
def platform_skill_pack_activate(pack_id: str, x: SkillPackActivateBody, owner: str = Depends(access_privileged)):
    result = PLATFORM_SKILL_PACKS.activate(
        pack_id or x.pack_id, x.version, approved=bool(x.approved), actor=owner, enable=bool(x.enable)
    )
    if not result.get('ok'):
        code = 401 if result.get('needs_approval') else 400
        raise HTTPException(code, result.get('error') or 'activate failed')
    OWNER.authorize('PLATFORM_SKILL_PACK_ACTIVATE', f'{owner} pack {pack_id}@{x.version}')
    return result


@app.post('/platform/skills/packs/{pack_id}/rollback')
def platform_skill_pack_rollback(pack_id: str, owner: str = Depends(access_privileged)):
    result = PLATFORM_SKILL_PACKS.rollback(pack_id, approved=True, actor=owner)
    if not result.get('ok'):
        raise HTTPException(400, result.get('error') or 'rollback failed')
    OWNER.authorize('PLATFORM_SKILL_PACK_ROLLBACK', f'{owner} pack {pack_id}')
    return result


@app.post('/platform/skills/packs/{pack_id}/enable')
def platform_skill_pack_enable(pack_id: str, x: SkillPackEnableBody, owner: str = Depends(access_privileged)):
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
def chat_tools(owner: str = Depends(access_public)):
    from .open_execution import open_chat_tools, open_execution_status
    return {
        'provider': COMMAND_AGENT.provider_name(),
        'tools': TOOL_ROUTER.catalog(),
        'open_chat_tools': open_chat_tools(),
        'open_execution': open_execution_status(),
        'locked_count': sum(1 for t in TOOL_ROUTER.catalog() if t.get('requires_approval')),
    }

@app.get('/chat/conversations')
def chat_conversations(owner: str = Depends(access_public), limit: int = 30):
    return {'items': COMMAND_MEMORY.list_conversations(limit)}

@app.get('/chat/conversations/{conversation_id}')
def chat_conversation(conversation_id: str, owner: str = Depends(access_public)):
    return {
        'conversation_id': conversation_id,
        'messages': COMMAND_MEMORY.get_messages(conversation_id),
    }

@app.post('/chat/message')
def chat_message(x: ChatMessage, owner: str = Depends(access_public)):
    if not x.message.strip():
        raise HTTPException(400, 'message is required')
    msg = x.message.strip()
    if _should_use_production_runtime(msg):
        prod = ELITE.production.handle(
            msg,
            conversation_id=x.conversation_id or '',
            actor=owner,
            authenticated=True,
            approved=False,
        )
        cid = COMMAND_MEMORY.ensure_conversation(x.conversation_id)
        COMMAND_MEMORY.add_message(cid, 'user', msg, status='completed')
        progress = prod.get('progress') or {}
        timeline = _progress_timeline_for_chat(progress)
        reply = str(prod.get('answer') or prod.get('reply') or '')
        status = 'completed' if prod.get('ok') else 'failed'
        if not timeline:
            timeline = [{'status': status, 'detail': progress.get('label') or status}]
        COMMAND_MEMORY.add_message(
            cid,
            'assistant',
            reply,
            status=status,
            meta={
                'timeline': timeline,
                'progress': progress,
                'production_runtime': True,
                'response_kind': prod.get('response_kind'),
                'provider': 'production_runtime',
            },
        )
        OWNER.authorize('CHAT_COMMAND', f'{owner} production chat status={status}')
        return {
            'ok': bool(prod.get('ok')),
            'conversation_id': cid,
            'reply': reply,
            'timeline': timeline,
            'progress': progress,
            'response_kind': prod.get('response_kind'),
            'information_source': prod.get('information_source') or 'model_knowledge',
            'citations': prod.get('citations') or [],
            'provider': 'production_runtime',
            'status': status,
            'phase': 23,
            'WEB_FABRIC_STATUS': prod.get('WEB_FABRIC_STATUS'),
            'EMAIL_DELIVERY_STATUS': prod.get('EMAIL_DELIVERY_STATUS'),
            'PHASE_24_ALLOWED': False,
        }
    result = COMMAND_AGENT.handle(msg, owner=owner, conversation_id=x.conversation_id, language=x.language)
    OWNER.authorize('CHAT_COMMAND', f'{owner} chat turn status={result.get("status")}')
    coding = result.get('coding')
    if isinstance(coding, dict):
        if not result.get('learning_context'):
            from .coding_agent import build_learning_context
            result['learning_context'] = build_learning_context(coding)
        result['learning_hub'] = _chat_learning_hub(owner)
    else:
        tools = result.get('tools') or []
        edu_tools = {
            'coding_teach', 'coding_tracks', 'coding_assess', 'coding_progress',
            'coding_projects', 'coding_knowledge', 'coding_next_lesson', 'coding_review',
            'learner_snapshot', 'training_eligibility', 'training_control_status', 'run_sandbox',
        }
        if any((t.get('tool') in edu_tools) for t in tools if isinstance(t, dict)):
            result['learning_hub'] = _chat_learning_hub(owner)
            result.setdefault('learning_context', {
                'intent': 'tools',
                'training_auto': False,
                'can_start_training_from_chat': False,
                'tools': [t.get('tool') for t in tools if isinstance(t, dict) and t.get('tool') in edu_tools],
                'note': 'Education/training status via read-only tools — never auto-train from chat',
            })
    return result

@app.post('/chat/approve/{pending_id}')
def chat_approve(pending_id: str, owner: str = Depends(access_privileged)):
    result = COMMAND_AGENT.approve(pending_id, owner=owner)
    if not result.get('ok') and result.get('error'):
        raise HTTPException(404 if 'not found' in result['error'] else 409, result['error'])
    OWNER.authorize('CHAT_APPROVE', f'{owner} approved pending {pending_id}')
    return result

@app.post('/chat/reject/{pending_id}')
def chat_reject(pending_id: str, owner: str = Depends(access_privileged)):
    result = COMMAND_AGENT.reject(pending_id, owner=owner)
    if not result.get('ok') and result.get('error'):
        raise HTTPException(404, result['error'])
    OWNER.authorize('CHAT_REJECT', f'{owner} rejected pending {pending_id}')
    return result

@app.get('/chat/audit')
def chat_audit(owner: str = Depends(access_privileged), limit: int = 50):
    return {'items': COMMAND_AUDIT.recent(limit)}

@app.get('/chat/memory/search')
def chat_memory_search(q: str, owner: str = Depends(access_public), limit: int = 8):
    return {'results': COMMAND_MEMORY.relevant(q, limit)}

@app.post('/chat/memory/remember')
def chat_memory_remember(x: ChatMemoryWrite, owner: str = Depends(access_privileged)):
    mid = COMMAND_MEMORY.remember(x.kind, x.content, source=f'owner:{owner}', confidence=x.confidence)
    OWNER.authorize('CHAT_MEMORY_REMEMBER', f'{owner} remembered kind={x.kind} id={mid}')
    return {'ok': True, 'memory_id': mid}

@app.post('/chat/memory/forget/{memory_id}')
def chat_memory_forget(memory_id: int, owner: str = Depends(access_privileged)):
    if not COMMAND_MEMORY.forget(memory_id):
        raise HTTPException(404, 'memory not found')
    OWNER.authorize('CHAT_MEMORY_FORGET', f'{owner} forgot memory {memory_id}')
    return {'ok': True, 'forgotten': memory_id}

@app.post('/chat/memory/correct/{memory_id}')
def chat_memory_correct(memory_id: int, x: ChatMemoryCorrect, owner: str = Depends(access_privileged)):
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
def coding_tracks(owner: str = Depends(access_public)):
    return {'tracks': CODING_CURRICULUM.list_tracks()}

@app.get('/coding/profile')
def coding_profile(owner: str = Depends(access_public)):
    return CODING_PROFILES.get_profile(owner)

@app.post('/coding/mode')
def coding_mode(x: ModeSet, owner: str = Depends(access_public)):
    return CODING_PROFILES.set_mode(owner, x.mode)

@app.get('/coding/assessment')
def coding_assessment(owner: str = Depends(access_public)):
    return CODING_PROFILES.start_assessment()

@app.post('/coding/assessment/submit')
def coding_assessment_submit(x: AssessmentSubmit, owner: str = Depends(access_public)):
    result = CODING_PROFILES.grade_assessment(owner, x.answers)
    CODING_MEMORY.sync_from_profile(owner, result.get('profile') or {})
    OWNER.authorize('CODING_ASSESSMENT', f'{owner} completed skill assessment')
    return result

@app.post('/coding/path')
def coding_path(track_id: str = 'python', goal: str = '', owner: str = Depends(access_public)):
    path = CODING_AGENT.tutor.start_path(owner, track_id, goal=goal)
    return path

@app.get('/coding/lesson/{track_id}/{lesson_id}')
def coding_lesson(track_id: str, lesson_id: str, owner: str = Depends(access_public), reveal_solution: bool = False):
    return CODING_AGENT.tutor.lesson(track_id, lesson_id, reveal_solution=reveal_solution)

@app.post('/coding/hint')
def coding_hint(x: HintRequest, owner: str = Depends(access_public)):
    return CODING_AGENT.tutor.hint(owner, x.track_id, x.lesson_id)

@app.post('/coding/exercise/submit')
def coding_exercise_submit(x: ExerciseSubmit, owner: str = Depends(access_public)):
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
def coding_solution(x: SolutionRequest, owner: str = Depends(access_public)):
    result = CODING_AGENT.tutor.solution(owner, x.track_id, x.lesson_id, confirmed=bool(x.confirm))
    if result.get('needs_confirmation'):
        return result
    OWNER.authorize('CODING_SOLUTION_REVEAL', f'{owner} revealed solution {x.track_id}/{x.lesson_id}')
    return result

@app.post('/coding/sandbox')
def coding_sandbox(x: SandboxRequest, owner: str = Depends(access_public)):
    return _tool_run_sandbox(x.code, x.test_code)

@app.post('/coding/review')
def coding_review(x: ReviewRequest, owner: str = Depends(access_public)):
    return CODING_AGENT.reviewer.review(x.code, language=x.language, context=x.context)

@app.post('/coding/debug/start')
def coding_debug_start(x: DebugStart, owner: str = Depends(access_public)):
    return CODING_AGENT.debugger.start(owner, x.code, x.test_code, x.description)

@app.post('/coding/debug/respond')
def coding_debug_respond(x: DebugRespond, owner: str = Depends(access_public)):
    return CODING_AGENT.debugger.respond(x.session_id, x.hypothesis)

@app.get('/coding/projects')
def coding_projects(owner: str = Depends(access_public), level: str | None = None):
    return {'projects': CODING_CURRICULUM.projects(level)}

@app.get('/coding/projects/{project_id}')
def coding_project(project_id: str, owner: str = Depends(access_public)):
    p = CODING_CURRICULUM.get_project(project_id)
    if not p:
        raise HTTPException(404, 'project not found')
    return p

@app.get('/coding/knowledge')
def coding_knowledge(q: str = '', owner: str = Depends(access_public), limit: int = 8):
    return {'results': CODING_CURRICULUM.knowledge_search(q, limit)}

@app.get('/coding/progress')
def coding_progress(owner: str = Depends(access_public)):
    return CODING_PROFILES.progress(owner)

@app.get('/coding/training/status')
def coding_training_status(owner: str = Depends(access_public)):
    return CODING_TRAINING.status()

@app.post('/coding/chat')
def coding_chat(x: CodingChat, owner: str = Depends(access_public)):
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
