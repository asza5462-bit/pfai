/* PFAI Command Chat — Brain UI wired to /chat/* APIs */
(function () {
  let conversationId = localStorage.getItem('pfai_chat_conversation') || null;
  let busy = false;

  const STATUS_LABEL = {
    thinking: { ar: 'فهم الطلب', en: 'Understanding' },
    planning: { ar: 'تخطيط', en: 'Planning' },
    calling_tool: { ar: 'اختيار القدرات', en: 'Selecting capabilities' },
    executing: { ar: 'تنفيذ', en: 'Executing' },
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
    return `<div class="chat-timeline">${timeline.map(s =>
      `<div class="chat-step">${statusChip(s.status, lang)} <span>${esc(s.detail || s.tool || '')}</span></div>`
    ).join('')}</div>`;
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
    div.innerHTML = `
      <div class="chat-role">${role === 'user' ? 'المالك / Owner' : 'عقل PFAI / Brain'}</div>
      <div class="chat-text">${esc(content)}</div>
      ${renderProgress(meta && meta.progress, lang)}
      ${renderTimeline(meta && meta.timeline, lang)}
      ${actions}
      ${kind}
      ${srcHtml}
      ${citeHtml}
      ${meta && meta.provider ? `<div class="chat-meta muted">provider: ${esc(meta.provider)} · status: ${esc(meta.status || '')}</div>` : ''}
    `;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    div.querySelectorAll('[data-approve]').forEach(btn => btn.onclick = () => approvePending(btn.getAttribute('data-approve')));
    div.querySelectorAll('[data-reject]').forEach(btn => btn.onclick = () => rejectPending(btn.getAttribute('data-reject')));
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

  async function sendChat() {
    if (busy) return;
    if (!OWNER_AUTHED) {
      toast('أدخل Owner login أولًا / Enter Owner login first', true);
      openOwner();
      return;
    }
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
      });
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
    if (!OWNER_AUTHED || !conversationId) return;
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
    const box = $('chatLog');
    if (box) box.innerHTML = '';
    appendBubble('assistant', 'مرحباً — أنا عقل PFAI. اطلب تحليل النظام، فحص الصحة، مراجعة البيانات، أو أي أمر تشغيلي. الإجراءات الحساسة تتطلب موافقتك.\n\nHello — I am the PFAI brain. Ask for system analysis, health checks, data review, or operational commands. Sensitive actions require your approval.', { status: 'completed', provider: 'ready' });
  }

  async function loadChatAudit() {
    if (!OWNER_AUTHED) return;
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
    if (!OWNER_AUTHED) return;
    try {
      const r = await api('/chat/tools');
      const el = $('chatTools');
      if (!el) return;
      el.innerHTML = `<div class="muted">provider: ${esc(r.provider)}</div>` +
        (r.tools || []).map(t => `<span class="tag">${esc(t.name)}${t.requires_approval ? ' 🔒' : ''}</span>`).join('');
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
    if (!$('chatLog').dataset.booted) {
      $('chatLog').dataset.booted = '1';
      if (conversationId) loadChatHistory();
      else newChat();
    }
    loadChatTools();
    loadChatAudit();
  };

  window.loadCommandChat = function loadCommandChat() {
    initCommandChat();
    loadChatHistory();
    loadChatTools();
    loadChatAudit();
  };

  window.loadAcademy = async function loadAcademy() {
    if (!OWNER_AUTHED) { toast('سجّل دخول المالك أولاً', true); return; }
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
    } catch (e) {
      toast(e.message, true);
    }
  };

  window.startTrack = async function startTrack(id) {
    try {
      const r = await api('/coding/path?track_id=' + encodeURIComponent(id) + '&goal=' + encodeURIComponent('Learn ' + id));
      $('acProfile').textContent = JSON.stringify(r, null, 2);
      toast('تم بناء مسار تعليمي');
    } catch (e) { toast(e.message, true); }
  };

  window.startAssessment = async function startAssessment() {
    try {
      const r = await api('/coding/assessment');
      $('acProfile').textContent = JSON.stringify(r, null, 2);
      toast('assessment جاهز — استخدم /coding/assessment/submit أو Chat');
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
