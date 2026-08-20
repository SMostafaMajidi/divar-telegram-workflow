const $ = (sel, root = document) => root.querySelector(sel);

const state = { users: [], status: {} };

const els = {
  list: $("#user-list"),
  create: $("#create-form"),
  settings: $("#settings-form"),
  toast: $("#toast"),
  watchBtn: $("#watch-btn"),
  watchPill: $("#watch-pill"),
  logoutBtn: $("#logout-btn"),
};

function toast(message, kind = "") {
  els.toast.hidden = !message;
  els.toast.className = `toast ${kind}`.trim();
  els.toast.textContent = message || "";
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

function renderUsers() {
  els.list.replaceChildren();
  if (!state.users.length) {
    els.list.append(Object.assign(document.createElement("p"), { className: "empty", textContent: "مشتری‌ای ثبت نشده." }));
    return;
  }
  for (const user of state.users) {
    const card = document.createElement("article");
    card.className = `card ${user.active ? "" : "off"}`;
    card.innerHTML = `
      <div class="card-top">
        <h3>@${user.login_username || user.telegram_username}</h3>
        <span class="pill ${user.linked ? "ok" : "warn"}">${user.linked ? "متصل" : "منتظر ربات"}</span>
      </div>
      <p class="meta">${user.display_name || ""} · تلگرام: @${user.telegram_username || "—"}</p>
      <div class="card-actions"></div>
    `;
    const actions = card.querySelector(".card-actions");
    const ai = document.createElement("label");
    ai.className = "check";
    ai.innerHTML = `<input type="checkbox" ${user.ai_enabled ? "checked" : ""}> هوش مصنوعی`;
    ai.querySelector("input").onchange = async (e) => {
      try {
        const data = await api(`/api/admin/users/${user.id}`, { method: "PUT", body: { ai_enabled: e.target.checked } });
        replaceUser(data.user);
        toast("ذخیره شد", "ok");
      } catch (err) {
        toast(err.message, "err");
      }
    };
    const active = document.createElement("label");
    active.className = "check";
    active.innerHTML = `<input type="checkbox" ${user.active ? "checked" : ""}> فعال`;
    active.querySelector("input").onchange = async (e) => {
      try {
        const data = await api(`/api/admin/users/${user.id}`, { method: "PUT", body: { active: e.target.checked } });
        replaceUser(data.user);
        toast("ذخیره شد", "ok");
      } catch (err) {
        toast(err.message, "err");
      }
    };
    const rotate = document.createElement("button");
    rotate.className = "ghost small";
    rotate.type = "button";
    rotate.textContent = "کلید API جدید";
    rotate.onclick = async () => {
      try {
        const data = await api(`/api/admin/users/${user.id}/rotate-key`, { method: "POST", body: {} });
        replaceUser(data.user);
        toast("کلید جدید ساخته شد", "ok");
      } catch (err) {
        toast(err.message, "err");
      }
    };
    const feed = document.createElement("a");
    feed.className = "ghost small";
    feed.href = `/u/${user.public_slug || user.login_username || user.telegram_username}`;
    feed.target = "_blank";
    feed.textContent = "فید عمومی";
    actions.append(ai, active, rotate, feed);
    els.list.append(card);
  }
}

function replaceUser(updated) {
  const i = state.users.findIndex((u) => u.id === updated.id);
  if (i >= 0) state.users[i] = updated;
  else state.users.unshift(updated);
  renderUsers();
}

function renderStatus() {
  els.watchPill.textContent = state.status.watching ? "پایش روشن" : "پایش خاموش";
  els.watchPill.className = `pill ${state.status.watching ? "ok" : ""}`;
  els.watchBtn.textContent = state.status.watching ? "توقف پایش" : "شروع پایش";
  els.settings.poll_interval_minutes.value = state.status.poll_interval_minutes || 30;
  els.settings.best_count.value = state.status.best_count || 5;
  els.settings.send_photos.checked = !!state.status.send_photos;
}

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
    replaceUser(res.user);
    els.create.reset();
    toast("مشتری ساخته شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.settings.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    state.status = await api("/api/settings", {
      method: "PUT",
      body: {
        poll_interval_minutes: Number(els.settings.poll_interval_minutes.value),
        best_count: Number(els.settings.best_count.value),
        send_photos: els.settings.send_photos.checked,
      },
    });
    renderStatus();
    toast("تنظیمات ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.watchBtn.onclick = async () => {
  try {
    const action = state.status.watching ? "stop" : "start";
    const data = await api("/api/watch", { method: "POST", body: { action } });
    state.status.watching = data.watching;
    renderStatus();
    toast(data.watching ? "پایش روشن شد" : "پایش متوقف شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
};

els.logoutBtn.onclick = async () => {
  await fetch("/api/admin/logout", { method: "POST", credentials: "same-origin" });
  location.href = "/admin/login";
};

async function boot() {
  try {
    const [users, status] = await Promise.all([
      api("/api/admin/users"),
      fetch("/api/status").then((r) => r.json()),
    ]);
    state.users = users.users || [];
    state.status = status;
    renderUsers();
    renderStatus();
  } catch (err) {
    if (!String(err.message).includes("ورود")) toast(err.message, "err");
  }
}

boot();
