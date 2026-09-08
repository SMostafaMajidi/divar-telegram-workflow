const state = { user: null, filters: [], chats: [] };
const userId = location.pathname.split("/").filter(Boolean).pop();

const els = {
  title: $("#page-title"),
  head: $("#user-head"),
  profile: $("#profile-form"),
  poll: $("#poll-form"),
  route: $("#route-form"),
  routeFilter: $("#route-filter"),
  routeChat: $("#route-chat"),
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

function chatNameFor(chatId) {
  const privateId = state.user?.telegram_chat_id || "";
  if (!chatId || (privateId && String(chatId) === String(privateId))) return "چت شخصی (پیش‌فرض)";
  const found = state.chats.find((c) => String(c.id) === String(chatId));
  return found ? chatLabel(found) : chatId;
}

function renderRoutes() {
  const privateId = state.user?.telegram_chat_id || "";
  fillSelect(els.routeFilter, state.filters, {
    emptyLabel: state.filters.length ? "انتخاب فیلتر" : "فیلتری نیست",
    labelFn: (f) => f.name || f.id,
  });
  fillSelect(els.routeChat, state.chats, {
    emptyLabel: "چت شخصی (پیش‌فرض)",
    labelFn: chatLabel,
    skipIds: [privateId],
  });
  els.routeList.replaceChildren();
  if (!state.filters.length) {
    els.routeList.append(
      Object.assign(document.createElement("p"), {
        className: "meta",
        textContent: "هنوز فیلتری برای این مشتری نیست.",
      }),
    );
    return;
  }
  for (const filter of state.filters) {
    const row = document.createElement("div");
    row.className = "route-row";
    row.innerHTML = `<strong>${filter.name || filter.id}</strong><span>${chatNameFor(filter.chat_id)}</span>`;
    els.routeList.append(row);
  }
}

function render() {
  const user = state.user;
  if (!user) return;
  const handle = user.login_username || user.telegram_username || user.id;
  els.title.textContent = `@${handle}`;
  document.title = `@${handle} — ادمین`;
  els.head.innerHTML = `
    <div class="card-top">
      <div>
        <p class="meta">${user.display_name || ""} · تلگرام: @${user.telegram_username || "—"}</p>
        <p class="meta">${user.filter_count || state.filters.length || 0} فیلتر · ساخته‌شده: ${(user.created_at || "").slice(0, 10)}</p>
      </div>
      <div class="row">
        <span class="pill ${user.linked ? "ok" : "warn"}">${user.linked ? "متصل" : "منتظر ربات"}</span>
        <span class="pill ${user.active ? "ok" : ""}">${user.active ? "فعال" : "غیرفعال"}</span>
      </div>
    </div>
  `;
  els.profile.display_name.value = user.display_name || "";
  els.profile.ai_enabled.checked = !!user.ai_enabled;
  els.profile.active.checked = !!user.active;
  els.poll.poll_interval_minutes.value =
    user.poll_interval_minutes ?? user.effective_poll_interval_minutes ?? 5;
  els.poll.poll_offset_minutes.value = user.poll_offset_minutes ?? user.effective_poll_offset_minutes ?? 0;
  els.poll.best_count.value = user.best_count ?? user.effective_best_count ?? 5;
  els.slotHint.textContent = slotHint(user);
  els.feed.href = `/u/${user.public_slug || user.login_username || user.telegram_username}`;
  els.apiKey.textContent = user.api_key ? `API key: ${user.api_key}` : "";
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
    toast("اطلاعات ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

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
    toast("زمان پایه نامعتبر است", "err");
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

els.route.addEventListener("submit", async (e) => {
  e.preventDefault();
  const filterId = els.routeFilter.value;
  if (!filterId) {
    toast("یک فیلتر انتخاب کنید", "err");
    return;
  }
  try {
    const data = await api(`/api/admin/users/${userId}/filters/${filterId}/chat`, {
      method: "POST",
      body: { chat_id: els.routeChat.value || "" },
    });
    const i = state.filters.findIndex((f) => f.id === data.filter.id);
    if (i >= 0) state.filters[i] = data.filter;
    renderRoutes();
    toast("مقصد فیلتر ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.routeFilter.addEventListener("change", () => {
  const filter = state.filters.find((f) => f.id === els.routeFilter.value);
  const privateId = state.user?.telegram_chat_id || "";
  const selected =
    filter?.chat_id && privateId && String(filter.chat_id) === String(privateId)
      ? ""
      : filter?.chat_id || "";
  fillSelect(els.routeChat, state.chats, {
    emptyLabel: "چت شخصی (پیش‌فرض)",
    labelFn: chatLabel,
    skipIds: [privateId],
    selected,
  });
});

els.refreshChats.onclick = async () => {
  try {
    await loadRoutes();
    toast(state.chats.length ? `${state.chats.length} چت` : "چتی ثبت نشده؛ در ربات/گروه پیام بفرستید", "ok");
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
  if (!userId) {
    toast("شناسه مشتری نامعتبر است", "err");
    return;
  }
  try {
    const data = await api(`/api/admin/users/${userId}`);
    state.user = data.user;
    await loadRoutes();
    render();
  } catch (err) {
    toast(err.message, "err");
  }
}

boot();
