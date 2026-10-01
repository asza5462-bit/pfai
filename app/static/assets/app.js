async function checkHealth() {
  const el = document.getElementById("status");
  if (!el) return;
  try {
    const res = await fetch("/health", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error("unhealthy");
    el.textContent = `يعمل · الإصدار ${data.version} · ${data.service || "local"}`;
    el.classList.add("ok");
  } catch {
    el.textContent = "تعذّر الوصول إلى /health";
    el.classList.add("err");
  }
}

checkHealth();
