(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("chart");
  const ctx = canvas.getContext("2d");
  let candles = [];
  let user = null;
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
      const top = max + pad;
      const bot = min - pad;
      const left = w * 0.08;
      const right = w * 0.96;
      const midY = h * 0.42;
      const chartH = h * 0.38;
      const slot = (right - left) / view.length;
      ctx.beginPath();
      view.forEach((c, i) => {
        const x = left + i * slot + slot * 0.5;
        const y = midY - ((c.close - bot) / (top - bot) - 0.5) * chartH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = "rgba(138,106,40,0.55)";
      ctx.lineWidth = 2;
      ctx.stroke();
      view.forEach((c, i) => {
        const x = left + i * slot + slot * 0.5;
        const yH = midY - ((c.high - bot) / (top - bot) - 0.5) * chartH;
        const yL = midY - ((c.low - bot) / (top - bot) - 0.5) * chartH;
        const yO = midY - ((c.open - bot) / (top - bot) - 0.5) * chartH;
        const yC = midY - ((c.close - bot) / (top - bot) - 0.5) * chartH;
        const bull = c.close >= c.open;
        ctx.strokeStyle = bull ? "rgba(31,122,76,0.75)" : "rgba(163,59,43,0.75)";
        ctx.beginPath();
        ctx.moveTo(x, yH);
        ctx.lineTo(x, yL);
        ctx.stroke();
        const bw = Math.max(2, slot * 0.45);
        ctx.fillStyle = bull ? "rgba(31,122,76,0.55)" : "rgba(163,59,43,0.55)";
        ctx.fillRect(x - bw / 2, Math.min(yO, yC), bw, Math.max(1.5, Math.abs(yC - yO)));
      });
      pulseAnim = (pulseAnim + 0.01) % 1;
      ctx.fillStyle = "rgba(200,162,74,0.14)";
      ctx.fillRect(left + pulseAnim * (right - left), midY - chartH * 0.55, 2, chartH * 1.1);
    }
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  const biasClass = (b) => (b === "buy" ? "bias-buy" : b === "sell" ? "bias-sell" : "bias-neutral");

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const text = await r.text();
    let j = {};
    try { j = text ? JSON.parse(text) : {}; } catch { j = { error: text }; }
    if (!r.ok) {
      const err = new Error(j.detail || j.error || j.message || `HTTP ${r.status}`);
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

  function setGate(authenticated) {
    $("authGate").classList.toggle("hidden", authenticated);
    $("deskApp").classList.toggle("hidden", !authenticated);
  }

  function fillSettings(u) {
    const s = (u && u.settings) || {};
    $("setMode").value = s.mode || "paper";
    $("setSymbol").value = s.symbol || "XAUUSD";
    $("setLogin").value = s.mt5_login || "";
    $("setServer").value = s.mt5_server || "";
    $("setPath").value = s.mt5_path || "";
    $("setPassword").value = "";
    $("setPassword").placeholder = s.has_mt5_password ? " محفوظة مشفّرة — اكتب فقط للتغيير" : "لن تُعرض بعد الحفظ";
  }

  function renderTrades(list, el) {
    el.innerHTML = "";
    if (!list.length) {
      el.innerHTML = "<li>لا صفقات بعد</li>";
      return;
    }
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
    const session = ((sig.schools || []).find((s) => s.school && s.school.startsWith("Session")) || {}).detail || {};

    $("readyPill").textContent = ready.summary_ar || ready.grade || "—";
    $("readyPill").classList.toggle("on", !!ready.paper_ready);
    $("statePill").textContent = data.state || "—";
    $("modePill").textContent = acc.mode || "—";
    $("symbolPill").textContent = data.symbol || "XAUUSD";
    $("latencyPill").textContent = data.latency_ms != null ? `${data.latency_ms}ms` : "—";
    $("price").textContent = tick.bid || "—";
    $("conf").textContent = sig.confluence != null ? `${Math.round(sig.confluence * 100)}%` : "—";
    $("action").textContent = sig.action || "—";
    $("action").className = biasClass(sig.action === "flat" ? "neutral" : sig.action);
    $("pulseBias").textContent = pulse.bias ? `${pulse.bias} ${Math.round((pulse.score || 0) * 100)}` : "—";
    $("pulseBias").className = biasClass(pulse.bias || "neutral");
    $("qualityPill").textContent = sig.quality && sig.quality !== "none" ? sig.quality : "—";
    $("equity").textContent = acc.equity != null ? Number(acc.equity).toFixed(2) : "—";
    $("riskState").textContent = risk.halted ? "متوقف" : "نشط";
    $("narrative").textContent = sig.narrative || data.disclaimer || "";
    $("headline").textContent =
      risk.halted ? "المخاطرة متوقفة — أعد التعيين للمتابعة" :
      data.state === "MANAGING" ? "إدارة ذكية للصفقة" :
      data.state === "IN_TRADE" ? "صفقة مفتوحة" :
      sig.action === "buy" ? "تقارب شراء" :
      sig.action === "sell" ? "تقارب بيع" :
      "انتظار الانضباط";

    const schools = $("schools");
    schools.innerHTML = "";
    (sig.schools || []).forEach((s) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong class="${biasClass(s.bias)}">${s.bias}</strong> · ${Math.round(s.strength * 100)}%<span>${s.school}</span>`;
      schools.appendChild(li);
    });
    const inst = sig.institutional || {};
    $("inst").textContent = [
      `التحيز: ${inst.bias || "—"} | الدرجة: ${inst.institutional_score ?? "—"}`,
      `أسباب: ${(inst.reasons || []).join(" · ") || "—"}`,
      `الجلسة: ${session.killzone || "—"}`,
      inst.disclaimer || "",
    ].join("\n");

    $("btnStart").classList.toggle("on", !!data.auto_trade);
    $("btnStart").textContent = data.auto_trade ? "المكتب يعمل" : "ابدأ التداول";
  }

  async function loadTrades() {
    const j = await api("/api/trades");
    renderTrades(j.trades || [], $("trades"));
    renderTrades(j.trades || [], $("tradesFull"));
  }

  async function refresh() {
    const j = await api("/api/status");
    // status is public; enrich after login via scan if needed
    render(j);
  }

  async function pulse() {
    try {
      const j = await api("/api/pulse");
      $("statePill").textContent = j.state || "—";
      $("latencyPill").textContent = j.elapsed_ms != null ? `${j.elapsed_ms}ms` : "—";
      if (j.tick) $("price").textContent = j.tick.bid;
      if (j.pulse) {
        $("pulseBias").textContent = `${j.pulse.bias} ${Math.round((j.pulse.score || 0) * 100)}`;
        $("pulseBias").className = biasClass(j.pulse.bias || "neutral");
      }
      if (j.account) $("equity").textContent = Number(j.account.equity).toFixed(2);
      if ((j.manage && ((j.manage.closed || []).length || (j.manage.updated || []).length)) || j.executed_pending) {
        await loadTrades();
        await api("/api/scan", { method: "POST" }).then(render).catch(() => {});
      }
    } catch (e) {
      if (e.status === 401) enterLoggedOut();
    }
  }

  function startDeskTimers() {
    clearInterval(pulseTimer);
    clearInterval(refreshTimer);
    pulseTimer = setInterval(pulse, 1000);
    refreshTimer = setInterval(async () => {
      try {
        const s = await api("/api/scan", { method: "POST" });
        render(s);
        await loadTrades();
      } catch (e) {
        if (e.status === 401) enterLoggedOut();
      }
    }, 8000);
  }

  function enterLoggedOut() {
    user = null;
    setGate(false);
    clearInterval(pulseTimer);
    clearInterval(refreshTimer);
  }

  async function enterLoggedIn(u) {
    user = u;
    setGate(true);
    $("userPill").textContent = u.username;
    fillSettings(u);
    showAuth("");
    try {
      const s = await api("/api/scan", { method: "POST" });
      render(s);
    } catch {
      await refresh();
    }
    await loadTrades();
    startDeskTimers();
  }

  // tabs auth
  $("tabLogin").onclick = () => {
    $("tabLogin").classList.add("on");
    $("tabRegister").classList.remove("on");
    $("loginForm").classList.remove("hidden");
    $("registerForm").classList.add("hidden");
  };
  $("tabRegister").onclick = () => {
    $("tabRegister").classList.add("on");
    $("tabLogin").classList.remove("on");
    $("registerForm").classList.remove("hidden");
    $("loginForm").classList.add("hidden");
  };

  $("loginForm").onsubmit = async (e) => {
    e.preventDefault();
    showAuth("جاري الدخول…");
    try {
      const j = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: $("loginUser").value.trim(), password: $("loginPass").value }),
      });
      showAuth("تم الدخول", true);
      await enterLoggedIn(j.user);
    } catch (err) {
      showAuth(err.message || "فشل الدخول");
    }
  };

  $("registerForm").onsubmit = async (e) => {
    e.preventDefault();
    showAuth("جاري إنشاء الحساب…");
    try {
      const j = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username: $("regUser").value.trim(),
          password: $("regPass").value,
          password_confirm: $("regPass2").value,
        }),
      });
      showAuth("تم إنشاء الحساب", true);
      await enterLoggedIn(j.user);
    } catch (err) {
      showAuth(err.message || "فشل التسجيل");
    }
  };

  $("btnLogout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" });
    enterLoggedOut();
  };

  // desk tabs
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
        alert(j.message || j.error || "تعذّر البدء");
        return;
      }
      if (j.scan) render(j.scan);
      alert(j.message || "بدأ المكتب");
    } catch (e) {
      alert(e.message);
    }
  };

  $("btnStop").onclick = async () => {
    const j = await api("/api/stop", { method: "POST" });
    alert(j.message || "توقف");
    $("btnStart").classList.remove("on");
    $("btnStart").textContent = "ابدأ التداول";
  };

  $("btnScan").onclick = async () => {
    const j = await api("/api/scan", { method: "POST" });
    render(j);
    await loadTrades();
  };

  $("btnResetRisk").onclick = async () => {
    if (!confirm("إعادة تعيين حد الخسارة اليومي للمتابعة الورقية؟")) return;
    const j = await api("/api/risk/reset", { method: "POST" });
    alert(j.ok ? "تمت إعادة تعيين المخاطر" : "فشل");
    await $("btnScan").onclick();
  };

  $("mt5Form").onsubmit = async (e) => {
    e.preventDefault();
    $("connectMsg").textContent = "جاري الحفظ…";
    try {
      const body = {
        mode: $("setMode").value,
        symbol: $("setSymbol").value.trim() || "XAUUSD",
        mt5_login: $("setLogin").value.trim(),
        mt5_server: $("setServer").value.trim(),
        mt5_path: $("setPath").value.trim(),
      };
      if ($("setPassword").value) body.mt5_password = $("setPassword").value;
      const j = await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
      user = j.user;
      fillSettings(user);
      $("connectMsg").textContent = "تم حفظ الربط";
      $("connectMsg").classList.add("ok");
      $("modePill").textContent = (j.account && j.account.mode) || body.mode;
    } catch (err) {
      $("connectMsg").textContent = err.message || "فشل الحفظ";
      $("connectMsg").classList.remove("ok");
    }
  };

  // boot
  (async () => {
    try {
      const st = await api("/api/auth/status");
      if (st.needs_setup) {
        $("tabRegister").click();
        showAuth("أنشئ أول حساب مالك للمكتب", true);
      }
      if (st.authenticated && st.user) {
        await enterLoggedIn(st.user);
      } else {
        setGate(false);
        // ambient chart from public status
        try {
          const s = await fetch("/api/status").then((r) => r.json());
          candles = s.candles_tail || [];
        } catch (_) {}
      }
    } catch (_) {
      setGate(false);
    }
  })();
})();
