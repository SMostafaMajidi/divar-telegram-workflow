const $ = (sel, root = document) => root.querySelector(sel);

function toast(message, kind = "") {
  const el = $("#toast");
  if (!el) return;
  el.hidden = !message;
  el.className = `toast ${kind}`.trim();
  el.textContent = message || "";
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401) {
    location.href = "/admin/login";
    throw new Error("نیاز به ورود");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "خطا");
  return data;
}

function optionalNumber(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function slotHint(user) {
  const slots = user.slot_preview || [];
  if (!slots.length) return "";
  const interval = user.effective_poll_interval_minutes || 5;
  const offset = user.effective_poll_offset_minutes ?? 0;
  return `هر ${interval} دقیقه از دقیقهٔ ${offset} → اسلات‌ها: ${slots.join("، ")}، …`;
}

function bindWatchControls(state) {
  const pill = $("#watch-pill");
  const btn = $("#watch-btn");
  if (!pill || !btn) return;
  const render = () => {
    pill.textContent = state.status.watching ? "پایش روشن" : "پایش خاموش";
    pill.className = `pill ${state.status.watching ? "ok" : ""}`;
    btn.textContent = state.status.watching ? "توقف پایش" : "شروع پایش";
  };
  render();
  btn.onclick = async () => {
    try {
      const action = state.status.watching ? "stop" : "start";
      const data = await api("/api/watch", { method: "POST", body: { action } });
      state.status.watching = data.watching;
      render();
      toast(data.watching ? "پایش روشن شد" : "پایش متوقف شد", "ok");
    } catch (err) {
      toast(err.message, "err");
    }
  };
}

function bindLogout() {
  const btn = $("#logout-btn");
  if (!btn) return;
  btn.onclick = async () => {
    await fetch("/api/admin/logout", { method: "POST", credentials: "same-origin" });
    location.href = "/admin/login";
  };
}

if (typeof bindNavMenus === "function") {
  bindNavMenus();
} else {
  document.addEventListener("DOMContentLoaded", () => {
    if (typeof bindNavMenus === "function") bindNavMenus();
  });
}
