const state = { users: [], status: {} };

const els = {
  list: $("#user-list"),
  count: $("#user-count"),
  create: $("#create-form"),
  toggleCreate: $("#toggle-create"),
  cancelCreate: $("#cancel-create"),
};

function renderUsers() {
  els.list.replaceChildren();
  els.count.textContent = state.users.length ? `(${state.users.length})` : "";
  if (!state.users.length) {
    els.list.append(
      Object.assign(document.createElement("p"), {
        className: "empty",
        textContent: "مشتری‌ای ثبت نشده.",
      }),
    );
    return;
  }
  for (const user of state.users) {
    const row = document.createElement("a");
    row.className = `user-summary ${user.active ? "" : "off"}`;
    row.href = `/admin/users/${user.id}`;
    const interval = user.effective_poll_interval_minutes || 5;
    const offset = user.effective_poll_offset_minutes ?? 0;
    const name = (user.display_name || "").trim() || "بدون نام";
    row.innerHTML = `
      <div class="user-summary-main">
        <strong>${name}</strong>
        <span class="meta">${user.filter_count || 0} فیلتر · ${user.plan_name || user.plan_id || "—"}</span>
      </div>
      <div class="user-summary-side">
        <span class="pill ${user.linked ? "ok" : "warn"}">${user.linked ? "متصل" : "منتظر"}</span>
        <span class="pill ${user.subscription_status === "expired" ? "warn" : user.active ? "ok" : ""}">${user.subscription_status || (user.active ? "فعال" : "غیرفعال")}</span>
        <span class="slot-chip">${interval}د / پایه ${offset}</span>
      </div>
    `;
    els.list.append(row);
  }
}

els.toggleCreate.onclick = () => {
  els.create.hidden = !els.create.hidden;
  if (!els.create.hidden) els.create.telegram_username.focus();
};

els.cancelCreate.onclick = () => {
  els.create.reset();
  els.create.hidden = true;
};

els.create.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = new FormData(els.create);
  try {
    const res = await api("/api/admin/users", {
      method: "POST",
      body: {
        telegram_username: data.get("telegram_username"),
        display_name: data.get("display_name"),
        ai_enabled: els.create.ai_enabled.checked,
      },
    });
    state.users.unshift(res.user);
    renderUsers();
    els.create.reset();
    els.create.hidden = true;
    toast("مشتری ساخته شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

const broadcastForm = $("#broadcast-form");
const broadcastText = $("#broadcast-text");
const broadcastScope = $("#broadcast-scope");
const broadcastChannels = $("#broadcast-channels");
const broadcastHint = $("#broadcast-hint");

function broadcastPayload(extra = {}) {
  const channel = broadcastChannels?.value || "";
  return {
    text: broadcastText?.value || "",
    scope: broadcastScope?.value || "private",
    channels: channel ? [channel] : null,
    ...extra,
  };
}

$("#broadcast-preview")?.addEventListener("click", async () => {
  try {
    const data = await api("/api/admin/broadcast", {
      method: "POST",
      body: broadcastPayload({ dry_run: true }),
    });
    const by = {};
    for (const t of data.targets || []) {
      by[t.channel] = (by[t.channel] || 0) + 1;
    }
    const parts = Object.entries(by).map(([ch, n]) => `${ch}: ${n}`);
    if (broadcastHint) {
      broadcastHint.textContent = `مقصدها: ${data.total || 0}` + (parts.length ? ` (${parts.join(" · ")})` : "");
    }
    toast(`آماده ارسال به ${data.total || 0} مقصد`, "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

$("#broadcast-bale-preset")?.addEventListener("click", async () => {
  try {
    const data = await api("/api/admin/broadcast", {
      method: "POST",
      body: { preset: "bale_announcement", dry_run: true },
    });
    if (broadcastText && data.text) broadcastText.value = data.text;
    toast("متن آماده بله گذاشته شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

broadcastForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!confirm("پیام گروهی برای مقصدهای انتخاب‌شده ارسال شود؟")) return;
  const btn = broadcastForm.querySelector('button[type="submit"]');
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/admin/broadcast", {
      method: "POST",
      body: broadcastPayload(),
    });
    if (broadcastHint) broadcastHint.textContent = data.message || "";
    toast(data.message || "ارسال شد", data.failed ? "err" : "ok");
  } catch (err) {
    toast(err.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
});

async function boot() {
  bindLogout();
  try {
    const [users, status] = await Promise.all([
      api("/api/admin/users"),
      fetch("/api/status", { credentials: "same-origin" }).then((r) => r.json()),
    ]);
    state.users = users.users || [];
    state.status = status;
    bindWatchControls(state);
    renderUsers();
  } catch (err) {
    if (!String(err.message).includes("ورود")) toast(err.message, "err");
  }
}

boot();
