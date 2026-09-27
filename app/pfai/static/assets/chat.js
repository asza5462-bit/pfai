/* PFAI Command Chat — Brain UI wired to /chat/* APIs */
(function () {
  let conversationId = localStorage.getItem('pfai_chat_conversation') || null;
  let busy = false;

  const STATUS_LABEL = {
    thinking: { ar: 'تفكير', en: 'Thinking' },
    planning: { ar: 'تخطيط', en: 'Planning' },
    calling_tool: { ar: 'استدعاء أداة', en: 'Calling tool' },
    executing: { ar: 'تنفيذ', en: 'Executing' },
    waiting_for_approval: { ar: 'بانتظار الموافقة', en: 'Waiting for approval' },
    completed: { ar: 'اكتمل', en: 'Completed' },
    failed: { ar: 'فشل', en: 'Failed' },
    rejected: { ar: 'مرفوض', en: 'Rejected' },
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
    div.innerHTML = `
      <div class="chat-role">${role === 'user' ? 'المالك / Owner' : 'عقل PFAI / Brain'}</div>
      <div class="chat-text">${esc(content)}</div>
      ${renderTimeline(meta && meta.timeline, lang)}
      ${actions}
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
    if (!SECRET) {
      toast('أدخل Owner Secret أولًا / Enter Owner Secret first', true);
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
        pending: r.pending,
        provider: r.provider,
        status: r.status,
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
    if (!SECRET || !conversationId) return;
    try {
      const r = await api('/chat/conversations/' + encodeURIComponent(conversationId));
      const box = $('chatLog');
      if (!box) return;
      box.innerHTML = '';
      (r.messages || []).forEach(m => {
        appendBubble(m.role === 'user' ? 'user' : 'assistant', m.content, {
          timeline: (m.meta || {}).timeline,
          pending: (m.meta || {}).pending,
          provider: (m.meta || {}).provider,
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
    if (!SECRET) return;
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
    if (!SECRET) return;
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
})();
