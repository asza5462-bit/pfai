const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  user: null,
  needsSetup: false,
  provider: null,
  projects: [],
  project: null,
  conversation: null,
  openFiles: new Map(),
  activeFile: null,
  busy: false,
};

async function api(path, options = {}) {
  const init = {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  };
  const response = await fetch(path, init);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" ? body.detail || body.message : body;
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function toast(message, type = "") {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = message;
  $("#toast-stack").append(item);
  setTimeout(() => item.remove(), 4200);
}

function setBusy(busy, label = "أفكر في أفضل تنفيذ…") {
  state.busy = busy;
  $("#send-btn").disabled = busy;
  $("#chat-input").disabled = busy;
  $("#agent-progress").classList.toggle("hidden", !busy);
  $("#agent-progress em").textContent = label;
  $("#agent-state").textContent = busy ? "يعمل الآن…" : "جاهز للبناء";
}

async function boot() {
  bindEvents();
  try {
    const auth = await api("/api/auth/status");
    state.needsSetup = auth.needs_setup;
    if (!auth.authenticated) {
      showAuth(auth.needs_setup, auth.setup_token_required);
      return;
    }
    state.user = auth.user;
    await enterStudio();
  } catch (error) {
    showAuth(false, false);
    $("#auth-error").textContent = error.message;
  }
}

function showAuth(needsSetup, setupTokenRequired) {
  $("#auth-screen").classList.remove("hidden");
  $("#app").classList.add("hidden");
  state.needsSetup = needsSetup;
  $("#auth-submit-label").textContent = needsSetup ? "إنشاء حساب المالك" : "دخول";
  $("#auth-copy").textContent = needsSetup
    ? "الإعداد الأول والوحيد. أنشئ حساب المالك للبدء."
    : "ادخل إلى مساحة البرمجة الذكية الخاصة بك.";
  const needsToken = needsSetup && setupTokenRequired;
  $("#setup-token-wrap").classList.toggle("hidden", !needsToken);
  $("#setup-token").required = needsToken;
  $("#auth-password").autocomplete = needsSetup ? "new-password" : "current-password";
  setTimeout(() => (needsToken ? $("#setup-token") : $("#auth-username")).focus(), 50);
}

async function enterStudio() {
  $("#auth-screen").classList.add("hidden");
  $("#app").classList.remove("hidden");
  await Promise.all([loadProvider(), loadProjects()]);
}

async function handleAuth(event) {
  event.preventDefault();
  $("#auth-error").textContent = "";
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const payload = {
      username: $("#auth-username").value.trim(),
      password: $("#auth-password").value,
    };
    const path = state.needsSetup ? "/api/auth/setup" : "/api/auth/login";
    if (state.needsSetup) payload.setup_token = $("#setup-token").value;
    const result = await api(path, { method: "POST", body: JSON.stringify(payload) });
    state.user = result.user;
    await enterStudio();
  } catch (error) {
    $("#auth-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function loadProvider() {
  try {
    state.provider = await api("/api/provider");
    const pill = $("#provider-pill");
    pill.classList.toggle("online", state.provider.configured);
    pill.classList.toggle("offline", !state.provider.configured);
    pill.querySelector("span").textContent = state.provider.configured
      ? `${state.provider.provider} · ${state.provider.model}`
      : "AI غير متصل";
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadProjects() {
  try {
    const result = await api("/api/projects");
    state.projects = result.projects;
    renderProjectMenu();
    const remembered = localStorage.getItem("nova.project");
    const target = state.projects.find((project) => project.id === remembered) || state.projects[0];
    if (target) await selectProject(target.id);
    else showEmptyProject();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderProjectMenu() {
  const menu = $("#project-menu");
  menu.innerHTML = "";
  state.projects.forEach((project) => {
    const button = document.createElement("button");
    button.textContent = `${project.name} · ${project.file_count || 0} ملفات`;
    button.addEventListener("click", () => {
      menu.classList.add("hidden");
      selectProject(project.id);
    });
    menu.append(button);
  });
  const add = document.createElement("button");
  add.className = "new-project-menu";
  add.textContent = "＋ مشروع جديد";
  add.addEventListener("click", () => openProjectDialog());
  menu.append(add);
}

function showEmptyProject() {
  state.project = null;
  $("#project-name").textContent = "اختر مشروعاً";
  $("#status-project").textContent = "No project";
  $("#empty-project").classList.remove("hidden");
  $("#file-tree").innerHTML = "";
}

async function selectProject(projectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  state.project = project;
  localStorage.setItem("nova.project", project.id);
  $("#project-name").textContent = project.name;
  $("#status-project").textContent = project.name;
  $("#empty-project").classList.add("hidden");
  state.openFiles.clear();
  state.activeFile = null;
  showWelcome();
  await Promise.all([loadTree(), loadConversations(), loadDiff()]);
}

function openProjectDialog() {
  $("#project-error").textContent = "";
  $("#project-dialog").showModal();
  setTimeout(() => $("#new-project-name").focus(), 50);
}

async function createProject(event) {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type=submit]");
  submit.disabled = true;
  $("#project-error").textContent = "";
  try {
    const template = $('input[name="template"]:checked').value;
    const result = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        name: $("#new-project-name").value.trim(),
        description: $("#new-project-description").value.trim(),
        template,
      }),
    });
    localStorage.setItem("nova.project", result.project.id);
    $("#project-dialog").close();
    event.currentTarget.reset();
    await loadProjects();
    if (state.project?.id !== result.project.id) {
      throw new Error("تم إنشاء المشروع لكن تعذّر فتحه تلقائياً");
    }
    toast("تم إنشاء مساحة العمل", "success");
  } catch (error) {
    $("#project-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function loadTree() {
  if (!state.project) return;
  try {
    const result = await api(`/api/projects/${state.project.id}/tree`);
    const root = $("#file-tree");
    root.innerHTML = "";
    result.tree.forEach((node) => root.append(renderTreeNode(node, 0)));
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderTreeNode(node, depth) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";
  const row = document.createElement("div");
  row.className = "tree-row";
  row.style.paddingLeft = `${8 + depth * 13}px`;
  row.dataset.path = node.path;
  const ext = node.name.split(".").pop().toLowerCase();
  const icon = node.type === "directory" ? "◇" : fileIcon(ext);
  row.innerHTML = `<span class="tree-chevron">${node.type === "directory" ? "▾" : ""}</span><span class="tree-icon ${ext}">${icon}</span><span>${escapeHtml(node.name)}</span>`;
  wrapper.append(row);
  if (node.type === "directory") {
    const children = document.createElement("div");
    (node.children || []).forEach((child) => children.append(renderTreeNode(child, depth + 1)));
    wrapper.append(children);
    row.addEventListener("click", () => {
      const hidden = children.classList.toggle("hidden");
      row.querySelector(".tree-chevron").textContent = hidden ? "▸" : "▾";
    });
  } else {
    row.addEventListener("click", () => openFile(node.path));
  }
  return wrapper;
}

function fileIcon(ext) {
  const map = { py: "Py", js: "JS", jsx: "JS", ts: "TS", tsx: "TS", html: "<>", css: "#", json: "{}", md: "M↓", yml: "Y", yaml: "Y", sh: "$" };
  return map[ext] || "·";
}

async function searchWorkspace() {
  if (!state.project) return toast("اختر مشروعاً أولاً");
  const query = prompt("ابحث داخل كل ملفات المشروع");
  if (!query) return;
  try {
    const result = await api(
      `/api/projects/${state.project.id}/search?q=${encodeURIComponent(query)}&limit=200`,
    );
    const root = $("#file-tree");
    root.innerHTML = "";
    result.results.forEach((match) => {
      const row = document.createElement("div");
      row.className = "tree-row search-result";
      row.innerHTML = `<span class="tree-icon">${match.line}</span><span><strong>${escapeHtml(match.path)}</strong><code>${escapeHtml(match.preview)}</code></span>`;
      row.addEventListener("click", () => openFile(match.path, match.line));
      root.append(row);
    });
    if (!result.results.length) {
      root.innerHTML = '<div class="empty-project"><p>لا توجد نتائج</p></div>';
    }
    toast(`${result.results.length} نتيجة — اضغط التحديث للعودة إلى الملفات`, "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function openFile(path, line = null) {
  if (!state.project) return;
  try {
    let file = state.openFiles.get(path);
    if (!file) {
      const result = await api(`/api/projects/${state.project.id}/file?path=${encodeURIComponent(path)}`);
      file = {
        path,
        content: result.content,
        original: result.content,
        language: result.language,
        checksum: result.checksum,
        dirty: false,
      };
      state.openFiles.set(path, file);
    }
    state.activeFile = path;
    $("#welcome").classList.add("hidden");
    $("#code-area").classList.remove("hidden");
    $("#code-editor").value = file.content;
    $("#breadcrumb").textContent = path;
    updateLines();
    renderTabs();
    $$(".tree-row").forEach((row) => row.classList.toggle("active", row.dataset.path === path));
    $("#code-editor").focus();
    if (line && line > 0) {
      const editor = $("#code-editor");
      const lines = editor.value.split("\n");
      const offset = lines.slice(0, line - 1).reduce((total, value) => total + value.length + 1, 0);
      editor.setSelectionRange(offset, offset + (lines[line - 1]?.length || 0));
      editor.scrollTop = Math.max(0, (line - 3) * 21);
      updateCursor();
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

function showWelcome() {
  state.activeFile = null;
  $("#welcome").classList.remove("hidden");
  $("#code-area").classList.add("hidden");
  renderTabs();
}

function renderTabs() {
  const tabs = $("#editor-tabs");
  tabs.innerHTML = "";
  const welcome = document.createElement("div");
  welcome.className = `welcome-tab ${state.activeFile ? "" : "active"}`;
  welcome.innerHTML = '<span class="nova-file">N</span> البداية';
  welcome.addEventListener("click", showWelcome);
  tabs.append(welcome);
  state.openFiles.forEach((file, path) => {
    const tab = document.createElement("div");
    tab.className = `editor-tab ${state.activeFile === path ? "active" : ""} ${file.dirty ? "dirty" : ""}`;
    tab.innerHTML = `<span class="tab-name">${escapeHtml(path.split("/").pop())}</span><span class="tab-close">×</span>`;
    tab.querySelector(".tab-name").addEventListener("click", () => openFile(path));
    tab.querySelector(".tab-close").addEventListener("click", (event) => {
      event.stopPropagation();
      if (file.dirty && !confirm("إغلاق الملف بدون حفظ؟")) return;
      state.openFiles.delete(path);
      if (state.activeFile === path) {
        const next = [...state.openFiles.keys()].at(-1);
        next ? openFile(next) : showWelcome();
      } else renderTabs();
    });
    tabs.append(tab);
  });
}

function editorChanged() {
  if (!state.activeFile) return;
  const file = state.openFiles.get(state.activeFile);
  file.content = $("#code-editor").value;
  file.dirty = file.content !== file.original;
  $("#file-state").textContent = file.dirty ? "غير محفوظ" : "محفوظ";
  renderTabs();
  updateLines();
  updateCursor();
}

function updateLines() {
  const count = Math.max(1, $("#code-editor").value.split("\n").length);
  $("#line-numbers").textContent = Array.from({ length: count }, (_, index) => index + 1).join("\n");
}

function updateCursor() {
  const editor = $("#code-editor");
  const before = editor.value.slice(0, editor.selectionStart);
  const parts = before.split("\n");
  $("#cursor-pos").textContent = `Ln ${parts.length}, Col ${parts.at(-1).length + 1}`;
}

async function saveActiveFile() {
  if (!state.project || !state.activeFile) return;
  const file = state.openFiles.get(state.activeFile);
  try {
    const result = await api(`/api/projects/${state.project.id}/file`, {
      method: "PUT",
      body: JSON.stringify({
        path: file.path,
        content: file.content,
        expected_checksum: file.checksum || null,
      }),
    });
    file.original = file.content;
    file.checksum = result.checksum;
    file.dirty = false;
    $("#file-state").textContent = "محفوظ";
    renderTabs();
    await Promise.all([loadTree(), loadDiff()]);
    toast(`حُفظ ${file.path}`, "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function createFile() {
  if (!state.project) return openProjectDialog();
  const path = prompt("مسار الملف الجديد، مثال: src/app.py");
  if (!path) return;
  try {
    await api(`/api/projects/${state.project.id}/file`, {
      method: "PUT",
      body: JSON.stringify({ path, content: "" }),
    });
    await loadTree();
    await openFile(path);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadConversations() {
  if (!state.project) return;
  try {
    const result = await api(`/api/projects/${state.project.id}/conversations`);
    if (result.conversations.length) {
      state.conversation = result.conversations[0];
      await loadMessages();
    } else {
      await newConversation(false);
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

async function newConversation(clear = true) {
  if (!state.project) return;
  try {
    const result = await api(`/api/projects/${state.project.id}/conversations`, {
      method: "POST",
      body: JSON.stringify({ title: "محادثة جديدة" }),
    });
    state.conversation = result.conversation;
    if (clear) renderMessages([]);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadMessages() {
  if (!state.project || !state.conversation) return;
  const result = await api(`/api/projects/${state.project.id}/conversations/${state.conversation.id}/messages`);
  renderMessages(result.messages);
}

function renderMessages(messages) {
  const container = $("#messages");
  container.innerHTML = "";
  if (!messages.length) {
    addMessage("assistant", "أنا جاهز. صف فكرتك بدقة، وسأحوّلها إلى كود حقيقي داخل المشروع.");
    return;
  }
  messages.forEach((message) => addMessage(message.role, message.content, message.metadata || {}));
}

function addMessage(role, content, metadata = {}) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const title = role === "assistant" ? '<span class="agent-orb tiny"></span>NOVA' : "أنت";
  article.innerHTML = `<div class="message-role">${title}</div><div class="message-body"></div>`;
  article.querySelector(".message-body").textContent = content;
  const files = metadata.changed_files || [];
  if (files.length) {
    const meta = document.createElement("div");
    meta.className = "message-meta";
    files.forEach((path) => {
      const chip = document.createElement("button");
      chip.className = "meta-chip";
      chip.textContent = path;
      chip.addEventListener("click", () => openFile(path));
      meta.append(chip);
    });
    article.append(meta);
  }
  $("#messages").append(article);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

async function sendChat() {
  if (state.busy) return;
  if (!state.project) {
    openProjectDialog();
    return toast("أنشئ مشروعاً أولاً", "error");
  }
  if (!state.provider?.configured) {
    openSettings();
    return toast("اربط مزود الذكاء أولاً", "error");
  }
  if (!state.conversation) await newConversation(false);
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  addMessage("user", message);
  input.value = "";
  setBusy(true);
  try {
    const result = await api(`/api/projects/${state.project.id}/chat`, {
      method: "POST",
      body: JSON.stringify({
        conversation_id: state.conversation.id,
        message,
        selected_file: state.activeFile,
        auto_apply: $("#auto-apply").checked,
        allow_commands: $("#agent-commands").checked,
      }),
    });
    addMessage("assistant", result.message, { changed_files: result.changed_files });
    appendTerminalAgentResult(result);
    if (result.changed_files?.length) {
      result.changed_files.forEach((path) => state.openFiles.delete(path));
      await Promise.all([loadTree(), loadDiff()]);
      await openFile(result.changed_files[0]);
    }
  } catch (error) {
    addMessage("assistant", `تعذّر إكمال الطلب: ${error.message}`);
    if (error.status === 424) openSettings();
  } finally {
    setBusy(false);
    input.focus();
  }
}

function appendTerminalAgentResult(result) {
  if (!result.commands?.length) return;
  result.commands.forEach((command) => {
    appendTerminal(`nova › ${command.command || "agent command"}`, "term-command");
    if (command.stdout) appendTerminal(command.stdout, command.ok ? "term-ok" : "");
    if (command.stderr) appendTerminal(command.stderr, "term-error");
  });
}

function appendTerminal(text, className = "") {
  const line = document.createElement("div");
  line.className = className;
  line.textContent = text;
  $("#terminal-output").append(line);
  $("#terminal-view").scrollTop = $("#terminal-view").scrollHeight;
}

async function runTerminal(event) {
  event.preventDefault();
  if (!state.project) return toast("اختر مشروعاً", "error");
  const input = $("#terminal-input");
  const command = input.value.trim();
  if (!command) return;
  input.value = "";
  appendTerminal(`nova › ${command}`, "term-command");
  try {
    const result = await api(`/api/projects/${state.project.id}/command`, {
      method: "POST",
      body: JSON.stringify({ command }),
    });
    if (result.stdout) appendTerminal(result.stdout, result.ok ? "term-ok" : "");
    if (result.stderr) appendTerminal(result.stderr, "term-error");
    appendTerminal(`exit ${result.exit_code} · ${result.duration_ms}ms`, result.ok ? "term-muted" : "term-error");
    await loadDiff();
  } catch (error) {
    appendTerminal(error.message, "term-error");
  }
}

async function loadDiff() {
  if (!state.project) return;
  try {
    const result = await api(`/api/projects/${state.project.id}/diff`);
    $("#diff-view").textContent = result.diff || "No changes.";
    const count = (result.diff.match(/^diff --git/gm) || []).length;
    $("#change-count").textContent = count;
  } catch {
    $("#diff-view").textContent = "Unable to load changes.";
  }
}

async function createCheckpoint() {
  if (!state.project) return toast("اختر مشروعاً", "error");
  const message = prompt("وصف نقطة الحفظ", "NOVA checkpoint");
  if (!message) return;
  try {
    const result = await api(`/api/projects/${state.project.id}/checkpoint`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    if (!result.ok && !String(result.stderr || "").includes("nothing to commit")) {
      throw new Error(result.stderr || "تعذّر إنشاء نقطة الحفظ");
    }
    await loadDiff();
    toast("تم إنشاء نقطة حفظ Git", "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function openHistory() {
  if (!state.project || !state.activeFile) return toast("افتح ملفاً أولاً", "error");
  try {
    const result = await api(
      `/api/projects/${state.project.id}/revisions?path=${encodeURIComponent(state.activeFile)}`,
    );
    $("#history-path").textContent = state.activeFile;
    const list = $("#history-list");
    list.innerHTML = "";
    result.revisions.forEach((revision) => {
      const item = document.createElement("button");
      item.className = "history-item";
      const timestamp = new Date(revision.created_at * 1000).toLocaleString("ar");
      item.innerHTML = `<strong>${revision.operation} · ${revision.actor}</strong><span>${timestamp}</span><small>${revision.checksum.slice(0, 12)} · ${revision.size} bytes</small>`;
      item.addEventListener("click", () => restoreRevision(revision.id));
      list.append(item);
    });
    if (!result.revisions.length) list.innerHTML = '<p class="modal-copy">لا توجد نسخ محفوظة لهذا الملف.</p>';
    $("#history-dialog").showModal();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function restoreRevision(revisionId) {
  if (!confirm("استرجاع هذه النسخة؟ ستُحفظ الحالة الحالية في السجل.")) return;
  try {
    const result = await api(`/api/projects/${state.project.id}/restore`, {
      method: "POST",
      body: JSON.stringify({ revision_id: revisionId }),
    });
    $("#history-dialog").close();
    state.openFiles.delete(result.path);
    await Promise.all([loadTree(), loadDiff()]);
    await openFile(result.path);
    toast("تم استرجاع النسخة", "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

function exportProject() {
  if (!state.project) return toast("اختر مشروعاً", "error");
  window.location.href = `/api/projects/${state.project.id}/export`;
}

function previewProject() {
  if (!state.project) return toast("اختر مشروعاً", "error");
  const path = state.activeFile?.endsWith(".html") ? state.activeFile : "index.html";
  window.open(`/api/projects/${state.project.id}/preview/${encodeURI(path)}`, "_blank", "noopener");
}

function showBottom(name) {
  $("#bottom-panel").classList.remove("collapsed");
  $$(".bottom-tabs button[data-bottom]").forEach((button) => button.classList.toggle("active", button.dataset.bottom === name));
  $("#terminal-view").classList.toggle("hidden", name !== "terminal");
  $("#diff-view").classList.toggle("hidden", name !== "diff");
  if (name === "diff") loadDiff();
}

async function openSettings() {
  await loadProvider();
  $("#provider-select").value = state.provider?.provider || "openai";
  $("#model-input").value = state.provider?.model || "gpt-5.2";
  $("#base-url-input").value = state.provider?.base_url || "https://api.openai.com/v1";
  $("#api-key-input").value = "";
  $("#provider-result").textContent = state.provider?.configured ? "يوجد مفتاح محفوظ ومشفّر." : "أدخل مفتاح API للاتصال.";
  $("#provider-result").className = "form-result";
  $("#settings-dialog").showModal();
}

async function saveProvider(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    state.provider = await api("/api/provider", {
      method: "PUT",
      body: JSON.stringify({
        provider: $("#provider-select").value,
        model: $("#model-input").value.trim(),
        api_key: $("#api-key-input").value.trim() || null,
        base_url: $("#base-url-input").value.trim() || null,
      }),
    });
    $("#settings-dialog").close();
    await loadProvider();
    toast("حُفظ إعداد الذكاء", "success");
  } catch (error) {
    $("#provider-result").textContent = error.message;
    $("#provider-result").className = "form-result";
  } finally {
    button.disabled = false;
  }
}

async function testProvider() {
  const result = $("#provider-result");
  result.textContent = "جارٍ اختبار الاتصال…";
  result.className = "form-result";
  try {
    // Save form first so the test uses current fields.
    state.provider = await api("/api/provider", {
      method: "PUT",
      body: JSON.stringify({
        provider: $("#provider-select").value,
        model: $("#model-input").value.trim(),
        api_key: $("#api-key-input").value.trim() || null,
        base_url: $("#base-url-input").value.trim() || null,
      }),
    });
    const test = await api("/api/provider/test", { method: "POST" });
    result.textContent = test.ok ? "اتصال ناجح — المحرك جاهز." : `وصل الرد لكن تحقق الاختبار فشل: ${test.response}`;
    result.className = `form-result ${test.ok ? "ok" : ""}`;
    await loadProvider();
  } catch (error) {
    result.textContent = error.message;
  }
}

function bindEvents() {
  $("#auth-form").addEventListener("submit", handleAuth);
  $("#project-menu-btn").addEventListener("click", () => $("#project-menu").classList.toggle("hidden"));
  $("#create-project-btn").addEventListener("click", openProjectDialog);
  $("#project-form").addEventListener("submit", createProject);
  $("#settings-btn").addEventListener("click", openSettings);
  $("#preview-btn").addEventListener("click", previewProject);
  $("#checkpoint-btn").addEventListener("click", createCheckpoint);
  $("#history-btn").addEventListener("click", openHistory);
  $("#export-btn").addEventListener("click", exportProject);
  $("#settings-form").addEventListener("submit", saveProvider);
  $("#test-provider-btn").addEventListener("click", testProvider);
  $$(".dialog-close").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
  $("#save-btn").addEventListener("click", saveActiveFile);
  $("#refresh-tree-btn").addEventListener("click", loadTree);
  $("#new-file-btn").addEventListener("click", createFile);
  $("#code-editor").addEventListener("input", editorChanged);
  $("#code-editor").addEventListener("keyup", updateCursor);
  $("#code-editor").addEventListener("click", updateCursor);
  $("#code-editor").addEventListener("scroll", () => { $("#line-numbers").scrollTop = $("#code-editor").scrollTop; });
  $("#code-editor").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveActiveFile();
    }
    if (event.key === "Tab") {
      event.preventDefault();
      const editor = event.currentTarget;
      const start = editor.selectionStart;
      editor.setRangeText("  ", start, editor.selectionEnd, "end");
      editorChanged();
    }
  });
  $("#send-btn").addEventListener("click", sendChat);
  $("#chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendChat();
    }
  });
  $("#new-chat-btn").addEventListener("click", () => newConversation(true));
  $("#terminal-form").addEventListener("submit", runTerminal);
  $$(".bottom-tabs button[data-bottom]").forEach((button) => button.addEventListener("click", () => showBottom(button.dataset.bottom)));
  $("#close-bottom").addEventListener("click", () => $("#bottom-panel").classList.add("collapsed"));
  $("#toggle-bottom").addEventListener("click", () => {
    $("#bottom-panel").classList.toggle("collapsed");
    if (!$("#bottom-panel").classList.contains("collapsed")) $("#terminal-input").focus();
  });
  $$(".quick-grid button").forEach((button) => button.addEventListener("click", () => {
    $("#chat-input").value = button.dataset.prompt;
    $("#chat-input").focus();
  }));
  $("#attach-current").addEventListener("click", () => toast(state.activeFile ? `سيُرفق ${state.activeFile} مع الطلب` : "لا يوجد ملف مفتوح"));
  $("#provider-select").addEventListener("change", () => {
    const providerName = $("#provider-select").value;
    $("#base-url-wrap").classList.toggle("hidden", providerName === "anthropic");
    if (providerName === "anthropic" && !$("#model-input").value.includes("claude")) $("#model-input").value = "claude-sonnet-4-5";
    if (providerName === "openai" && $("#model-input").value.includes("claude")) $("#model-input").value = "gpt-5.2";
  });
  $("#logout-btn").addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    location.reload();
  });
  $(".activity[data-panel=explorer]").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $(".activity[data-panel=git]").addEventListener("click", () => showBottom("diff"));
  $(".activity[data-panel=chat]").addEventListener("click", () => $("#app .chat-panel").classList.toggle("mobile-closed"));
  $(".activity[data-panel=search]").addEventListener("click", searchWorkspace);
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".project-switcher")) $("#project-menu").classList.add("hidden");
  });
}

boot();
