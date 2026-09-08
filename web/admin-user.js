const state = { user: null, filters: [], chats: [], plans: [] };
const userId = location.pathname.split("/").filter(Boolean).pop();

const els = {
  title: $("#page-title"),
  head: $("#user-head"),
  tabs: $("#user-tabs"),
  profile: $("#profile-form"),
  plan: $("#plan-form"),
  planStatus: $("#plan-status"),
  planId: $("#plan-id"),
  poll: $("#poll-form"),
  routesPanel: $("#routes-panel"),
  routeList: $("#route-list"),
  refreshChats: $("#refresh-chats-btn"),
  slotHint: $("#slot-hint"),
  rotate: $("#rotate-btn"),
  feed: $("#feed-link"),
  apiKey: $("#api-key"),
  deleteBtn: $("#delete-btn"),
};

function chatLabel(chat) {
  const kinds = { private: "خصوصی", group: "گروه", supergroup: "گروه", channel: "کانال" };
  const kind = kinds[chat.type] || "";
  const name = chat.name || (chat.username ? `@${chat.username}` : chat.id);
  return kind ? `${name} · ${kind}` : String(name);
}

function parseExpiryInput(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    return fromJalaliInput(raw);
  } catch (err) {
    if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
      return raw.includes("T") ? raw : `${raw}T23:59:59+03:30`;
    }
    throw err;
  }
}

function fillSelect(select, items, { valueKey = "id", labelFn, emptyLabel, selected, skipIds = [] } = {}) {
  const skipped = new Set((skipIds || []).map(String).filter(Boolean));
  select.replaceChildren();
  if (emptyLabel != null) {
    select.append(Object.assign(document.createElement("option"), { value: "", textContent: emptyLabel }));
  }
  for (const item of items) {
    const value = String(item[valueKey] ?? "");
    if (skipped.has(value)) continue;
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = labelFn ? labelFn(item) : value;
    select.append(opt);
  }
  let selectedValue = selected != null ? String(selected) : "";
  if (selectedValue && skipped.has(selectedValue)) selectedValue = "";
  if (selectedValue && ![...select.options].some((o) => o.value === selectedValue)) {
    const opt = document.createElement("option");
    opt.value = selectedValue;
    opt.textContent = selectedValue;
    select.append(opt);
  }
  select.value = selectedValue;
}

function setTab(name) {
  const tab = name || "account";
  els.tabs.querySelectorAll(".seg-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== tab;
  });
  try {
    history.replaceState(null, "", `#${tab}`);
  } catch (_) {
    /* ignore */
  }
}

function renderRoutes() {
  const privateId = state.user?.telegram_chat_id || "";
  els.routeList.replaceChildren();
  if (!state.filters.length) {
    els.routeList.append(
      Object.assign(document.createElement("p"), {
        className: "empty",
        textContent: "هنوز فیلتری برای این مشتری نیست.",
      }),
    );
    return;
  }
  for (const filter of state.filters) {
    const select = document.createElement("select");
    fillSelect(select, state.chats, {
      emptyLabel: "چت شخصی (پیش‌فرض)",
      labelFn: chatLabel,
      skipIds: [privateId],
      selected:
        filter.chat_id && privateId && String(filter.chat_id) === String(privateId)
          ? ""
          : filter.chat_id || "",
    });
    select.addEventListener("change", async () => {
      try {
        const data = await api(`/api/admin/users/${userId}/filters/${filter.id}/chat`, {
          method: "POST",
          body: { chat_id: select.value || "" },
        });
        const i = state.filters.findIndex((f) => f.id === data.filter.id);
        if (i >= 0) state.filters[i] = data.filter;
        toast("مقصد ذخیره شد", "ok");
      } catch (err) {
        toast(err.message, "err");
        renderRoutes();
      }
    });

    const row = document.createElement("article");
    row.className = "route-card";
    const title = document.createElement("strong");
    title.textContent = filter.name || filter.id;
    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = filter.enabled ? "فعال" : "غیرفعال";
    const label = document.createElement("label");
    label.className = "chat-target";
    label.append("ارسال به", select);
    row.append(title, meta, label);
    els.routeList.append(row);
  }
}

