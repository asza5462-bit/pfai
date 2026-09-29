(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("chart");
  const ctx = canvas.getContext("2d");
  let candles = [];
  let autoOn = false;
  let pulse = 0;

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
    if (!candles.length) {
      requestAnimationFrame(draw);
      return;
    }
    const view = candles.slice(-72);
    const highs = view.map((c) => c.high);
    const lows = view.map((c) => c.low);
    const max = Math.max(...highs);
    const min = Math.min(...lows);
    const pad = (max - min) * 0.08 || 1;
    const top = max + pad;
    const bot = min - pad;
    const left = w * 0.08;
    const right = w * 0.96;
    const midY = h * 0.42;
    const chartH = h * 0.38;
    const slot = (right - left) / view.length;

    // atmospheric gold wash
    const g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, "rgba(200,162,74,0.05)");
    g.addColorStop(1, "rgba(20,17,15,0.04)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

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

    // subtle scan pulse
    pulse = (pulse + 0.008) % 1;
    const px = left + pulse * (right - left);
    ctx.fillStyle = "rgba(200,162,74,0.12)";
    ctx.fillRect(px, midY - chartH * 0.55, 2, chartH * 1.1);

    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  function biasClass(b) {
    if (b === "buy") return "bias-buy";
    if (b === "sell") return "bias-sell";
    return "bias-neutral";
  }

  function render(data) {
    candles = data.candles_tail || candles;
    const sig = data.signal || {};
    const tick = data.tick || {};
    const acc = data.account || {};
    const risk = data.risk || {};
    const session = ((sig.schools || []).find((s) => s.school.startsWith("Session")) || {}).detail || {};

    $("modePill").textContent = acc.mode || data.mode || "—";
    $("symbolPill").textContent = data.symbol || "XAUUSD";
    $("sessionPill").textContent = session.killzone || "—";
    $("price").textContent = (tick.bid || sig.entry || "—");
    $("conf").textContent = sig.confluence != null ? `${Math.round(sig.confluence * 100)}%` : "—";
    $("action").textContent = sig.action || "—";
    $("action").className = biasClass(sig.action === "flat" ? "neutral" : sig.action);
    $("rr").textContent = sig.reward_risk != null ? sig.reward_risk.toFixed(2) : "—";
    $("equity").textContent = acc.equity != null ? Number(acc.equity).toFixed(2) : "—";
    $("riskState").textContent = risk.halted ? "متوقف" : "نشط";
    $("narrative").textContent = sig.narrative || data.disclaimer || "";
    $("headline").textContent =
      sig.action === "buy" ? "تقارب شراء على الذهب" :
      sig.action === "sell" ? "تقارب بيع على الذهب" :
      "انتظار الانضباط — لا صفقة ضعيفة";

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
      inst.disclaimer || "",
    ].join("\n");

    autoOn = !!data.auto_trade;
    const startBtn = $("btnStart");
    if (startBtn) {
      startBtn.classList.toggle("on", autoOn);
      startBtn.textContent = autoOn ? "المكتب يعمل" : "ابدأ التداول";
    }
  }

  async function loadTrades() {
    const r = await fetch("/api/trades");
    const j = await r.json();
    const ul = $("trades");
    ul.innerHTML = "";
    (j.trades || []).slice(0, 8).forEach((t) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong class="${biasClass(t.side)}">${t.side}</strong> ${t.lot} @ ${t.entry}<span>${t.status} · ${t.mode}</span>`;
      ul.appendChild(li);
    });
    if (!(j.trades || []).length) {
      ul.innerHTML = "<li>لا صفقات بعد — الوضع الآمن أولاً</li>";
    }
  }

  async function refresh() {
    const r = await fetch("/api/status");
    const j = await r.json();
    render(j);
    await loadTrades();
  }

  $("btnScan").onclick = async () => {
    const r = await fetch("/api/scan", { method: "POST" });
    render(await r.json());
    await loadTrades();
  };

  $("btnExec").onclick = async () => {
    const r = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: true }),
    });
    const j = await r.json();
    if (j.scan) render(j.scan);
    else await refresh();
    await loadTrades();
    if (!j.ok) alert(j.error || "تعذّر التنفيذ");
  };

  $("btnStart").onclick = async () => {
    const r = await fetch("/api/start", { method: "POST" });
    const j = await r.json();
    if (j.scan) render(j.scan);
    else await refresh();
    await loadTrades();
    alert(j.message || (j.ok ? "بدأ المكتب" : (j.error || "تعذّر البدء")));
  };

  $("btnStop").onclick = async () => {
    const r = await fetch("/api/stop", { method: "POST" });
    const j = await r.json();
    autoOn = false;
    $("btnStart").classList.remove("on");
    $("btnStart").textContent = "ابدأ التداول";
    alert(j.message || "توقف التلقائي");
  };

  refresh();
  setInterval(refresh, 20000);
})();
