/* PFAI Command Chat — Advanced Brain UI linked to Academy + REAL Training (write-path) */
(function () {
  let conversationId = localStorage.getItem('pfai_chat_conversation') || null;
  let busy = false;
  let lastExercise = null; // {track_id, lesson_id, starter}

  const STATUS_LABEL = {
    thinking: { ar: 'فهم الطلب', en: 'Understanding' },
    planning: { ar: 'تخطيط', en: 'Planning' },
    calling_tool: { ar: 'اختيار القدرات', en: 'Selecting capabilities' },
    executing: { ar: 'تنفيذ', en: 'Executing' },
    teaching: { ar: 'تعليم', en: 'Teaching' },
    reviewing: { ar: 'مراجعة', en: 'Reviewing' },
    waiting_for_approval: { ar: 'بانتظار الموافقة', en: 'Waiting for approval' },
    completed: { ar: 'اكتمل', en: 'Completed' },
    failed: { ar: 'فشل', en: 'Failed' },
    rejected: { ar: 'مرفوض', en: 'Rejected' },
  };

  const PROGRESS_LABEL = {
    Understanding: { ar: 'فهم الطلب', en: 'Understanding' },
    Planning: { ar: 'تخطيط', en: 'Planning' },
    'Selecting capabilities': { ar: 'اختيار القدرات', en: 'Selecting capabilities' },
    Executing: { ar: 'تنفيذ', en: 'Executing' },
    Testing: { ar: 'اختبار', en: 'Testing' },
    Validating: { ar: 'تحقق', en: 'Validating' },
    Completed: { ar: 'اكتمل', en: 'Completed' },
    Failed: { ar: 'فشل', en: 'Failed' },
  };

  function langOf(text) {
    return /[\u0600-\u06FF]/.test(text || '') ? 'ar' : 'en';
  }

  function statusChip(status, lang) {
    const L = STATUS_LABEL[status] || { ar: status, en: status };
    const label = lang === 'en' ? L.en : L.ar;
    return `<span class="chat-status ${esc(status)}">${esc(label)}</span>`;
  }

  function renderTimeline(timeline, lang) {
    if (!timeline || !timeline.length) return '';
    // Collapse internals — show final status chip; full trace only on expand
    const last = timeline[timeline.length - 1] || {};
    const summary = statusChip(last.status || 'completed', lang);
    const steps = timeline.map(s =>
      `<div class="chat-step">${statusChip(s.status, lang)} <span>${esc(s.detail || s.tool || '')}</span></div>`
    ).join('');
    return `<details class="chat-timeline-wrap">
      <summary class="chat-timeline-summary muted">${summary} <span>${lang === 'en' ? 'trace' : 'التتبع'}</span></summary>
      <div class="chat-timeline">${steps}</div>
    </details>`;
  }

  function providerLabel(provider) {
    if (!provider) return '';
    if (provider === 'pfai-brain' || provider === 'mock-command') {
      return 'PFAI Brain';
    }
    if (String(provider).startsWith('anthropic:')) return provider;
    return provider;
  }

  function renderProgress(progress, lang) {
    if (!progress || !progress.timeline) return '';
    const pct = Number(progress.progress_percent || 0);
    const cur = progress.label || '';
    const L = PROGRESS_LABEL[cur] || { ar: cur, en: cur };
    const label = lang === 'en' ? L.en : L.ar;
    const steps = (progress.timeline || []).map(s => {
      const pl = PROGRESS_LABEL[s.label] || { ar: s.label, en: s.label };
      const name = lang === 'en' ? pl.en : pl.ar;
      return `<span class="chat-progress-step${s.reached ? ' reached' : ''}">${esc(name)}</span>`;
    }).join('');
    return `<div class="chat-progress" aria-label="execution progress">
      <div class="chat-progress-bar"><i style="width:${Math.max(0, Math.min(100, pct))}%"></i></div>
      <div class="chat-progress-label">${esc(label)} · ${pct}%</div>
      <div class="chat-progress-steps">${steps}</div>
    </div>`;
  }

  function renderLearningContext(ctx, lang) {
    if (!ctx) return '';
    // Only show academy strip for real coding/teaching turns — not ops/training spam
    const codingish = ['teach', 'coding', 'academy', 'exercise', 'review', 'assess'].includes(
      String(ctx.intent || ctx.mode || '').toLowerCase()
    ) || ctx.track_id || ctx.lesson_id || ctx.lesson_title;
    if (!codingish) return '';
    const bits = [];
    if (ctx.mode) bits.push(`${lang === 'en' ? 'mode' : 'وضع'}: ${ctx.mode}`);
    if (ctx.track_id) bits.push(`track: ${ctx.track_id}`);
    if (ctx.lesson_title || ctx.lesson_id) bits.push(`${ctx.lesson_title || ctx.lesson_id}`);
    if (!bits.length) return '';
    return `<div class="chat-learn-strip">${bits.map(b => `<span class="chat-chip">${esc(String(b))}</span>`).join('')}</div>`;
  }

  function renderTrainingChips(tools, lang) {
    if (!tools || !tools.length) return '';
    const chips = [];
    let eligShown = false;
    tools.forEach(t => {
      if (!t || !t.ok) return;
      const name = t.tool || '';
      const res = t.result || {};
      if (!eligShown && (name === 'training_eligibility' || name === 'smart_training_status' || (res.eligibility && 'eligible' in res))) {
        const elig = res.eligible;
        const reason = (res.eligibility && (res.eligibility.reason || (res.eligibility.reasons || [])[0])) || res.reason || '';
        chips.push(`<span class="chat-chip ${elig ? 'ok' : 'warn'}">${lang === 'en' ? 'Eligible' : 'الأهلية'}: ${elig ? 'YES' : 'NO'}${reason ? ' · ' + esc(String(reason).slice(0, 60)) : ''}</span>`);
        eligShown = true;
      }
      if (name === 'training_cycle_start' || name === 'smart_training_start' || name === 'unified_train_learn_cycle') {
        const train = res.train || res.cycle || res;
        const ex = !!(res.actual_training_executed || train.actual_training_executed);
        const st = train.status || res.status || '';
        const trig = train.triggered;
        chips.push(`<span class="chat-chip ${ex || trig ? 'ok' : 'warn'}">${lang === 'en' ? 'REAL train' : 'تدريب حقيقي'}: ${ex ? 'EXECUTED' : esc(String(st || (trig ? 'STARTED' : 'idle')).slice(0, 48))}</span>`);
      }
      if (name === 'unified_train_learn_status') {
        const hb = res.heartbeat_alive;
        chips.push(`<span class="chat-chip ${hb ? 'ok' : 'warn'}">${lang === 'en' ? 'Unified 24/7' : 'موحّد 24/7'}: ${hb ? 'ON' : 'off'}</span>`);
      }
      if (name === 'live_monitor_pulse' || name === 'live_monitor_status') {
        const alive = res.alive !== undefined ? res.alive : res.continuous_alive;
        chips.push(`<span class="chat-chip ok">${lang === 'en' ? 'Live monitor' : 'مراقب حي'}: ${alive === false ? 'DOWN' : '24/7'}</span>`);
      }
      if (name === 'continuous_start' || name === 'continuous_status' || name === 'continuous_tick') {
        const wa = res.worker_alive;
        if (wa !== undefined) {
          chips.push(`<span class="chat-chip ${wa ? 'ok' : 'warn'}">${lang === 'en' ? 'Continuous' : 'مستمر'}: ${wa ? 'ALIVE' : 'DOWN'}</span>`);
        }
      }
      if (name === 'training_control_status') {
        chips.push(`<span class="chat-chip">control: ${esc(String(res.paused === true ? 'paused' : (res.autonomous_enabled ? 'autonomous' : 'manual')))}</span>`);
      }
      if (name === 'learner_snapshot' && res.profile) {
        chips.push(`<span class="chat-chip ok">${lang === 'en' ? 'Level' : 'مستوى'}: ${esc(res.profile.display_level || '—')}</span>`);
        if ((res.profile.weak_skills || []).length) {
          chips.push(`<span class="chat-chip warn">${lang === 'en' ? 'Weak' : 'ضعيف'}: ${esc((res.profile.weak_skills || []).slice(0, 3).join(', '))}</span>`);
        }
      }
    });
    if (!chips.length) return '';
    return `<div class="chat-learn-strip">${chips.join('')}</div>`;
  }

  function renderCodingCard(coding, lang) {
    if (!coding) return '';
    const parts = [];
    const intent = coding.intent || '';
    const path = coding.path || {};
    const lessonWrap = coding.lesson || {};
    const lesson = lessonWrap.lesson || {};
    const exercise = lessonWrap.exercise || {};
    const trackId = coding.track_id || path.track_id || lesson.track_id || 'python';
    const lessonId = lesson.id;

    if (intent === 'teach' && path && path.path) {
      const items = (path.path || []).slice(0, 6).map(p =>
        `<li><strong>${esc(p.title || p.id)}</strong> <span class="muted">${esc(p.level || '')}</span></li>`
      ).join('');
      parts.push(`<div class="chat-coding-card">
        <div class="chat-coding-head">${lang === 'en' ? 'Learning path' : 'مسار تعليمي'} · ${esc(path.track_id || trackId)} · ${esc(path.recommended_level || '')}</div>
        <ul class="chat-path-list">${items}</ul>
        <div class="chat-actions">
          <button class="btn" data-chat-quick-set="أعطني تمرينًا في ${esc(path.track_id || trackId)}">${lang === 'en' ? 'Next exercise' : 'التمرين التالي'}</button>
          <button class="btn" data-goto-academy="1">${lang === 'en' ? 'Open Academy' : 'فتح الأكاديمية'}</button>
        </div>
      </div>`);
    }

    if ((intent === 'exercise' || exercise.prompt) && lessonId) {
      lastExercise = {
        track_id: trackId,
        lesson_id: lessonId,
        starter: exercise.starter || '',
      };
      const starter = exercise.starter || '# write your solution\n';
      parts.push(`<div class="chat-coding-card" data-ex-track="${esc(trackId)}" data-ex-lesson="${esc(lessonId)}">
        <div class="chat-coding-head">${lang === 'en' ? 'Exercise' : 'تمرين'}: ${esc(lesson.title || lessonId)}</div>
        <div class="chat-ex-prompt">${esc(exercise.prompt || '')}</div>
        <textarea class="textarea chat-ex-code" rows="8">${esc(starter)}</textarea>
        <div class="chat-actions">
          <button class="btn primary" data-ex-submit="1">${lang === 'en' ? 'Submit solution' : 'إرسال الحل'}</button>
          <button class="btn" data-ex-hint="1">${lang === 'en' ? 'Hint' : 'تلميح'}</button>
          <button class="btn" data-goto-academy="1">${lang === 'en' ? 'Academy' : 'الأكاديمية'}</button>
        </div>
        <div class="chat-ex-result muted" hidden></div>
      </div>`);
    }

    if (intent === 'assess' && coding.assessment) {
      const n = coding.assessment.count || (coding.assessment.items || []).length;
      parts.push(`<div class="chat-coding-card">
        <div class="chat-coding-head">${lang === 'en' ? 'Skill assessment ready' : 'اختبار المهارات جاهز'} · ${n} ${lang === 'en' ? 'items' : 'أسئلة'}</div>
        <div class="muted">${lang === 'en' ? 'Submit answers via Academy or /coding/assessment/submit' : 'أرسل الإجابات من الأكاديمية أو /coding/assessment/submit'}</div>
        <div class="chat-actions"><button class="btn" data-goto-academy="1">${lang === 'en' ? 'Open Academy' : 'فتح الأكاديمية'}</button></div>
      </div>`);
    }

    if (intent === 'review' && coding.review) {
      const findings = coding.review.findings || [];
      const high = findings.filter(f => f.severity === 'high').length;
      parts.push(`<div class="chat-coding-card">
        <div class="chat-coding-head">${lang === 'en' ? 'Code review' : 'مراجعة كود'} · ${findings.length} notes (${high} high)</div>
        <ul class="chat-path-list">${findings.slice(0, 5).map(f =>
          `<li><strong>${esc(f.category || '')}</strong> ${esc((f.message || f.detail || '').slice(0, 140))}</li>`
        ).join('')}</ul>
      </div>`);
    }

    if (intent === 'project' && coding.projects) {
      parts.push(`<div class="chat-coding-card">
        <div class="chat-coding-head">${lang === 'en' ? 'Projects' : 'مشاريع'}</div>
        <ul class="chat-path-list">${(coding.projects || []).slice(0, 5).map(p =>
          `<li><strong>${esc(p.title || p.id)}</strong> <span class="muted">${esc(p.level || '')}</span></li>`
        ).join('')}</ul>
      </div>`);
    }

    return parts.join('');
  }

  function wireCodingCard(root) {
    if (!root) return;
    root.querySelectorAll('[data-goto-academy]').forEach(btn => {
      btn.onclick = () => {
        const navBtn = document.querySelector('[data-id="academy"]');
        if (typeof show === 'function') show('academy', navBtn);
        if (typeof loadAcademy === 'function') loadAcademy();
      };
    });
    root.querySelectorAll('[data-chat-quick-set]').forEach(btn => {
      btn.onclick = () => {
        const input = $('chatInput');
        if (input) {
          input.value = btn.getAttribute('data-chat-quick-set');
          sendChat();
        }
      };
    });
    root.querySelectorAll('[data-ex-submit]').forEach(btn => {
      btn.onclick = () => submitExerciseFromCard(btn.closest('.chat-coding-card'));
    });
    root.querySelectorAll('[data-ex-hint]').forEach(btn => {
      btn.onclick = () => hintFromCard(btn.closest('.chat-coding-card'));
    });
  }

  async function submitExerciseFromCard(card) {
    if (!card || busy) return;
    const track = card.getAttribute('data-ex-track');
    const lesson = card.getAttribute('data-ex-lesson');
    const codeEl = card.querySelector('.chat-ex-code');
    const out = card.querySelector('.chat-ex-result');
    const code = (codeEl && codeEl.value) || '';
    setBusy(true);
    try {
      const r = await api('/coding/exercise/submit', {
        method: 'POST',
        body: { track_id: track, lesson_id: lesson, code },
      });
      const passed = !!r.passed;
      const cand = r.learning_candidate || {};
      if (out) {
        out.hidden = false;
        out.className = 'chat-ex-result ' + (passed ? 'ok' : 'bad');
        out.textContent = (passed ? '✓ Passed' : '✗ Failed')
          + (r.message ? ' · ' + r.message : '')
          + (r.stderr ? '\n' + r.stderr.slice(0, 300) : '')
          + `\nlearning_candidate: ${cand.eligibility || 'n/a'} · trained=${cand.trained === true}`;
      }
      toast(passed ? 'تم اجتياز التمرين' : 'فشل التمرين', !passed);
      refreshLearningRail();
      if (typeof loadAcademy === 'function') loadAcademy();
    } catch (e) {
      if (out) { out.hidden = false; out.className = 'chat-ex-result bad'; out.textContent = e.message; }
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function hintFromCard(card) {
    if (!card) return;
    const track = card.getAttribute('data-ex-track');
    const lesson = card.getAttribute('data-ex-lesson');
    const out = card.querySelector('.chat-ex-result');
    try {
      const r = await api('/coding/hint', { method: 'POST', body: { track_id: track, lesson_id: lesson } });
      if (out) {
        out.hidden = false;
        out.className = 'chat-ex-result muted';
        out.textContent = r.exhausted
          ? (r.message || 'No more hints')
          : `Hint #${r.level}: ${r.hint || ''}`;
      }
    } catch (e) {
      toast(e.message, true);
    }
  }

  function appendBubble(role, content, meta) {
    const box = $('chatLog');
    if (!box) return;
    const lang = langOf(content);
    const div = document.createElement('div');
    div.className = 'chat-bubble ' + role;
    const pending = meta && meta.pending;
    let actions = '';
    if (pending && pending.pending_id) {
      actions = `<div class="chat-actions">
        <button class="btn ok" data-approve="${esc(pending.pending_id)}">موافقة / Approve</button>
        <button class="btn danger" data-reject="${esc(pending.pending_id)}">رفض / Reject</button>
      </div>`;
    }
    const kind = meta && meta.response_kind ? `<div class="chat-meta muted">kind: ${esc(meta.response_kind)}</div>` : '';
    const srcMap = {
      live_web: { ar: 'معلومات ويب مباشرة', en: 'Live web information' },
      unavailable: { ar: 'الويب غير متاح', en: 'Web unavailable' },
      model_knowledge: { ar: 'معرفة النموذج', en: 'Model knowledge' },
      external_tool: { ar: 'نتيجة أداة خارجية', en: 'External tool result' },
      verified_knowledge: { ar: 'معرفة موثقة', en: 'Verified knowledge' },
    };
    let srcHtml = '';
    if (meta && meta.information_source) {
      const s = srcMap[meta.information_source] || { ar: meta.information_source, en: meta.information_source };
      srcHtml = `<div class="chat-meta muted">source: ${esc(lang === 'en' ? s.en : s.ar)}</div>`;
    }
    const citeHtml = (meta && meta.citations && meta.citations.length)
      ? `<div class="chat-meta muted">citations: ${meta.citations.length} (provenance retained; not fabricated)</div>`
      : '';
    const learnHtml = renderLearningContext(meta && meta.learning_context, lang);
    const trainHtml = renderTrainingChips(meta && meta.tools, lang);
    const codingHtml = role === 'assistant' ? renderCodingCard(meta && meta.coding, lang) : '';
    div.innerHTML = `
      <div class="chat-role">${role === 'user' ? 'المالك / Owner' : 'عقل PFAI / Brain'}</div>
      <div class="chat-text">${esc(content)}</div>
      ${learnHtml}
      ${trainHtml}
      ${codingHtml}
      ${renderProgress(meta && meta.progress, lang)}
      ${renderTimeline(meta && meta.timeline, lang)}
      ${actions}
      ${kind}
      ${srcHtml}
      ${citeHtml}
      ${meta && meta.provider ? `<div class="chat-meta muted">${esc(providerLabel(meta.provider))} · ${esc(meta.status || '')}</div>` : ''}
    `;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    div.querySelectorAll('[data-approve]').forEach(btn => btn.onclick = () => approvePending(btn.getAttribute('data-approve')));
    div.querySelectorAll('[data-reject]').forEach(btn => btn.onclick = () => rejectPending(btn.getAttribute('data-reject')));
    wireCodingCard(div);
  }

  function setBusy(v) {
    busy = v;
    const send = $('chatSend');
    const input = $('chatInput');
    if (send) send.disabled = v;
    if (input) input.disabled = v;
    const ind = $('chatBusy');
    if (ind) ind.style.display = v ? 'inline-flex' : 'none';
  }

  function applyLearningHub(hub) {
    if (!hub || !hub.academy) return;
    const a = hub.academy;
    const elLevel = $('chatLearnLevel');
    const elMode = $('chatLearnMode');
    const elDone = $('chatLearnDone');
    const elWeak = $('chatLearnWeak');
    if (elLevel) elLevel.textContent = a.display_level || '—';
    if (elMode) elMode.textContent = a.mode || '—';
    if (elDone) elDone.textContent = a.completed_lessons != null ? a.completed_lessons : '—';
    if (elWeak) elWeak.textContent = (a.weak_skills || []).slice(0, 3).join(', ') || '—';
  }

  async function refreshLearningRail() {
    try {
      const [profile, elig] = await Promise.all([
        api('/coding/profile'),
        api('/platform/training/eligibility').catch(() => null),
      ]);
      applyLearningHub({
        academy: {
          display_level: profile.display_level,
          mode: profile.mode,
          completed_lessons: (profile.completed_lessons || []).length,
          weak_skills: Object.entries(profile.skills || {}).filter(([, v]) => Number(v) < 0.6).map(([k]) => k),
        },
      });
      const chip = $('chatTrainElig');
      if (chip && elig) {
        chip.textContent = elig.eligible
          ? 'Eligible · كتابة من الشات · ليس قراءة فقط'
          : `Not eligible · ${(elig.reason || (elig.blockers || [])[0] || '—').toString().slice(0, 48)}`;
        chip.className = 'chat-chip ' + (elig.eligible ? 'ok' : 'warn');
      }
    } catch (e) {
      /* rail is best-effort */
    }
  }

  async function sendChat() {
    if (busy) return;
    const input = $('chatInput');
    const message = (input.value || '').trim();
    if (!message) return;
    input.value = '';
    appendBubble('user', message, {});
    setBusy(true);
    try {
      const r = await api('/chat/message', {
        method: 'POST',
        body: { message, conversation_id: conversationId, language: langOf(message) },
      });
      conversationId = r.conversation_id;
      localStorage.setItem('pfai_chat_conversation', conversationId);
      appendBubble('assistant', r.reply || '', {
        timeline: r.timeline,
        progress: r.progress,
        pending: r.pending,
        provider: r.provider,
        status: r.status,
        response_kind: r.response_kind,
        information_source: r.information_source,
        citations: r.citations,
        coding: r.coding,
        learning_context: r.learning_context,
        tools: r.tools,
      });
      if (r.learning_hub) applyLearningHub(r.learning_hub);
      else refreshLearningRail();
      if (r.status === 'failed') toast('الأمر فشل / Command failed', true);
      else if (r.status === 'waiting_for_approval') toast('بانتظار موافقتك / Waiting for approval');
      else toast('تم / Done');
      loadChatAudit();
    } catch (e) {
      appendBubble('assistant', e.message || String(e), { status: 'failed', timeline: [{ status: 'failed', detail: e.message }] });
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function approvePending(id) {
    setBusy(true);
    try {
      const r = await api('/chat/approve/' + encodeURIComponent(id), { method: 'POST' });
      appendBubble('assistant', r.reply || 'Approved', { timeline: r.timeline, status: r.status, provider: 'owner-gate' });
      toast('تمت الموافقة والتنفيذ');
      loadChatAudit();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function rejectPending(id) {
    setBusy(true);
    try {
      const r = await api('/chat/reject/' + encodeURIComponent(id), { method: 'POST' });
      appendBubble('assistant', r.reply || 'Rejected', { status: 'rejected' });
      toast('تم الرفض');
      loadChatAudit();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function loadChatHistory() {
    if (!conversationId) return;
    try {
      const r = await api('/chat/conversations/' + encodeURIComponent(conversationId));
      const box = $('chatLog');
      if (!box) return;
      box.innerHTML = '';
      (r.messages || []).forEach(m => {
        appendBubble(m.role === 'user' ? 'user' : 'assistant', m.content, {
          timeline: (m.meta || {}).timeline,
          progress: (m.meta || {}).progress,
          pending: (m.meta || {}).pending,
          provider: (m.meta || {}).provider,
          response_kind: (m.meta || {}).response_kind,
          coding: (m.meta || {}).coding,
          learning_context: (m.meta || {}).learning_context,
          status: m.status,
        });
      });
    } catch (e) {
      /* new conversation is fine */
    }
  }

  async function newChat() {
    conversationId = null;
    localStorage.removeItem('pfai_chat_conversation');
    lastExercise = null;
    const box = $('chatLog');
    if (box) box.innerHTML = '';
    appendBubble('assistant',
      'مرحباً — أنا عقل PFAI 8.15 (حلقة تعلّم+تدريب موحّدة 24/7).\n'
      + '• أوامر التشغيل · الأكاديمية · التعلّم المستمر · التدريب الحقيقي · الويب الحي\n'
      + '• التدريب من الشات مسار كتابة — ليس قراءة فقط — بلا ترقية أوزان صامتة\n'
      + '• تعليم أكواد أقوى: تلميحات تشخيصية + تسليم تمارين من الشات\n'
      + '• بحث ويب/جلب روابط عبر أدوات سياسة آمنة (بدون نتائج ملفّقة)\n\n'
      + 'Hello — PFAI 8.15 Unified learn+train 24/7.\n'
      + '• Ops · Academy · Continuous learning · Real LoRA · Live web\n'
      + '• Training from chat is a write path — never silent weight promote\n'
      + '• Web search/fetch via policy-gated tools (no fabricated results)',
      { status: 'completed', provider: 'ready' }
    );
    refreshLearningRail();
  }

  async function loadChatAudit() {
    try {
      const r = await api('/chat/audit?limit=15');
      const el = $('chatAudit');
      if (!el) return;
      el.textContent = JSON.stringify(r.items || [], null, 2);
    } catch (e) {
      const el = $('chatAudit');
      if (el) el.textContent = e.message;
    }
  }

  async function loadChatTools() {
    try {
      const r = await api('/chat/tools');
      const el = $('chatTools');
      if (!el) return;
      const tools = r.tools || [];
      const open = !!r.open_chat_tools;
      const locked = Number(r.locked_count || 0);
      const edu = tools.filter(t => /coding_|training_|learner_|run_sandbox|continuous_/.test(t.name || ''));
      const banner = open
        ? `<div class="chat-chip ok">النظام مفتوح · Open execution · ${tools.length} tools · 0 locks</div>`
        : `<div class="chat-chip warn">أقفال نشطة · ${locked} locked</div>`;
      el.innerHTML = `<div class="muted">provider: ${esc(r.provider)}</div>`
        + `<div class="chat-learn-strip" style="margin:8px 0">${banner}</div>`
        + `<div class="chat-learn-strip" style="margin:8px 0">${edu.map(t =>
          `<span class="chat-chip">${esc(t.name)}${(!open && t.requires_approval) ? ' 🔒' : ''}</span>`
        ).join('')}</div>`
        + tools.map(t => `<span class="tag">${esc(t.name)}${(!open && t.requires_approval) ? ' 🔒' : ''}</span>`).join('');
      const lockEl = $('chatOpenStatus');
      if (lockEl) {
        lockEl.textContent = open ? 'مفتوح بالكامل / Fully open' : `مقفل جزئيًا (${locked})`;
        lockEl.className = 'chat-chip ' + (open ? 'ok' : 'warn');
      }
    } catch (e) {
      const el = $('chatTools');
      if (el) el.textContent = e.message;
    }
  }

  window.initCommandChat = function initCommandChat() {
    const send = $('chatSend');
    const input = $('chatInput');
    if (send) send.onclick = sendChat;
    if (input) {
      input.onkeydown = (ev) => {
        if (ev.key === 'Enter' && !ev.shiftKey) {
          ev.preventDefault();
          sendChat();
        }
      };
    }
    const neu = $('chatNew');
    if (neu) neu.onclick = newChat;
    const quick = document.querySelectorAll('[data-chat-quick]');
    quick.forEach(btn => btn.onclick = () => {
      $('chatInput').value = btn.getAttribute('data-chat-quick');
      sendChat();
    });
    if ($('chatLog') && !$('chatLog').dataset.booted) {
      $('chatLog').dataset.booted = '1';
      if (conversationId) loadChatHistory();
      else newChat();
    }
    loadChatTools();
    loadChatAudit();
    refreshLearningRail();
  };

  window.loadCommandChat = function loadCommandChat() {
    initCommandChat();
    loadChatHistory();
    loadChatTools();
    loadChatAudit();
    refreshLearningRail();
  };

  window.loadAcademy = async function loadAcademy() {
    try {
      const [profile, tracks, projects] = await Promise.all([
        api('/coding/profile'),
        api('/coding/tracks'),
        api('/coding/projects'),
      ]);
      $('acLevel').textContent = profile.display_level || '—';
      $('acMode').textContent = profile.mode || '—';
      $('acDone').textContent = (profile.completed_lessons || []).length;
      const weak = Object.entries(profile.skills || {}).filter(([, v]) => Number(v) < 0.6).map(([k]) => k);
      $('acWeak').textContent = weak.slice(0, 3).join(', ') || '—';
      $('acProfile').textContent = JSON.stringify(profile, null, 2);
      $('acTracks').innerHTML = (tracks.tracks || []).map(t =>
        `<button class="btn" style="margin:4px" onclick="startTrack('${esc(t.id)}')">${esc(t.title)} (${esc(t.lesson_count)})</button>`
      ).join('') || '<div class="empty">لا توجد مسارات</div>';
      $('acProjects').innerHTML = (projects.projects || []).map(p =>
        `<div class="status-card"><strong>${esc(p.title)}</strong><span>${esc(p.level)} · ${esc((p.skills || []).join(', '))}</span></div>`
      ).join('') || '<div class="empty">لا توجد مشاريع</div>';
      refreshLearningRail();
    } catch (e) {
      toast(e.message, true);
    }
  };

  window.startTrack = async function startTrack(id) {
    try {
      const r = await api('/coding/path?track_id=' + encodeURIComponent(id) + '&goal=' + encodeURIComponent('Learn ' + id));
      $('acProfile').textContent = JSON.stringify(r, null, 2);
      toast('تم بناء مسار تعليمي');
      const navBtn = document.querySelector('[data-id="chat"]');
      if (typeof show === 'function') show('chat', navBtn);
      $('chatInput').value = 'علمني ' + id;
      sendChat();
    } catch (e) { toast(e.message, true); }
  };

  window.startAssessment = async function startAssessment() {
    try {
      const r = await api('/coding/assessment');
      $('acProfile').textContent = JSON.stringify(r, null, 2);
      toast('assessment جاهز — استخدم Chat أو /coding/assessment/submit');
      const navBtn = document.querySelector('[data-id="chat"]');
      if (typeof show === 'function') show('chat', navBtn);
      $('chatInput').value = 'اختبر مستواي';
      sendChat();
    } catch (e) { toast(e.message, true); }
  };

  window.setCodingMode = async function setCodingMode(mode) {
    try {
      const r = await api('/coding/mode', { method: 'POST', body: { mode } });
      toast('Mode = ' + r.mode);
      loadAcademy();
    } catch (e) { toast(e.message, true); }
  };

  window.runAcademySandbox = async function runAcademySandbox() {
    try {
      const r = await api('/coding/sandbox', { method: 'POST', body: { code: $('acCode').value, test_code: $('acTests').value } });
      $('acSandbox').textContent = JSON.stringify(r, null, 2);
      toast(r.passed ? 'Sandbox passed' : 'Sandbox failed', !r.passed);
    } catch (e) { toast(e.message, true); }
  };

  window.reviewAcademyCode = async function reviewAcademyCode() {
    try {
      const r = await api('/coding/review', { method: 'POST', body: { code: $('acCode').value, language: 'python' } });
      $('acSandbox').textContent = JSON.stringify(r, null, 2);
      toast('Review ready');
    } catch (e) { toast(e.message, true); }
  };

  window.searchAcademyKnowledge = async function searchAcademyKnowledge() {
    try {
      const r = await api('/coding/knowledge?q=' + encodeURIComponent($('acKnowQ').value || ''));
      $('acKnow').textContent = JSON.stringify(r, null, 2);
    } catch (e) { toast(e.message, true); }
  };
})();
