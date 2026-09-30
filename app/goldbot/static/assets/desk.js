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
      let detail = typeof j.detail === "string" ? j.detail : null;
      if (!detail && j.detail && typeof j.detail === "object") {
        detail = j.detail.detail || j.detail.error || j.detail.msg || j.detail.message;
      }
      detail = detail || j.error || j.message;
      const code = (j.detail && j.detail.error_code) || j.error_code || (j.detail && j.detail.code) || j.code;
      const err = new Error(detail || `HTTP ${r.status}`);
      err.status = r.status;
      err.body = j;
      err.error_code = code || null;
      if (code && detail && !String(detail).includes(String(code))) {
        err.message = `${detail} [${code}]`;
      }
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
        input.value = j.default || "Exness-MT5Real32";
      }
    } catch (_) {
      if (list) {
        ["Exness-MT5Real32", "Exness-MT5Trial15", "Exness-MT5Real"].forEach((s) => {
          const o = document.createElement("option");
          o.value = s;
          list.appendChild(o);
        });
      }
    }
  }

  function setBridgeUI(bridge, token, agentCommand, metaConfigured, linuxConfigured, ctraderConfigured) {
    const online = !!(bridge && bridge.online);
    const provider = (bridge && bridge.provider) || (bridge && bridge.execution) || "";
    const label =
      provider === "ctrader" ? "cTrader" :
      provider === "mt5_linux" ? "Linux MT5" :
      provider === "metaapi" ? "MetaApi" :
      provider === "windows_bridge" ? "Windows" : "التنفيذ";
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
    if ($("ctraderConfiguredLine") && ctraderConfigured != null) {
      $("ctraderConfiguredLine").textContent = ctraderConfigured
        ? "cTrader Open API: مفعّل"
        : "cTrader Open API: غير مضبوط";
      $("ctraderConfiguredLine").classList.toggle("ok", !!ctraderConfigured);
    }
    if (token) bridgeToken = token;
    if (agentCommand && $("agentCmd")) $("agentCmd").value = agentCommand;
  }

  async function loadWays() {
    try {
      const j = await fetch("/api/ways").then((r) => r.json());
      if ($("waysFinding")) $("waysFinding").textContent = j.finding_ar || "";
      if ($("ctraderConfiguredLine")) {
        $("ctraderConfiguredLine").textContent = j.ctrader_ready
          ? "cTrader Open API: جاهز للتنفيذ"
          : (j.ctrader_configured ? "cTrader Open API: تطبيق محفوظ — أكمل التفويض" : "cTrader Open API: غير مضبوط");
        $("ctraderConfiguredLine").classList.toggle("ok", !!(j.ctrader_ready || j.ctrader_configured));
      }
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

  async function refreshCtraderStatus() {
    try {
      const j = await api("/api/ctrader/status");
      if ($("ctraderRedirectUri")) $("ctraderRedirectUri").value = j.redirect_uri || "";
      if ($("ctraderStatusLine")) {
        $("ctraderStatusLine").textContent = j.ready
          ? `حالة cTrader: جاهز · حساب ${j.account_id || "—"}`
          : (j.configured
            ? (j.has_token ? "حالة cTrader: فوّض ثم اختر الحساب" : "حالة cTrader: احفظ التطبيق ثم فوّض")
            : "حالة cTrader: أدخل Client ID/Secret");
        $("ctraderStatusLine").classList.toggle("ok", !!j.ready);
      }
      if ($("ctraderConfiguredLine")) {
        $("ctraderConfiguredLine").textContent = j.ready
          ? "cTrader Open API: جاهز للتنفيذ"
          : (j.configured ? "cTrader Open API: تطبيق محفوظ — أكمل التفويض" : "cTrader Open API: غير مضبوط");
        $("ctraderConfiguredLine").classList.toggle("ok", !!(j.ready || j.configured));
      }
      if (j.bridge) setBridgeUI(j.bridge, null, null, null, null, j.ready || j.configured);
      return j;
    } catch (_) {
      return null;
    }
  }

  async function bindCtraderAccount(accountId, live) {
    $("connectMsg").textContent = "جاري ربط حساب cTrader…";
    $("connectMsg").classList.remove("ok");
    try {
      const j = await api("/api/ctrader/bind", {
        method: "POST",
        body: JSON.stringify({ account_id: Number(accountId), live: live == null ? null : !!live }),
      });
      setBridgeUI(j.bridge || {}, null, null, null, null, true);
      if (j.account && j.account.equity != null) {
        $("equity").textContent = Number(j.account.equity || 0).toFixed(2);
      }
      $("connectMsg").textContent = j.message || "تم ربط cTrader";
      $("connectMsg").classList.toggle("ok", !!(j.live_execution || (j.account && j.account.connected)));
      await refreshCtraderStatus();
    } catch (e) {
      $("connectMsg").textContent = e.message || "تعذّر ربط cTrader";
      $("connectMsg").classList.remove("ok");
    }
  }

  async function listCtraderAccounts() {
    const list = $("ctraderAccountsList");
    if (list) list.innerHTML = "<li>جاري التحميل…</li>";
    try {
      const j = await api("/api/ctrader/accounts");
      if (!list) return;
      list.innerHTML = "";
      const rows = j.accounts || [];
      if (!rows.length) {
        list.innerHTML = "<li>لا حسابات — تأكد أن حساب Exness على منصة cTrader وأن التفويض اكتمل</li>";
        return;
      }
      rows.forEach((a) => {
        const li = document.createElement("li");
        const title = `${a.brokerTitle || "cTrader"} · ${a.traderLogin || a.ctidTraderAccountId}${a.isLive ? " · Live" : " · Demo"}`;
        li.innerHTML = `<strong>${title}</strong> <span>${a.depositCurrency || ""} · ${a.ctidTraderAccountId}</span>`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tiny";
        btn.textContent = "ربط هذا الحساب";
        btn.onclick = () => bindCtraderAccount(a.ctidTraderAccountId, a.isLive);
        li.appendChild(btn);
        list.appendChild(li);
      });
    } catch (e) {
      if (list) list.innerHTML = `<li>${e.message || "تعذّر جلب الحسابات"}</li>`;
    }
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
      const code = prov.code || (j.last_error && j.last_error.code) || "";
      const err = prov.message || (j.last_error && j.last_error.error) || "فشل الربط السحابي";
      $("connectMsg").textContent = code ? `${err} [${code}]` : err;
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
      setBridgeUI(
        j.bridge || j.cloud,
        null,
        null,
        j.metaapi_configured,
        j.mt5_linux_configured,
        j.ctrader_ready || j.ctrader_configured
      );
      if (j.account) {
        $("equity").textContent = Number(j.account.equity || 0).toFixed(2);
      }
      applyProvisionUI(j);
      await refreshCtraderStatus();
      return j;
    } catch (_) {
      const j = await api("/api/bridge/status");
      setBridgeUI(j.bridge || j.cloud, null, null, j.metaapi_configured, j.mt5_linux_configured, null);
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
      if (!confirm("سيتم حذف الطرفية السحابية العالقة من MetaApi وإنشاء واحدة جديدة. هل تريد المتابعة؟")) return;
      $("connectMsg").textContent = "جاري حذف الطرفية العالقة وإنشاء طرفية جديدة…";
      $("connectMsg").classList.remove("ok");
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
        const cool = (st && st.cooldown) || null;
        if (cool && cool.message) {
          $("connectMsg").textContent = cool.message;
          $("connectMsg").classList.remove("ok");
          return;
        }
        if (prov.status === "error" && /ساعة|دقيقة|cooldown|rejected/i.test(prov.message || "")) {
          $("connectMsg").textContent = prov.message;
          $("connectMsg").classList.remove("ok");
          return;
        }
        if (!(st && st.live_execution)) {
          await refreshBridge(false);
          try {
            const diag = await api("/api/cloud/diagnose");
            if (diag && !diag.live_execution && diag.message && $("connectMsg")) {
              const code = diag.error_code ? ` [${diag.error_code}]` : "";
              if (!$("connectMsg").classList.contains("ok")) {
                $("connectMsg").textContent = `${diag.message}${code}`;
              }
            }
          } catch (_) {}
        }
      } catch (e) {
        $("connectMsg").textContent = e.message || "تعذّر التحديث";
        $("connectMsg").classList.remove("ok");
      }
    };
  }

  async function loadMetaAccounts() {
    const list = $("metaAccountsList");
    if (!list) return;
    list.innerHTML = "<li>جاري التحميل…</li>";
    try {
      const j = await api("/api/cloud/accounts");
      const rows = j.accounts || [];
      if (!rows.length) {
        list.innerHTML = "<li>لا حسابات بعد — أضف حساب MT5 من لوحة MetaApi وانتظر Connected</li>";
        return;
      }
      list.innerHTML = "";
      rows.forEach((a) => {
        const li = document.createElement("li");
        const ready = !!a.ready;
        li.innerHTML = `<strong class="${ready ? "ok" : ""}">${ready ? "Connected" : (a.connectionStatus || a.state || "—")}</strong> · ${a.login || "—"} · ${a.server || "—"}<span>${a.id}</span>`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = ready ? "primary" : "ghost";
        btn.textContent = ready ? "ربط" : "تجربة الربط";
        btn.style.marginTop = "0.35rem";
        btn.onclick = () => bindMetaAccount(a.id, a.region);
        li.appendChild(btn);
        list.appendChild(li);
      });
      if ($("connectMsg") && j.hint_ar) {
        $("connectMsg").textContent = `${j.ready_count || 0} جاهز من ${j.count} — ${j.hint_ar}`;
        $("connectMsg").classList.toggle("ok", (j.ready_count || 0) > 0);
      }
    } catch (e) {
      list.innerHTML = `<li>${e.message || "تعذّر جلب الحسابات"}</li>`;
    }
  }

  async function bindMetaAccount(accountId, region) {
    const id = (accountId || ($("cloudAccountId") && $("cloudAccountId").value) || "").trim();
    if (id.length < 8) {
      $("connectMsg").textContent = "الصق Account ID من لوحة MetaApi أولاً";
      $("connectMsg").classList.remove("ok");
      return;
    }
    if ($("cloudAccountId")) $("cloudAccountId").value = id;
    $("connectMsg").textContent = "جاري ربط الحساب الجاهز من MetaApi…";
    $("connectMsg").classList.remove("ok");
    try {
      const j = await api("/api/cloud/bind", {
        method: "POST",
        body: JSON.stringify({ account_id: id, region: region || null }),
      });
      setBridgeUI(j.bridge || j.cloud, null, null, true);
      if (j.account) {
        $("equity").textContent = Number(j.account.equity || 0).toFixed(2);
        $("modePill").textContent = j.account.mode || "mt5";
      }
      const live = !!(j.live_execution || (j.account && j.account.connected));
      $("connectMsg").textContent = j.message || (live ? "تم الربط الحقيقي" : "تم الحفظ");
      $("connectMsg").classList.toggle("ok", live);
      if ($("cloudAccountLine")) {
        $("cloudAccountLine").textContent = `معرّف الحساب: ${(j.cloud && j.cloud.account_id) || id}`;
      }
      if (live && j.started && j.started.scan) render(j.started.scan);
    } catch (e) {
      $("connectMsg").textContent = e.message || "تعذّر ربط الحساب";
      $("connectMsg").classList.remove("ok");
    }
  }

  if ($("btnBindAccount")) {
    $("btnBindAccount").onclick = () => bindMetaAccount();
  }
  if ($("btnListAccounts")) {
    $("btnListAccounts").onclick = () => loadMetaAccounts();
  }

  if ($("btnSaveExnessCreds")) {
    $("btnSaveExnessCreds").onclick = async () => {
      const pass = ($("cloudMt5Pass") && $("cloudMt5Pass").value || "").trim();
      const server = ($("cloudMt5Server") && $("cloudMt5Server").value || "").trim() || "Exness-MT5Real32";
      if (pass.length < 4) {
        $("connectMsg").textContent = "أدخل كلمة مرور التداول (ليس Investor)";
        $("connectMsg").classList.remove("ok");
        return;
      }
      $("connectMsg").textContent = "جاري حفظ كلمة المرور وإعادة الربط…";
      $("connectMsg").classList.remove("ok");
      try {
        const j = await api("/api/cloud/credentials", {
          method: "POST",
          body: JSON.stringify({
            mt5_password: pass,
            mt5_server: server,
            force_new: true,
          }),
        });
        setBridgeUI(j.bridge || j.cloud, null, null, true);
        if (j.account) {
          $("equity").textContent = Number(j.account.equity || 0).toFixed(2);
          $("modePill").textContent = j.account.mode || "mt5";
        }
        const live = !!(j.account && j.account.connected);
        $("connectMsg").textContent = j.message || (live ? "تم التصحيح والاتصال" : "تم الحفظ — بانتظار اتصال Exness");
        $("connectMsg").classList.toggle("ok", live);
        if ($("cloudMt5Pass")) $("cloudMt5Pass").value = "";
        if (!live) {
          for (let i = 0; i < 18; i++) {
            await new Promise((r) => setTimeout(r, 5000));
            const st = await refreshCloudStatusOnly();
            if (st && (st.live_execution || (st.bridge && st.bridge.online))) {
              $("connectMsg").textContent = "اكتمل الربط السحابي — جاهز";
              $("connectMsg").classList.add("ok");
              break;
            }
            const prov = (st && st.provision) || {};
            if (prov.status === "error" && prov.message) {
              $("connectMsg").textContent = prov.code ? `${prov.message} [${prov.code}]` : prov.message;
              $("connectMsg").classList.remove("ok");
              break;
            }
          }
        }
      } catch (e) {
        $("connectMsg").textContent = e.message || "تعذّر تصحيح بيانات Exness";
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
    // 2s pulse + 10s scan — lighter than 1s/8s; desk loop already manages live trades
    pulseTimer = setInterval(pulse, 2000);
    refreshTimer = setInterval(async () => {
      try {
        render(await api("/api/scan", { method: "POST" }));
        await loadTrades();
        await refreshCloudStatusOnly();
      } catch (e) {
        if (e.status === 401) enterLoggedOut();
      }
    }, 10000);
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
      showAuth("تأكد من اسم السيرفر كما في Exness (مثال: Exness-MT5Real32)");
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
      const live = !!(j.account && j.account.connected) || !!(j.live_execution) || !!(j.cloud_ok);
      const softFail = !live && j.cloud && j.cloud.ok === false;
      const code = j.error_code || (j.cloud && (j.cloud.error_code || j.cloud.code));
      let authMsg = j.message || (live ? "تم الربط السحابي" : "الحساب محفوظ — بانتظار اتصال Exness");
      if (softFail && code && authMsg && !String(authMsg).includes(String(code))) {
        authMsg = `${authMsg} [${code}]`;
      }
      showAuth(authMsg, live && !softFail);
      await enterLoggedIn(j.user, j);
      if (!live) {
        document.querySelector('.tabs button[data-tab="connect"]')?.click();
        // Real servers can take up to ~2 minutes to reach CONNECTED
        let online = false;
        for (let i = 0; i < 24; i++) {
          await new Promise((r) => setTimeout(r, 5000));
          try {
            const st = await refreshCloudStatusOnly();
            online = !!(st && ((st.bridge && st.bridge.online) || st.live_execution));
            if (online) {
              showAuth("اكتمل الربط السحابي — جاهز للتداول", true);
              break;
            }
            const prov = (st && st.provision) || {};
            const cool = (st && st.cooldown) || null;
            if (cool && cool.message) {
              showAuth(cool.message, false);
              break;
            }
            if (prov.status === "error" && prov.message) {
              showAuth(prov.message, false);
              if ($("connectMsg")) {
                $("connectMsg").textContent = prov.message;
                $("connectMsg").classList.remove("ok");
              }
              break;
            }
            if ($("connectMsg") && prov.message) {
              $("connectMsg").textContent = prov.message;
            }
          } catch (_) {}
        }
        if (!online) {
          showAuth(
            (j.message || "لم يكتمل اتصال Exness بعد") + " — من تبويب الربط اضغط «إعادة ربط كامل»",
            false
          );
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
      if (btn.dataset.tab === "connect") {
        loadMetaAccounts().catch(() => {});
      }
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
  if ($("btnSaveCtraderApp")) {
    $("btnSaveCtraderApp").onclick = async () => {
      const client_id = ($("ctraderClientId") && $("ctraderClientId").value || "").trim();
      const client_secret = ($("ctraderClientSecret") && $("ctraderClientSecret").value || "").trim();
      const live = !($("ctraderLive") && $("ctraderLive").value === "0");
      if (!client_id || !client_secret) {
        $("connectMsg").textContent = "أدخل Client ID و Client Secret من openapi.ctrader.com";
        $("connectMsg").classList.remove("ok");
        return;
      }
      $("connectMsg").textContent = "جاري حفظ تطبيق cTrader…";
      try {
        const j = await api("/api/ctrader/app", {
          method: "POST",
          body: JSON.stringify({ client_id, client_secret, live }),
        });
        if ($("ctraderRedirectUri") && j.redirect_uri) $("ctraderRedirectUri").value = j.redirect_uri;
        setBridgeUI(j.bridge || {}, null, null, null, null, true);
        $("connectMsg").textContent = j.message || "تم الحفظ — انسخ Redirect URI إلى Spotware ثم فوّض";
        $("connectMsg").classList.add("ok");
        await refreshCtraderStatus();
      } catch (e) {
        $("connectMsg").textContent = e.message || "تعذّر الحفظ";
        $("connectMsg").classList.remove("ok");
      }
    };
  }
  if ($("btnCtraderAuth")) {
    $("btnCtraderAuth").onclick = async () => {
      $("connectMsg").textContent = "جاري فتح تفويض cTrader…";
      try {
        const j = await api("/api/ctrader/oauth/start");
        if (j.auth_url) {
          window.location.href = j.auth_url;
          return;
        }
        $("connectMsg").textContent = "تعذّر الحصول على رابط التفويض";
        $("connectMsg").classList.remove("ok");
      } catch (e) {
        $("connectMsg").textContent = e.message || "احفظ Client ID/Secret أولاً";
        $("connectMsg").classList.remove("ok");
      }
    };
  }
  if ($("btnListCtraderAccounts")) {
    $("btnListCtraderAccounts").onclick = () => listCtraderAccounts();
  }

  if ($("btnEnableWindows")) {
    $("btnEnableWindows").onclick = async () => {
      $("connectMsg").textContent = "جاري تفعيل مسار Windows…";
      $("connectMsg").classList.remove("ok");
      try {
        const j = await api("/api/bridge/windows-enable", { method: "POST", body: "{}" });
        if ($("agentCmd")) $("agentCmd").value = j.agent_command || "";
        if ($("agentDownloadLink") && j.agent_download) $("agentDownloadLink").href = j.agent_download;
        setBridgeUI(j.bridge || {}, j.bridge_token, j.agent_command, null, null);
        $("connectMsg").textContent = j.message || "تم تفعيل Windows — انسخ الأمر وشغّله";
        $("connectMsg").classList.add("ok");
        try {
          if (j.agent_command) await navigator.clipboard.writeText(j.agent_command);
        } catch (_) {}
      } catch (e) {
        $("connectMsg").textContent = e.message || "تعذّر تفعيل Windows";
        $("connectMsg").classList.remove("ok");
      }
    };
  }
  if ($("btnCopyAgent")) {
    $("btnCopyAgent").onclick = async () => {
      const t = ($("agentCmd") && $("agentCmd").value) || "";
      if (!t) {
        $("connectMsg").textContent = "فعّل مسار Windows أولاً ليظهر الأمر";
        $("connectMsg").classList.remove("ok");
        return;
      }
      try {
        await navigator.clipboard.writeText(t);
        $("connectMsg").textContent = "تم نسخ أمر الوكيل";
        $("connectMsg").classList.add("ok");
      } catch {
        $("connectMsg").textContent = "انسخ يدوياً من الصندوق";
      }
    };
  }

  (async () => {
    await loadServers();
    await loadWays();
    await loadSetupNext();
    showTab("mt5");
    try {
      const params = new URLSearchParams(window.location.search || "");
      const ct = params.get("ctrader");
      if (ct === "authorized") {
        document.querySelector('.tabs button[data-tab="connect"]')?.click();
        $("connectMsg").textContent = "تم تفويض cTrader — اعرض الحسابات واختر واحداً";
        $("connectMsg").classList.add("ok");
        try { await listCtraderAccounts(); } catch (_) {}
        history.replaceState({}, "", "/");
      } else if (ct === "error") {
        document.querySelector('.tabs button[data-tab="connect"]')?.click();
        $("connectMsg").textContent = "فشل تفويض cTrader — تحقق من Redirect URI و Client Secret";
        $("connectMsg").classList.remove("ok");
        history.replaceState({}, "", "/");
      }
    } catch (_) {}
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