function render() {
  const user = state.user;
  if (!user) return;
  const handle = user.login_username || user.telegram_username || user.id;
  const name = (user.display_name || "").trim() || "بدون نام";
  els.title.textContent = name;
  document.title = `${name} — ادمین`;

  const filterCount = user.filter_count || state.filters.length || 0;
  const exp = user.expires_at ? formatJalali(user.expires_at) : "—";
  els.head.innerHTML = `
    <div class="user-hero-main">
      <div>
        <p class="eyebrow">مشتری</p>
        <h2>${name}</h2>
        <p class="meta">یوزرنیم: @${handle}${user.telegram_username && user.telegram_username !== handle ? ` · تلگرام @${user.telegram_username}` : ""}</p>
      </div>
      <div class="user-hero-pills">
        <span class="pill ${user.linked ? "ok" : "warn"}">${user.linked ? "متصل" : "منتظر ربات"}</span>
        <span class="pill ${user.active ? "ok" : ""}">${user.active ? "فعال" : "غیرفعال"}</span>
        <span class="pill ${user.subscription_status === "expired" ? "warn" : "ok"}">${user.plan_name || user.plan_id || "—"}</span>
      </div>
    </div>
    <dl class="user-hero-stats">
      <div><dt>فیلتر</dt><dd>${filterCount}</dd></div>
      <div><dt>سقف</dt><dd>${user.effective_max_filters ?? "—"}</dd></div>
      <div><dt>انقضا</dt><dd>${exp}</dd></div>
      <div><dt>عضویت</dt><dd>${formatJalali(user.created_at)}</dd></div>
    </dl>
  `;

  els.profile.display_name.value = user.display_name || "";
  els.profile.ai_enabled.checked = !!user.ai_enabled;
  els.profile.active.checked = !!user.active;

  if (els.plan) {
    fillSelect(els.planId, state.plans, {
      labelFn: (p) => `${p.name} — تا ${p.max_filters} فیلتر`,
      selected: user.plan_id || "trial",
    });
    els.plan.max_filters.value = user.max_filters ?? "";
    els.plan.expires_at.value = toJalaliInput(user.expires_at);
    els.planStatus.textContent =
      `${user.subscription_status || "—"} · سقف مؤثر ${user.effective_max_filters ?? "—"}` +
      (user.expires_at ? ` · تا ${formatJalali(user.expires_at)}` : "");
  }

  els.poll.poll_interval_minutes.value =
    user.poll_interval_minutes ?? user.effective_poll_interval_minutes ?? 5;
  els.poll.poll_offset_minutes.value = user.poll_offset_minutes ?? user.effective_poll_offset_minutes ?? 0;
  els.poll.best_count.value = user.best_count ?? user.effective_best_count ?? 5;
  els.slotHint.textContent = slotHint(user);
  els.feed.href = `/u/${user.public_slug || user.login_username || user.telegram_username}`;
  els.apiKey.textContent = user.api_key ? `API key: ${user.api_key}` : "کلید API هنوز ساخته نشده.";
  renderRoutes();
}

async function loadRoutes() {
  const [filters, chats] = await Promise.all([
    api(`/api/admin/users/${userId}/filters`),
    api(`/api/admin/users/${userId}/chats`),
  ]);
  state.filters = filters.filters || [];
  state.chats = chats.chats || [];
  renderRoutes();
}

els.tabs?.addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-tab");
  if (!btn) return;
  setTab(btn.dataset.tab);
});

