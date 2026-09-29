(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("chart");
  const ctx = canvas.getContext("2d");
  let candles = [];
  let user = null;
  let bridgeToken = null;
  let pulseTimer = null;
  let refreshTimer = null;
  let pulseAnim = 0;

  function resize() {
    canvas.width = window.innerWidth * devicePixelRatio;
    canvas.height = window.innerHeight * devicePixelRatio;
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  }
  window.addEventListener("resize", resize);
  resize();

  function draw() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    ctx.clearRect(0, 0, w, h);
    if (candles.length) {
      const view = candles.slice(-72);
      const max = Math.max(...view.map((c) => c.high));
      const min = Math.min(...view.map((c) => c.low));
      const pad = (max - min) * 0.08 || 1;
      const top = max + pad, bot = min - pad;
      const left = w * 0.08, right = w * 0.96, midY = h * 0.42, chartH = h * 0.38;
      const slot = (right - left) / view.length;
      ctx.beginPath();
      view.forEach((c, i) => {
        const x = left + i * slot + slot * 0.5;
        const y = midY - ((c.close - bot) / (top - bot) - 0.5) * chartH;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.strokeStyle = "rgba(138,106,40,0.55)";
      ctx.lineWidth = 2;
      ctx.stroke();
      pulseAnim = (pulseAnim + 0.01) % 1;
      ctx.fillStyle = "rgba(200,162,74,0.14)";
      ctx.fillRect(left + pulseAnim * (right - left), midY - chartH * 0.55, 2, chartH * 1.1);
    }
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  const biasClass = (b) => (b === "buy" ? "bias-buy" : b === "sell" ? "bias-sell" : "bias-neutral");

  async function api(path, opts = {}) {
    let r;
    try {
      r = await fetch(path, {
        credentials: "include",
        headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
        ...opts,
      });
    } catch (netErr) {
      const msg = String(netErr && netErr.message || netErr || "");
      const friendly = new Error(
        /load failed|failed to fetch|networkerror|aborted/i.test(msg)
          ? "انقطع الاتصال بالخادم (الطلب استغرق طويلاً). أعد المحاولة — الربط أصبح أسرع الآن."
          : (msg || "فشل الاتصال بالخادم")
      );
      friendly.status = 0;
      friendly.network = true;
      throw friendly;
    }
    const text = await r.text();
    let j = {};
    try { j = text ? JSON.parse(text) : {}; } catch { j = { error: text }; }
    if (!r.ok) {
      const detail = typeof j.detail === "string" ? j.detail : (j.detail && j.detail.msg) || j.error || j.message;
      const err = new Error(detail || `HTTP ${r.status}`);
      err.status = r.status;
      err.body = j;
      throw err;
    }
    return j;
  }

  function showAuth(msg, ok = false) {
    const el = $("authMsg");
    el.textContent = msg || "";
    el.classList.toggle("ok", !!ok);
  }

  function setGate(on) {
    $("authGate").classList.toggle("hidden", on);
    $("deskApp").classList.toggle("hidden", !on);
  }

  function showTab(name) {
    ["mt5FormLogin", "loginForm", "registerForm"].forEach((id) => $(id).classList.add("hidden"));
    ["tabMt5", "tabLogin", "tabRegister"].forEach((id) => $(id).classList.remove("on"));
    if (name === "mt5") { $("mt5FormLogin").classList.remove("hidden"); $("tabMt5").classList.add("on"); }
    if (name === "login") { $("loginForm").classList.remove("hidden"); $("tabLogin").classList.add("on"); }
    if (name === "register") { $("registerForm").classList.remove("hidden"); $("tabRegister").classList.add("on"); }
  }

  async function loadServers() {
    const input = $("mt5Server");
    const list = $("mt5ServerList");
    try {
      const j = await api("/api/exness/servers");
      if (list) {
        list.innerHTML = "";
        (j.servers || []).forEach((s) => {
          const o = document.createElement("option");
          o.value = s;
          list.appendChild(o);
        });
      }
      // Keep whatever the user typed; only set default if empty
      if (input && !input.value.trim()) {
        input.value = j.default || "Exness-MT5Trial15";
      }
    } catch (_) {
      if (list) {
        ["Exness-MT5Trial15", "Exness-MT5Trial", "Exness-MT5Real"].forEach((s) => {
          const o = document.createElement("option");
          o.value = s;
          list.appendChild(o);
        });
      }
    }
  }

  function setBridgeUI(bridge, token, agentCommand, metaConfigured, linuxConfigured) {
    const online = !!(bridge && bridge.online);
    const provider = (bridge && bridge.provider) || (bridge && bridge.execution) || "";
    const label =
      provider === "mt5_linux" ? "Linux MT5" :
      provider === "metaapi" ? "MetaApi" : "التنفيذ";
    $("bridgePill").textContent = online ? `${label}: متصل Exness` : `${label}: غير متصل`;
    $("bridgePill").classList.toggle("on", online);
    if ($("bridgeStatusText")) {
      $("bridgeStatusText").textContent =
        (bridge && bridge.detail) || (online ? "متصل للتنفيذ الحقيقي" : "بانتظار تفعيل مسار بدون Windows");
    }
    if ($("cloudAccountLine")) {
      const id = (bridge && (bridge.account_id || bridge.base_url || (bridge.account && bridge.account.login))) || "—";
      $("cloudAccountLine").textContent = `المعرّف / الرابط: ${id}`;
    }
    if ($("metaConfiguredLine") && metaConfigured != null) {
      $("metaConfiguredLine").textContent = metaConfigured
        ? "توكن MetaApi: محفوظ ومفعّل"
        : "توكن MetaApi: غير محفوظ";
      $("metaConfiguredLine").classList.toggle("ok", !!metaConfigured);
    }
    if ($("linuxConfiguredLine") && linuxConfigured != null) {
      $("linuxConfiguredLine").textContent = linuxConfigured
        ? "منفّذ Linux: محفوظ"
        : "منفّذ Linux: غير مضبوط";
      $("linuxConfiguredLine").classList.toggle("ok", !!linuxConfigured);
    }
    if (token) bridgeToken = token;
    if (agentCommand && $("agentCmd")) $("agentCmd").value = agentCommand;
  }

  async function loadWays() {
    try {
      const j = await fetch("/api/ways").then((r) => r.json());
      if ($("waysFinding")) $("waysFinding").textContent = j.finding_ar || "";
      if ($("metaConfiguredLine")) {
        $("metaConfiguredLine").textContent = j.metaapi_configured ? "توكن MetaApi: محفوظ ومفعّل" : "توكن MetaApi: غير محفوظ";
        $("metaConfiguredLine").classList.toggle("ok", !!j.metaapi_configured);
      }
      if ($("linuxConfiguredLine")) {
        $("linuxConfiguredLine").textContent = j.mt5_linux_configured ? "منفّذ Linux: محفوظ" : "منفّذ Linux: غير مضبوط";
        $("linuxConfiguredLine").classList.toggle("ok", !!j.mt5_linux_configured);
      }
    } catch (_) {}
  }

  function renderTrades(list, el) {
    el.innerHTML = "";
    if (!list.length) { el.innerHTML = "<li>لا صفقات بعد</li>"; return; }
    list.slice(0, 20).forEach((t) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong class="${biasClass(t.side)}">${t.side}</strong> ${t.lot} @ ${t.entry}<span>${t.status} · pnl ${Number(t.pnl || 0).toFixed(2)} · ${t.mode}</span>`;
      el.appendChild(li);
    });
  }

  function render(data) {
    candles = data.candles_tail || candles;
    const sig = data.signal || {};
    const tick = data.tick || {};
    const acc = data.account || {};
    const risk = data.risk || {};
    const pulse = data.pulse || {};
    const ready = data.readiness || {};
    $("readyPill").textContent = ready.summary_ar || ready.grade || "—";
    $("readyPill").classList.toggle("on", !!ready.exness_mt5_ready);
    $("statePill").textContent = data.state || "—";
    const live = !!(ready.live_execution || ready.exness_mt5_ready || (acc.mode === "mt5" && acc.connected && acc.server && acc.server !== "AURUM-PAPER"));
    $("modePill").textContent = live ? `Exness حي · ${acc.server || "MT5"}` : (acc.mode === "paper" ? "ورقي (تجربة)" : (acc.mode || "—"));
    $("modePill").classList.toggle("on", live);
    $("symbolPill").textContent = data.symbol || "XAUUSDm";
    $("latencyPill").textContent = data.latency_ms != null ? `${data.latency_ms}ms` : "—";
    $("price").textContent = tick.bid || "—";
    $("conf").textContent = sig.confluence != null ? `${Math.round(sig.confluence * 100)}%` : "—";
    $("action").textContent = sig.action || "—";
    $("action").className = biasClass(sig.action === "flat" ? "neutral" : sig.action);
    $("pulseBias").textContent = pulse.bias ? `${pulse.bias} ${Math.round((pulse.score || 0) * 100)}` : "—";
    $("qualityPill").textContent = sig.quality && sig.quality !== "none" ? sig.quality : "—";
    $("equity").textContent = acc.equity != null ? Number(acc.equity).toFixed(2) : "—";
    $("riskState").textContent = risk.halted ? "متوقف" : "نشط";
    $("narrative").textContent = sig.narrative || data.disclaimer || "";
    $("headline").textContent =
      !acc.connected && acc.mode === "mt5" ? "بانتظار اكتمال الربط السحابي بـ Exness" :
      risk.halted ? "المخاطرة متوقفة" :
      data.state === "IN_TRADE" ? "صفقة مفتوحة على الحساب" :
      sig.action === "buy" ? "تقارب شراء" :
      sig.action === "sell" ? "تقارب بيع" : "تحليل حي — بانتظار إشارة قوية";

    const schools = $("schools");
    schools.innerHTML = "";
    (sig.schools || []).forEach((s) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong class="${biasClass(s.bias)}">${s.bias}</strong> · ${Math.round(s.strength * 100)}%<span>${s.school}</span>`;
      schools.appendChild(li);
    });
    const inst = sig.institutional || {};
    $("inst").textContent = `التحيز: ${inst.bias || "—"} | ${inst.institutional_score ?? "—"}\n${(inst.reasons || []).join(" · ") || "—"}`;
    $("btnStart").classList.toggle("on", !!data.auto_trade);
    $("btnStart").textContent = data.auto_trade ? "المكتب يعمل" : "ابدأ التداول";
  }

  async function loadTrades() {
    const j = await api("/api/trades");
    renderTrades(j.trades || [], $("trades"));
    renderTrades(j.trades || [], $("tradesFull"));
  }

  function applyProvisionUI(j) {
    const prov = (j && j.provision) || {};
    const live = !!(j && j.live_execution);
    const online = !!(j && j.bridge && j.bridge.online);
    if (!$("connectMsg")) return;
    if (live || online) {
      $("connectMsg").textContent = (prov.message) || "متصل بسحابة Exness — التنفيذ الحقيقي جاهز";
      $("connectMsg").classList.add("ok");
      return;
    }
    if (prov.status === "error" || (j && j.last_error && j.last_error.error && prov.status !== "pending")) {
      const err = prov.message || (j.last_error && j.last_error.error) || "فشل الربط السحابي";
      $("connectMsg").textContent = err;
      $("connectMsg").classList.remove("ok");
      return;
    }
    if (prov.status === "pending" && prov.message) {
      $("connectMsg").textContent = prov.message;
      $("connectMsg").classList.remove("ok");
    }
  }

  async function refreshCloudStatusOnly() {
    try {
      const j = await api("/api/cloud/status");
      setBridgeUI(j.bridge || j.cloud, null, null, j.metaapi_configured, j.mt5_linux_configured);
      if (j.account) {
        $("equity").textContent = Number(j.account.equity || 0).toFixed(2);
      }
      applyProvisionUI(j);
      return j;
    } catch (_) {
      const j = await api("/api/bridge/status");
      setBridgeUI(j.bridge || j.cloud, null, null, j.metaapi_configured, j.mt5_linux_configured);
      return j;
    }
  }

  async function refreshBridge(forceNew = false) {
    try {
      const path = forceNew ? "/api/cloud/reset" : "/api/cloud/reconnect";
      const j = await api(path, {
        method: "POST",
        body: JSON.stringify(forceNew ? {} : { force_new: false }),
      });
      setBridgeUI(j.bridge || j.cloud, null, null, true);
      if (j.account) {
        $("equity").textContent = Number(j.account.equity || 0).toFixed(2);
        $("modePill").textContent = j.account.mode || "mt5";
      }
      if (j.started && j.started.scan) render(j.started.scan);
      if ($("connectMsg")) {
        $("connectMsg").textContent = j.message || "";
        $("connectMsg").classList.toggle("ok", !!(j.account && j.account.connected));
      }
    } catch (e) {
      try {
        await refreshCloudStatusOnly();
      } catch (_) {}
      if ($("connectMsg")) {
        $("connectMsg").textContent = e.message || "تعذّر تحديث السحابة";
        $("connectMsg").classList.remove("ok");
      }
    }
  }

  if ($("btnResetCloud")) {
    $("btnResetCloud").onclick = async () => {
      if (!confirm("إعادة إنشاء الطرفية السحابية بالكامل؟")) return;
      $("connectMsg").textContent = "جاري إعادة الربط الكامل…";
      await refreshBridge(true);
    };
  }
  if ($("btnRefreshBridge")) {
    $("btnRefreshBridge").onclick = async () => {
      $("connectMsg").textContent = "جاري التحديث…";
      // Status-only first; full reconnect only if user confirms when cooled down
      try {
        const st = await refreshCloudStatusOnly();
        const prov = (st && st.provision) || {};
        if (prov.status === "error" && /ساعة|دقيقة|cooldown|rejected/i.test(prov.message || "")) {
          $("connectMsg").textContent = prov.message;
          $("connectMsg").classList.remove("ok");
          return;
        }
        if (!(st && st.live_execution)) {
          await refreshBridge(false);
        }
      } catch (e) {
        $("connectMsg").textContent = e.message || "تعذّر التحديث";
        $("connectMsg").classList.remove("ok");
      }
    };
  }

  if ($("btnSaveMetaToken")) {
    $("btnSaveMetaToken").onclick = async () => {
      const token = ($("cloudMetaToken").value || "").trim();
      if (token.length < 10) {
        $("connectMsg").textContent = "الصق توكن MetaApi صالحاً أولاً";
        $("connectMsg").classList.remove("ok");
        return;
      }
      try {
        const j = await api("/api/cloud/token", {
          method: "POST",
          body: JSON.stringify({ token, check_token: true }),
        });
        $("connectMsg").textContent = j.message || "تم الحفظ";
        $("connectMsg").classList.add("ok");
        $("cloudMetaToken").value = "";
        setBridgeUI(j.bridge || j.cloud, null, null, true, null);
        if (j.account) {
          $("equity").textContent = Number(j.account.equity || 0).toFixed(2);
          $("modePill").textContent = j.account.mode || "mt5";
        }
        if (j.started && j.started.scan) render(j.started.scan);
        await loadWays();
      } catch (e) {
        $("connectMsg").textContent = e.message || "فشل حفظ التوكن";
        $("connectMsg").classList.remove("ok");
      }
    };
  }

  if ($("btnSaveLinux")) {
    $("btnSaveLinux").onclick = async () => {
      const base_url = ($("linuxExecutorUrl").value || "").trim();
      if (!base_url) {
        $("connectMsg").textContent = "أدخل رابط منفّذ Linux مثل http://IP:5001";
        $("connectMsg").classList.remove("ok");
        return;
      }
      try {
        const j = await api("/api/executor/linux", {
          method: "POST",
          body: JSON.stringify({
            base_url,
            token: ($("linuxExecutorToken").value || "").trim(),
            probe: true,
          }),
        });
        $("connectMsg").textContent = j.message || "تم الحفظ";
        $("connectMsg").classList.toggle("ok", !!(j.account && j.account.connected) || !!(j.probe && j.probe.ok));
        setBridgeUI(j.bridge, null, null, null, true);
        await loadWays();
      } catch (e) {
        $("connectMsg").textContent = e.message || "فشل حفظ المنفّذ";
        $("connectMsg").classList.remove("ok");
      }
    };
  }

  async function pulse() {
    try {
      const j = await api("/api/pulse");
      $("statePill").textContent = j.state || "—";
      $("latencyPill").textContent = j.elapsed_ms != null ? `${j.elapsed_ms}ms` : "—";
      if (j.tick) $("price").textContent = j.tick.bid;
      if (j.account) $("equity").textContent = Number(j.account.equity).toFixed(2);
      if ((j.manage && (j.manage.closed || []).length) || j.executed_pending) {
        await loadTrades();
      }
    } catch (e) {
      if (e.status === 401) enterLoggedOut();
    }
  }

  function startTimers() {
    clearInterval(pulseTimer); clearInterval(refreshTimer);
    pulseTimer = setInterval(pulse, 1000);
    refreshTimer = setInterval(async () => {
      try {
        render(await api("/api/scan", { method: "POST" }));
        await loadTrades();
        await refreshCloudStatusOnly();
      } catch (e) {
        if (e.status === 401) enterLoggedOut();
      }
    }, 8000);
  }

  function enterLoggedOut() {
    user = null; bridgeToken = null;
    setGate(false);
    clearInterval(pulseTimer); clearInterval(refreshTimer);
    showTab("mt5");
  }

  async function enterLoggedIn(u, extra = {}) {
    user = u;
    setGate(true);
    $("userPill").textContent = u.username;
    await loadWays();
    try {
      const st = await refreshCloudStatusOnly();
      if (extra.bridge) {
        setBridgeUI(extra.bridge, extra.bridge_token, extra.agent_command, st && st.metaapi_configured, st && st.mt5_linux_configured);
      }
    } catch (_) {
      if (extra.bridge_token || extra.agent_command || extra.bridge) {
        setBridgeUI(extra.bridge, extra.bridge_token, extra.agent_command, true, null);
      }
    }
    try { render(await api("/api/scan", { method: "POST" })); }
    catch { render(await fetch("/api/status").then((r) => r.json())); }
    await loadTrades();
    startTimers();
    if (extra.message) {
      showAuth(extra.message, !!(extra.account && extra.account.connected));
      if ($("connectMsg")) {
        $("connectMsg").textContent = extra.message;
        $("connectMsg").classList.toggle("ok", !!(extra.account && extra.account.connected));
      }
    }
  }

  $("tabMt5").onclick = () => showTab("mt5");
  $("tabLogin").onclick = () => showTab("login");
  $("tabRegister").onclick = () => showTab("register");

  async function loadSetupNext() {
    try {
      const j = await fetch("/api/setup-next").then((r) => r.json());
      if ($("setupNext")) $("setupNext").textContent = j.next_ar || "";
      if (j.default_server && $("mt5Server") && !$("mt5Server").dataset.touched) {
        $("mt5Server").value = j.default_server;
      }
      return j;
    } catch (_) { return null; }
  }

  if ($("mt5Server")) {
    $("mt5Server").addEventListener("input", () => { $("mt5Server").dataset.touched = "1"; });
  }

  $("mt5FormLogin").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("mt5FormLogin").querySelector("button[type=submit]");
    const metaTok = ($("mt5MetaToken") && $("mt5MetaToken").value || "").trim();
    const setup = await loadSetupNext();
    if (!metaTok && !(setup && setup.metaapi_configured)) {
      showAuth("الصق توكن MetaApi أولاً — افتح رابط «توليد التوكن» أعلاه");
      if ($("mt5MetaToken")) $("mt5MetaToken").focus();
      return;
    }
    const server = ($("mt5Server").value || "").trim();
    if (!server.toLowerCase().includes("exness")) {
      showAuth("تأكد من اسم السيرفر كما في Exness (مثال: Exness-MT5Trial15)");
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = "جاري الربط…"; }
    showAuth("جاري الارتباط السحابي بـ Exness… عادةً أقل من 30 ثانية");
    try {
      const j = await api("/api/auth/mt5-login", {
        method: "POST",
        body: JSON.stringify({
          mt5_login: $("mt5Login").value.trim(),
          mt5_password: $("mt5Pass").value,
          mt5_server: server,
          symbol: $("mt5Symbol").value.trim() || "XAUUSDm",
          auto_start: true,
          metaapi_token: metaTok || null,
        }),
      });
      showAuth(j.message || "تم الربط السحابي", !!(j.account && j.account.connected) || !!(j.cloud && j.cloud.ok));
      await enterLoggedIn(j.user, j);
      if (!(j.account && j.account.connected)) {
        document.querySelector('.tabs button[data-tab="connect"]')?.click();
        // Poll background MetaApi deploy without blocking login again
        for (let i = 0; i < 8; i++) {
          await new Promise((r) => setTimeout(r, 4000));
          try {
            const st = await refreshCloudStatusOnly();
            const online = st && st.bridge && st.bridge.online;
            if (online) {
              showAuth("اكتمل الربط السحابي — جاهز للتداول", true);
              break;
            }
          } catch (_) {}
        }
      }
    } catch (err) {
      showAuth(err.message || "فشل الارتباط");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "ارتباط سحابي وابدأ التداول"; }
    }
  };

  $("loginForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const j = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: $("loginUser").value.trim(), password: $("loginPass").value }),
      });
      await enterLoggedIn(j.user);
    } catch (err) { showAuth(err.message); }
  };

  $("registerForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const j = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username: $("regUser").value.trim(),
          password: $("regPass").value,
          password_confirm: $("regPass2").value,
        }),
      });
      await enterLoggedIn(j.user);
    } catch (err) { showAuth(err.message); }
  };

  $("btnLogout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); enterLoggedOut(); };

  document.querySelectorAll(".tabs button").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      ["trade", "connect", "history"].forEach((name) => {
        $(`tab-${name}`).classList.toggle("hidden", btn.dataset.tab !== name);
      });
    };
  });

  $("btnStart").onclick = async () => {
    try {
      const j = await api("/api/start", { method: "POST" });
      if (!j.ok) {
        if ($("connectMsg")) { $("connectMsg").textContent = j.message || j.error; $("connectMsg").classList.remove("ok"); }
        showAuth(j.message || j.error || "تعذّر البدء");
        return;
      }
      if (j.scan) render(j.scan);
      if (j.bridge) setBridgeUI(j.bridge);
      showAuth(j.message || "بدأ التداول", true);
    } catch (e) {
      showAuth(e.message || "تعذّر البدء");
      // Auto-heal common MetaApi stale account errors
      if ((e.message || "").includes("not found") || (e.message || "").includes("تالف")) {
        document.querySelector('.tabs button[data-tab="connect"]')?.click();
        await refreshBridge(true);
      }
    }
  };
  $("btnStop").onclick = async () => {
    await api("/api/stop", { method: "POST" });
    $("btnStart").classList.remove("on");
    $("btnStart").textContent = "ابدأ التداول";
  };
  $("btnScan").onclick = async () => { render(await api("/api/scan", { method: "POST" })); await loadTrades(); };
  $("btnResetRisk").onclick = async () => {
    if (!confirm("إعادة تعيين المخاطر؟")) return;
    await api("/api/risk/reset", { method: "POST" });
    await $("btnScan").onclick();
  };
  $("btnCopyAgent").onclick = async () => {
    const t = $("agentCmd").value;
    try { await navigator.clipboard.writeText(t); $("connectMsg").textContent = "تم النسخ"; $("connectMsg").classList.add("ok"); }
    catch { $("connectMsg").textContent = "انسخ يدوياً من الصندوق"; }
  };

  (async () => {
    await loadServers();
    await loadWays();
    await loadSetupNext();
    showTab("mt5");
    try {
      const st = await api("/api/auth/status");
      if (st.authenticated && st.user) await enterLoggedIn(st.user);
      else {
        setGate(false);
        try {
          const s = await fetch("/api/status").then((r) => r.json());
          candles = s.candles_tail || [];
        } catch (_) {}
      }
    } catch (_) { setGate(false); }
  })();
})();
