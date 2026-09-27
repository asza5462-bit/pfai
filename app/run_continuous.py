"""24/7 production entrypoint for PFAI's continuous learning subsystem.

Run as: `python run_continuous.py`. Two supported ways to keep it alive:
  - `docker compose --profile continuous up -d` (recommended; see the
    `pfai-continuous` service in docker-compose.yml -- deploy.sh offers to set
    this up for you), or
  - deploy/pfai-continuous.service, a systemd unit for a non-Docker host.

Either way, this checks configs/default.json's `continuous_training.enabled`
before doing anything: if it is not `true`, the process logs that and exits
immediately (exit code 0) rather than looping forever doing nothing -- an
operator must explicitly opt in.

What this does, every `interval_seconds` (config: continuous_training.interval_seconds):
  1. Looks at whatever training examples have already been curated into
     data/continuous_learning/curated_examples.jsonl (via
     ContinuousLearningOrchestrator.register_batch — an operator or another
     pipeline component supplies these; this process never fetches data
     itself, over the network or otherwise).
  2. If a real model is configured (model.provider == "anthropic" and
     ANTHROPIC_API_KEY is set), asks that model to score the curated batch
     (pfai/llm_evaluator.py) and proposes a new training candidate.
  3. Fails closed and simply idles the cycle when there is nothing curated,
     or when no model/API key is configured — exactly like every previous
     version of this file.

What this deliberately never does, no matter what:
  - Promote a candidate to "active". That still requires an explicit human
    `orchestrator.approve(version)` call (require_human_approval stays True) —
    see tests/test_v70_continuous_learning_orchestrator.py::test_model_cannot_bypass_approval_gate.
  - Fetch its own training data from the internet.
  - Widen its own tool/security permissions.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from pfai.config import Config
from pfai.model_anthropic import AnthropicProvider
from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator
from pfai.continuous_training import ContinuousConfig
from pfai.code_learning_pipeline import CodeLearningPipeline
from pfai.code_execution_evaluator import SandboxedCodeEvaluator
from pfai.continuous_gate import is_continuous_enabled, continuous_gate_status, ENV_NAME
from pfai.logging_setup import setup_logging

log = setup_logging("pfai.continuous")


def build_model(model_cfg: dict):
    """Same provider-selection rule as pfai/app.py: only a real, explicitly
    configured provider ever acts as the evaluator. Anything else (including a
    missing API key) leaves the evaluator unset, so cycles keep failing closed
    exactly as before."""
    provider = model_cfg.get('provider', 'echo')
    if provider == 'anthropic' and os.environ.get(model_cfg.get('api_key_env', 'ANTHROPIC_API_KEY')):
        return AnthropicProvider(
            model_cfg.get('model', 'claude-opus-5'),
            model_cfg.get('base_url', 'https://api.anthropic.com/v1'),
            int(model_cfg.get('max_tokens', 2048)),
            model_cfg.get('api_key_env', 'ANTHROPIC_API_KEY'),
        )
    return None  # no evaluator configured -> orchestrator.run_cycle fails closed


def is_enabled(config_path='configs/default.json') -> bool:
    """Continuous loop gate: config `continuous_training.enabled` plus optional
    force override via ``PFAI_CONTINUOUS_TRAINING_ENABLED``.

    Even when enabled, this process never auto-promotes candidates to active.
    """
    return is_continuous_enabled(config_path)


def build_orchestrator(config_path='configs/default.json') -> ContinuousLearningOrchestrator:
    cfg = Config.load(config_path)
    ct_cfg = cfg.get('continuous_training', {})
    evaluator_model = build_model(cfg.get('model', {}))
    return ContinuousLearningOrchestrator(
        root='data/continuous_learning',
        min_quality=float(ct_cfg.get('acquisition', {}).get('min_quality', 0.40)),
        self_training=bool(ct_cfg.get('self_training', {}).get('enabled', True)),
        self_training_batch_size=int(ct_cfg.get('self_training', {}).get('examples_per_track_per_cycle', 2)),
        self_training_min_score=float(ct_cfg.get('self_training', {}).get('min_teacher_score', 0.80)),
        continuous_config=ContinuousConfig(
            interval_seconds=int(ct_cfg.get('interval_seconds', 3600)),
            max_consecutive_failures=int(ct_cfg.get('max_consecutive_failures', 3)),
            checkpoint_every_cycle=bool(ct_cfg.get('checkpoint_every_cycle', True)),
            auto_promote=False,  # not configurable from JSON on purpose: promotion is always human-gated
            require_evaluation=bool(ct_cfg.get('require_evaluation', True)),
            heartbeat_seconds=int(ct_cfg.get('heartbeat_seconds', 30)),
        ),
        require_human_approval=True,  # never configurable from JSON: this is the safety boundary
        evaluator_model=evaluator_model,
        max_curated_examples=int(ct_cfg.get('max_curated_examples', 10000)),
    )


def make_cycle(orchestrator: ContinuousLearningOrchestrator, config_path='configs/default.json'):
    cfg = Config.load(config_path).get('continuous_training', {})
    wt = cfg.get('self_training', {}).get('weight_training', {})
    cc = cfg.get('code_learning', {})
    code_model = build_model(Config.load(config_path).get('model', {}))
    code_pipeline = (CodeLearningPipeline(
        code_model, orchestrator, evaluator=SandboxedCodeEvaluator(),
        n=int(cc.get('candidates', 5)), max_repairs=int(cc.get('max_repairs', 4)),
        adversarial_rounds=int(cc.get('adversarial_rounds', 2)),
        auto_repair=bool(cc.get('auto_repair', True))) if code_model and cc.get('enabled', True) else None)
    every = max(1, int(wt.get('every_n_cycles', 5)))
    model_env = wt.get('model_id_env', 'PFAI_LOCAL_MODEL_ID')
    def cycle() -> dict:
        version = 'auto-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        result = orchestrator.run_cycle(version=version)
        if code_pipeline is not None:
            code_results = []
            for _ in range(max(1, int(cc.get('tasks_per_cycle', 2)))):
                code_results.append(code_pipeline.generate_and_learn_task(source='autonomous_code_curriculum'))
            result['code_learning'] = {
                'tasks': len(code_results),
                'solved': sum(1 for x in code_results if x.get('solved')),
                'curated': sum(1 for x in code_results if x.get('curated')),
                'results': code_results,
            }
        cycle_no = orchestrator.service.status().get('cycles', 0)
        if result.get('evaluated') and wt.get('enabled', True) and cycle_no % every == 0 and orchestrator.self_training is not None:
            model_id = os.environ.get(model_env, '')
            train_result = orchestrator.self_training.train_weights(
                model_id=model_id, run_id=version,
                require_gpu=bool(wt.get('require_gpu', False))) if model_id else {
                    'status': 'blocked', 'reason': f'{model_env} is not set; no local model was selected'}
            result['weight_training'] = train_result
        return result
    return cycle


if __name__ == "__main__":
    gate = continuous_gate_status()
    log.info("continuous_gate %s", gate)
    if not is_enabled():
        log.warning(
            "continuous training disabled (config enabled=%s, %s override=%s) — exiting",
            gate.get("config_enabled"),
            ENV_NAME,
            gate.get("env_override"),
        )
        raise SystemExit(0)
    orchestrator = build_orchestrator()
    cycle = make_cycle(orchestrator)

    def logged_cycle() -> dict:
        result = cycle()
        log.info(
            "training_cycle version=%s evaluated=%s auto_scored=%s weight_training=%s",
            result.get("version"),
            result.get("evaluated"),
            result.get("auto_scored"),
            (result.get("weight_training") or {}).get("status"),
        )
        return result

    # If no real teacher/model credentials are configured, stay alive in a
    # heartbeat-only idle state instead of entering a failure/restart loop.
    # This keeps 24/7 service supervision stable while making the missing
    # dependency explicit in status/events. As soon as a model is configured,
    # restart the service to activate real learning cycles.
    model_ready = build_model(Config.load().get('model', {})) is not None
    if not model_ready:
        log.warning("no teacher model/API credentials configured — idle heartbeat mode")
        orchestrator.service.start()
        orchestrator.service._state['last_error'] = 'idle: no teacher model/API credentials configured'
        orchestrator.service._save()
        while orchestrator.service.status().get('status') == 'running':
            orchestrator.service.heartbeat()
            import time
            time.sleep(max(1, int(orchestrator.service.config.interval_seconds)))
    else:
        log.info("starting continuous learning loop (auto_promote=false, human approval required)")
        orchestrator.service.serve_forever(logged_cycle)