els.profile.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const data = await api(`/api/admin/users/${userId}`, {
      method: "PUT",
      body: {
        display_name: els.profile.display_name.value,
        ai_enabled: els.profile.ai_enabled.checked,
        active: els.profile.active.checked,
      },
    });
    state.user = data.user;
    render();
    toast("حساب ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

if (els.plan) {
  els.plan.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const renew = els.plan.renew.checked;
      const body = {
        apply_plan: true,
        plan_id: els.planId.value || "trial",
        renew,
        apply_limits: els.plan.apply_limits.checked,
        max_filters: optionalNumber(els.plan.max_filters.value),
      };
      if (!renew) body.expires_at = parseExpiryInput(els.plan.expires_at.value);
      const data = await api(`/api/admin/users/${userId}`, { method: "PUT", body });
      // Keep max_filters override if set after plan apply
      if (body.max_filters != null) {
        const again = await api(`/api/admin/users/${userId}`, {
          method: "PUT",
          body: { max_filters: body.max_filters },
        });
        state.user = again.user;
      } else {
        state.user = data.user;
      }
      render();
      toast("اشتراک ذخیره شد", "ok");
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

els.poll.addEventListener("submit", async (e) => {
  e.preventDefault();
  const interval = optionalNumber(els.poll.poll_interval_minutes.value);
  const offset = optionalNumber(els.poll.poll_offset_minutes.value);
  const best = optionalNumber(els.poll.best_count.value);
  if (interval == null || interval < 1) {
    toast("فاصله پایش را وارد کنید", "err");
    return;
  }
  if (offset == null || offset < 0) {
    toast("آفست نامعتبر است", "err");
    return;
  }
  if (best == null || best < 1) {
    toast("تعداد آگهی برتر را وارد کنید", "err");
    return;
  }
  try {
    const data = await api(`/api/admin/users/${userId}`, {
      method: "PUT",
      body: {
        poll_interval_minutes: interval,
        poll_offset_minutes: offset,
        best_count: best,
      },
    });
    state.user = data.user;
    render();
    toast(`پایش ذخیره شد — ${(data.user.slot_preview || []).join("، ")}`, "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.refreshChats.onclick = async () => {
  try {
    await loadRoutes();
    toast(state.chats.length ? `${state.chats.length} چت` : "چتی نیست؛ در ربات/گروه پیام بفرستید", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
};

els.rotate.onclick = async () => {
  if (!confirm("کلید API جدید ساخته شود؟ کلید قبلی از کار می‌افتد.")) return;
  try {
    const data = await api(`/api/admin/users/${userId}/rotate-key`, { method: "POST", body: {} });
    state.user = data.user;
    render();
    toast("کلید جدید ساخته شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
};

els.deleteBtn.onclick = async () => {
  const handle = state.user?.login_username || state.user?.telegram_username || userId;
  if (!confirm(`حساب @${handle} کامل حذف شود؟ این کار برگشت‌پذیر نیست.`)) return;
  if (!confirm("مطمئن هستید؟ فیلترها و داده‌های این مشتری پاک می‌شود.")) return;
  try {
    await api(`/api/admin/users/${userId}`, { method: "DELETE" });
    toast("حساب حذف شد", "ok");
    setTimeout(() => {
      location.href = "/admin";
    }, 600);
  } catch (err) {
    toast(err.message, "err");
  }
};

async function boot() {
  bindLogout();
  bindJalaliPickers();
  const initial = (location.hash || "").replace("#", "") || "account";
  setTab(["account", "plan", "poll", "routes", "more"].includes(initial) ? initial : "account");
  if (!userId) {
    toast("شناسه مشتری نامعتبر است", "err");
    return;
  }
  try {
    const [data, plans] = await Promise.all([
      api(`/api/admin/users/${userId}`),
      fetch("/api/plans").then((r) => r.json()),
    ]);
    state.user = data.user;
    state.plans = plans.plans || [];
    await loadRoutes();
    render();
  } catch (err) {
    toast(err.message, "err");
  }
}

els.plan?.expires_at?.addEventListener("change", () => {
  if (els.plan.expires_at.value) els.plan.renew.checked = false;
});

boot();
