const state = { user: null, filters: [], chats: [], plans: [], invoices: [], watchEvents: [], tickets: [], activeTicket: null };
const userId = location.pathname.split("/").filter(Boolean).pop();

const INVOICE_STATUS = {
  pending: "در انتظار پرداخت",
  awaiting_review: "در صف تأیید",
  paid: "پرداخت‌شده",
  rejected: "رد شده",
  cancelled: "لغو شده",
};

const WATCH_ACTION = { scan: "جستجو", deliver: "ارسال" };
const WATCH_STATUS = {
  success: "موفق",
  failure: "ناموفق",
  partial: "جزئی",
  skipped: "رد شده",
};
const WATCH_CHANNEL = { telegram: "تلگرام", bale: "بله", email: "ایمیل", sms: "پیامک" };
const CHANNEL_LABELS = { telegram: "تلگرام", bale: "بله", eitaa: "ایتا" };
const WATCH_PLATFORM = { divar: "دیوار" };

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
  paymentList: $("#payment-list"),
  refreshPayments: $("#refresh-payments-btn"),
  watchList: $("#watch-list"),
  refreshWatch: $("#refresh-watch-btn"),
  ticketList: $("#admin-ticket-list"),
  ticketThread: $("#admin-ticket-thread"),
  ticketForm: $("#admin-ticket-form"),
  ticketId: $("#admin-ticket-id"),
  ticketSubject: $("#admin-ticket-subject"),
  ticketSubjectWrap: $("#admin-ticket-subject-wrap"),
  ticketBody: $("#admin-ticket-body"),
  ticketCloseBtn: $("#admin-ticket-close-btn"),
  refreshTickets: $("#refresh-tickets-btn"),
  slotHint: $("#slot-hint"),
  rotate: $("#rotate-btn"),
  feed: $("#feed-link"),
  apiKey: $("#api-key"),
  deleteBtn: $("#delete-btn"),
  eitaaStatus: $("#admin-eitaa-status"),
  eitaaToken: $("#admin-eitaa-token"),
  eitaaSave: $("#admin-eitaa-save"),
  eitaaClear: $("#admin-eitaa-clear"),
  eitaaChannel: $("#admin-eitaa-channel"),
  eitaaChannelAdd: $("#admin-eitaa-channel-add"),
  eitaaChannels: $("#admin-eitaa-channels"),
  platformsCaps: $("#platforms-caps"),
  platformsLinks: $("#platforms-links"),
};

function chatLabel(chat) {
  const kinds = { private: "خصوصی", group: "گروه", supergroup: "گروه", channel: "کانال" };
  const kind = kinds[chat.type] || "";
  const channel = CHANNEL_LABELS[chat.channel] || chat.channel || "";
  const name = chat.name || (chat.username ? `@${chat.username}` : chat.id);
  const base = kind ? `${name} · ${kind}` : String(name);
  return channel ? `${channel} · ${base}` : base;
}

function formatDestinations(filter) {
  const dests = filter.destinations || [];
  if (!dests.length) {
    return filter.chat_id
      ? chatLabel({ id: filter.chat_id, channel: "telegram", type: "private" })
      : "بدون مقصد";
  }
  return dests
    .map((d) => {
      const chat = state.chats.find(
        (c) =>
          (c.channel || "telegram") === (d.channel || "telegram") &&
          String(c.id) === String(d.chat_id),
      );
      return chat
        ? chatLabel(chat)
        : `${CHANNEL_LABELS[d.channel] || d.channel} · ${d.chat_id}`;
    })
    .join(" · ");
}

function priceText(filter) {
  const min = filter.price_min_million;
  const max = filter.price_max_million;
  if (min == null && max == null) return "بدون محدودیت قیمت";
  if (min != null && max != null) return `${min} تا ${max} میلیون`;
  if (min != null) return `از ${min} میلیون`;
  return `تا ${max} میلیون`;
}

function formatFieldValue(value) {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "بله" : "خیر";
  if (Array.isArray(value)) return value.length ? value.map(String).join("، ") : "—";
  if (typeof value === "object") {
    const min = value.min ?? value.minimum ?? value.from;
    const max = value.max ?? value.maximum ?? value.to;
    if (min != null || max != null) {
      if (min != null && max != null) return `${min} تا ${max}`;
      if (min != null) return `از ${min}`;
      return `تا ${max}`;
    }
    try {
      return JSON.stringify(value);
    } catch (_) {
      return String(value);
    }
  }
  return String(value);
}

function fieldLabel(key) {
  const map = {
    price: "قیمت",
    year: "سال",
    mileage: "کارکرد",
    chassis_status: "وضعیت شاسی",
    body_status: "وضعیت بدنه",
    color: "رنگ",
    brand_model: "برند/مدل",
    motor_status: "وضعیت موتور",
  };
  return map[key] || key;
}

function filterDetailRows(filter) {
  const rows = [
    ["وضعیت", filter.enabled ? "فعال" : "غیرفعال"],
    ["دسته", filter.category_path || filter.category_name || filter.category || "—"],
    ["عبارت جستجو", filter.query || "—"],
    ["شهرها", (filter.cities || []).join("، ") || "—"],
    ["قیمت", priceText(filter)],
    ["حذف از عنوان", (filter.exclude_title || []).join("، ") || "—"],
    ["صفحات جستجو", filter.max_pages != null ? String(filter.max_pages) : "—"],
  ];
  const fields = filter.fields && typeof filter.fields === "object" ? filter.fields : {};
  for (const [key, value] of Object.entries(fields)) {
    if (key === "price") continue; // already shown via price_min/max
    const text = formatFieldValue(value);
    if (text === "—") continue;
    rows.push([fieldLabel(key), text]);
  }
  return rows;
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
    fillSelect(select, state.chats.filter((c) => (c.channel || "telegram") === "telegram"), {
      emptyLabel: "چت شخصی تلگرام (پیش‌فرض)",
      labelFn: chatLabel,
      skipIds: [privateId],
      selected:
        filter.chat_id && privateId && String(filter.chat_id) === String(privateId)
          ? ""
          : filter.chat_id || "",
    });
    select.addEventListener("change", async () => {
      try {
        const destinations = select.value
          ? [{ channel: "telegram", chat_id: select.value, enabled: true }]
          : privateId
            ? [{ channel: "telegram", chat_id: privateId, enabled: true }]
            : [];
        const data = await api(`/api/admin/users/${userId}/filters/${filter.id}/destinations`, {
          method: "POST",
          body: { destinations },
        });
        const i = state.filters.findIndex((f) => f.id === data.filter.id);
        if (i >= 0) state.filters[i] = data.filter;
        toast("مقصد ذخیره شد", "ok");
        renderRoutes();
      } catch (err) {
        toast(err.message, "err");
        renderRoutes();
      }
    });

    const row = document.createElement("article");
    row.className = `route-card filter-detail-card ${filter.enabled ? "" : "off"}`;

    const head = document.createElement("div");
    head.className = "card-top";
    const title = document.createElement("strong");
    title.textContent = filter.name || filter.id;
    const pill = document.createElement("span");
    pill.className = `pill ${filter.enabled ? "ok" : "warn"}`;
    pill.textContent = filter.enabled ? "فعال" : "غیرفعال";
    head.append(title, pill);

    const dl = document.createElement("dl");
    dl.className = "filter-detail-grid";
    for (const [labelText, valueText] of filterDetailRows(filter)) {
      const item = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = labelText;
      const dd = document.createElement("dd");
      dd.textContent = valueText;
      item.append(dt, dd);
      dl.append(item);
    }

    const destMeta = document.createElement("p");
    destMeta.className = "meta";
    destMeta.textContent = `مقصدها: ${formatDestinations(filter)}`;

    const label = document.createElement("label");
    label.className = "chat-target";
    label.append("مقصد تلگرام (سریع)", select);

    const idMeta = document.createElement("p");
    idMeta.className = "meta mono";
    idMeta.textContent = `شناسه فیلتر: ${filter.id}`;

    row.append(head, dl, destMeta, label, idMeta);
    els.routeList.append(row);
  }
}

function renderPayments() {
  if (!els.paymentList) return;
  els.paymentList.replaceChildren();
  if (!state.invoices.length) {
    els.paymentList.append(
      Object.assign(document.createElement("p"), {
        className: "empty",
        textContent: "سابقه پرداختی برای این مشتری نیست.",
      }),
    );
    return;
  }
  for (const inv of state.invoices) {
    const card = document.createElement("article");
    card.className = "invoice-card";
    const canAct = inv.status === "pending" || inv.status === "awaiting_review";
    const receipt = inv.has_receipt
      ? `<p class="meta"><a class="ghost small" href="/api/invoices/${inv.id}/receipt" target="_blank" rel="noreferrer">مشاهده فیش</a>${inv.receipt_name ? ` · ${inv.receipt_name}` : ""}</p>`
      : `<p class="meta">فیش آپلود نشده</p>`;
    const actions = canAct
      ? `<div class="row">
          <button class="primary small" type="button" data-confirm="${inv.id}" ${inv.has_receipt ? "" : "disabled"}>تأیید و فعال‌سازی</button>
          <button class="ghost small" type="button" data-reject="${inv.id}">رد</button>
        </div>`
      : "";
    card.innerHTML = `
      <div class="card-top">
        <div>
          <h3>${inv.plan_name || inv.plan_id}</h3>
          <p class="meta">${inv.amount_label} · شناسه <b dir="ltr">${inv.ref_code}</b></p>
          <p class="meta">توضیح: ${inv.payer_note || "—"}</p>
          <p class="meta">${typeof formatJalali === "function" ? formatJalali(inv.created_at, { withTime: true }) : inv.created_at || ""}</p>
        </div>
        <span class="pill ${inv.status === "paid" ? "ok" : inv.status === "rejected" ? "warn" : inv.status === "awaiting_review" ? "warn" : ""}">${INVOICE_STATUS[inv.status] || inv.status}</span>
      </div>
      ${receipt}
      ${actions}
    `;
    els.paymentList.append(card);
  }
  els.paymentList.querySelectorAll("[data-confirm]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("پرداخت تأیید شود و حساب با انقضای پلن فعال گردد؟")) return;
      try {
        const data = await api(`/api/admin/invoices/${btn.dataset.confirm}/confirm`, {
          method: "POST",
          body: {},
        });
        if (data.user) state.user = data.user;
        toast("پرداخت تأیید شد", "ok");
        await loadPayments();
        render();
      } catch (err) {
        toast(err.message, "err");
      }
    };
  });
  els.paymentList.querySelectorAll("[data-reject]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("فاکتور رد شود؟")) return;
      try {
        await api(`/api/admin/invoices/${btn.dataset.reject}/reject`, { method: "POST", body: {} });
        toast("رد شد", "ok");
        await loadPayments();
      } catch (err) {
        toast(err.message, "err");
      }
    };
  });
}

function renderWatchLog() {
  if (!els.watchList) return;
  els.watchList.replaceChildren();
  if (!state.watchEvents.length) {
    els.watchList.append(
      Object.assign(document.createElement("p"), {
        className: "empty",
        textContent: "هنوز رویدادی از پایش ثبت نشده.",
      }),
    );
    return;
  }
  for (const ev of state.watchEvents) {
    const row = document.createElement("article");
    const statusClass =
      ev.status === "success" ? "ok" : ev.status === "failure" || ev.status === "skipped" ? "warn" : "";
    row.className = `watch-log-item ${ev.status || ""}`;
    const when =
      typeof formatJalali === "function" ? formatJalali(ev.created_at, { withTime: true }) : ev.created_at || "";
    const counts = [];
    if (ev.action === "scan" || ev.found_count) counts.push(`یافت ${ev.found_count || 0}`);
    if (ev.new_count) counts.push(`تازه ${ev.new_count}`);
    if (ev.sent_count) counts.push(`ارسال ${ev.sent_count}`);
    row.innerHTML = `
      <div class="card-top">
        <div>
          <strong>${WATCH_ACTION[ev.action] || ev.action} · ${ev.filter_name || "فیلتر"}</strong>
          <p class="meta">${WATCH_PLATFORM[ev.platform] || ev.platform} → ${WATCH_CHANNEL[ev.channel] || ev.channel}${counts.length ? ` · ${counts.join(" · ")}` : ""}</p>
          <p class="meta">${ev.message || "—"}</p>
          <p class="meta">${when}${ev.destination ? ` · مقصد: <span dir="ltr">${ev.destination}</span>` : ""}</p>
        </div>
        <span class="pill ${statusClass}">${WATCH_STATUS[ev.status] || ev.status}</span>
      </div>
    `;
    els.watchList.append(row);
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
  const accounts = (user.messenger_accounts || [])
    .map((a) => `${CHANNEL_LABELS[a.channel] || a.channel}:${a.account_id}`)
    .join(" · ");
  els.head.innerHTML = `
    <div class="user-hero-main">
      <div>
        <p class="eyebrow">مشتری</p>
        <h2>${name}</h2>
        <p class="meta">یوزرنیم: @${handle}${user.telegram_username && user.telegram_username !== handle ? ` · تلگرام @${user.telegram_username}` : ""}</p>
        ${accounts ? `<p class="meta">پیام‌رسان‌ها: <span dir="ltr">${accounts}</span></p>` : ""}
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
  renderPlatforms(user);
  renderEitaaAdmin(user.eitaa || {});
  renderRoutes();
  renderPayments();
  renderWatchLog();
  renderTickets();
}

function renderPlatforms(user) {
  const caps = user.capabilities || {};
  const maxDest = Number(caps.max_destinations || 0);
  const rows = [
    ["تلگرام", true, !!user.linked || !!(user.telegram_chat_id)],
    ["بله", !!caps.allow_bale, (user.messenger_accounts || []).some((a) => a.channel === "bale")],
    ["ایتا", !!caps.allow_eitaa, !!user.eitaa_configured || !!(user.eitaa && user.eitaa.configured)],
    ["کیف‌پول بله", !!caps.allow_bale_wallet, null],
    ["سقف مقصد", true, maxDest > 0 ? `${maxDest}` : "نامحدود"],
  ];
  if (els.platformsCaps) {
    els.platformsCaps.replaceChildren();
    for (const [label, allowed, linked] of rows) {
      const chip = document.createElement("div");
      chip.className = "dest-chip";
      const status =
        linked === null
          ? allowed
            ? "مجاز در پلن"
            : "در پلن نیست"
          : typeof linked === "string"
            ? linked
            : allowed
              ? linked
                ? "مجاز · متصل"
                : "مجاز · هنوز وصل نشده"
              : "در پلن نیست";
      chip.innerHTML = `<span><b>${label}</b> · ${status}</span>`;
      if (!allowed && linked !== null && typeof linked !== "string") chip.classList.add("off");
      els.platformsCaps.append(chip);
    }
  }
  if (els.platformsLinks) {
    els.platformsLinks.replaceChildren();
    const accounts = user.messenger_accounts || [];
    if (!accounts.length && !user.telegram_chat_id && !(user.eitaa && (user.eitaa.channels || []).length)) {
      els.platformsLinks.append(
        Object.assign(document.createElement("p"), {
          className: "meta",
          textContent: "هنوز اتصال فعالی ثبت نشده.",
        }),
      );
    } else {
      for (const a of accounts) {
        const chip = document.createElement("div");
        chip.className = "dest-chip";
        chip.innerHTML = `<span>${CHANNEL_LABELS[a.channel] || a.channel} · <span dir="ltr">${a.account_id || "—"}</span>${
          a.username ? ` · @${a.username}` : ""
        }</span>`;
        els.platformsLinks.append(chip);
      }
      if (user.telegram_chat_id && !accounts.some((a) => a.channel === "telegram")) {
        const chip = document.createElement("div");
        chip.className = "dest-chip";
        chip.innerHTML = `<span>تلگرام · <span dir="ltr">${user.telegram_chat_id}</span></span>`;
        els.platformsLinks.append(chip);
      }
      for (const ch of (user.eitaa && user.eitaa.channels) || []) {
        const chip = document.createElement("div");
        chip.className = "dest-chip";
        chip.innerHTML = `<span>ایتا · ${chatLabel(ch)}</span>`;
        els.platformsLinks.append(chip);
      }
    }
  }
}

function renderEitaaAdmin(eitaa) {
  if (els.eitaaStatus) {
    els.eitaaStatus.textContent = eitaa.configured
      ? `توکن ذخیره شده: ${eitaa.token_masked || "••••"}`
      : "توکنی برای این مشتری ذخیره نشده.";
  }
  if (!els.eitaaChannels) return;
  els.eitaaChannels.replaceChildren();
  const channels = eitaa.channels || [];
  if (!channels.length) {
    els.eitaaChannels.append(
      Object.assign(document.createElement("p"), {
        className: "meta",
        textContent: "کانالی ثبت نشده.",
      }),
    );
    return;
  }
  for (const chat of channels) {
    const row = document.createElement("div");
    row.className = "dest-chip";
    const span = document.createElement("span");
    span.textContent = chatLabel(chat);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ghost small";
    btn.textContent = "حذف";
    btn.onclick = async () => {
      try {
        const data = await api(
          `/api/admin/users/${userId}/eitaa/channels/${encodeURIComponent(chat.id)}`,
          { method: "DELETE" },
        );
        if (state.user) state.user.eitaa = data;
        renderEitaaAdmin(data);
        toast("حذف شد", "ok");
      } catch (err) {
        toast(err.message, "err");
      }
    };
    row.append(span, btn);
    els.eitaaChannels.append(row);
  }
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

async function loadPayments() {
  const data = await api(`/api/admin/users/${userId}/invoices`);
  state.invoices = data.invoices || [];
  renderPayments();
}

async function loadWatchLog() {
  const data = await api(`/api/admin/users/${userId}/watch-events?limit=80`);
  state.watchEvents = data.events || [];
  renderWatchLog();
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

els.refreshPayments?.addEventListener("click", async () => {
  try {
    await loadPayments();
    toast(state.invoices.length ? `${state.invoices.length} فاکتور` : "فاکتوری نیست", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.refreshWatch?.addEventListener("click", async () => {
  try {
    await loadWatchLog();
    toast(state.watchEvents.length ? `${state.watchEvents.length} رویداد` : "رویدادی نیست", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

function renderTickets() {
  if (!els.ticketList) return;
  els.ticketList.replaceChildren();
  if (!state.tickets.length) {
    els.ticketList.append(
      Object.assign(document.createElement("p"), {
        className: "meta",
        textContent: "تیکتی نیست. از فرم سمت چپ پیام جدید بفرستید.",
      }),
    );
  } else {
    for (const ticket of state.tickets) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `ticket-card ${state.activeTicket?.id === ticket.id ? "active" : ""} ${ticket.status === "closed" ? "off" : ""}`;
      btn.innerHTML = `
        <div class="card-top">
          <strong>${ticket.subject || "بدون موضوع"}</strong>
          <span class="pill ${ticket.status === "closed" ? "warn" : "ok"}">${ticket.status === "closed" ? "بسته" : "باز"}</span>
        </div>
        <p class="meta">${ticket.last_body || "بدون پیام"}</p>
      `;
      btn.addEventListener("click", () => openAdminTicket(ticket.id));
      els.ticketList.append(btn);
    }
  }
  renderAdminThread(state.activeTicket);
}

function renderAdminThread(ticket) {
  if (!els.ticketThread) return;
  els.ticketThread.replaceChildren();
  if (!ticket) {
    els.ticketThread.append(
      Object.assign(document.createElement("p"), {
        className: "meta",
        textContent: "یک تیکت را انتخاب کنید یا پیام جدید بفرستید.",
      }),
    );
    if (els.ticketId) els.ticketId.value = "";
    if (els.ticketSubjectWrap) els.ticketSubjectWrap.hidden = false;
    if (els.ticketCloseBtn) els.ticketCloseBtn.hidden = true;
    return;
  }
  if (els.ticketId) els.ticketId.value = ticket.id;
  if (els.ticketSubjectWrap) els.ticketSubjectWrap.hidden = true;
  if (els.ticketCloseBtn) els.ticketCloseBtn.hidden = ticket.status === "closed";
  for (const msg of ticket.messages || []) {
    const mine = msg.sender === "admin";
    const bubble = document.createElement("div");
    bubble.className = `ticket-bubble ${mine ? "mine" : "theirs"}`;
    bubble.innerHTML = `
      <p class="meta">${mine ? "شما (پشتیبانی)" : "مشتری"}</p>
      <div>${msg.body || ""}</div>
      <p class="meta">${typeof formatJalali === "function" ? formatJalali(msg.created_at) : msg.created_at || ""}</p>
    `;
    els.ticketThread.append(bubble);
  }
  els.ticketThread.scrollTop = els.ticketThread.scrollHeight;
}

async function loadTickets() {
  const data = await api(`/api/admin/users/${userId}/tickets`);
  state.tickets = data.tickets || [];
  if (state.activeTicket) {
    const still = state.tickets.find((t) => t.id === state.activeTicket.id);
    if (!still) state.activeTicket = null;
  }
  renderTickets();
}

async function openAdminTicket(ticketId) {
  try {
    const data = await api(`/api/admin/users/${userId}/tickets/${ticketId}`);
    state.activeTicket = data.ticket;
    renderTickets();
  } catch (err) {
    toast(err.message, "err");
  }
}

els.refreshTickets?.addEventListener("click", async () => {
  try {
    await loadTickets();
    toast(state.tickets.length ? `${state.tickets.length} تیکت` : "تیکتی نیست", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.ticketCloseBtn?.addEventListener("click", async () => {
  const id = els.ticketId?.value;
  if (!id) return;
  try {
    const data = await api(`/api/admin/users/${userId}/tickets/${id}/close`, {
      method: "POST",
      body: {},
    });
    state.activeTicket = data.ticket;
    await loadTickets();
    toast("تیکت بسته شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.ticketForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = (els.ticketBody?.value || "").trim();
  if (!body) {
    toast("متن پیام را بنویسید", "err");
    return;
  }
  try {
    let data;
    if (els.ticketId?.value) {
      data = await api(`/api/admin/users/${userId}/tickets/${els.ticketId.value}/messages`, {
        method: "POST",
        body: { body },
      });
    } else {
      data = await api(`/api/admin/users/${userId}/tickets`, {
        method: "POST",
        body: {
          subject: els.ticketSubject?.value || "پیام پشتیبانی",
          body,
        },
      });
    }
    state.activeTicket = data.ticket;
    if (els.ticketBody) els.ticketBody.value = "";
    if (els.ticketSubject) els.ticketSubject.value = "";
    await loadTickets();
    toast("پیام ارسال شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

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

els.eitaaSave?.addEventListener("click", async () => {
  const token = String(els.eitaaToken?.value || "").trim();
  if (!token) {
    toast("توکن را وارد کنید", "err");
    return;
  }
  try {
    const data = await api(`/api/admin/users/${userId}/eitaa`, {
      method: "POST",
      body: { token },
    });
    if (els.eitaaToken) els.eitaaToken.value = "";
    if (state.user) state.user.eitaa = data.eitaa || data;
    renderEitaaAdmin(state.user.eitaa);
    toast("توکن ایتا ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.eitaaClear?.addEventListener("click", async () => {
  if (!confirm("توکن ایتای این مشتری حذف شود؟")) return;
  try {
    const data = await api(`/api/admin/users/${userId}/eitaa`, { method: "DELETE" });
    if (state.user) state.user.eitaa = data;
    renderEitaaAdmin(data);
    toast("توکن حذف شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.eitaaChannelAdd?.addEventListener("click", async () => {
  const chatId = String(els.eitaaChannel?.value || "").trim();
  if (!chatId) {
    toast("شناسه کانال را وارد کنید", "err");
    return;
  }
  try {
    const data = await api(`/api/admin/users/${userId}/eitaa/channels`, {
      method: "POST",
      body: { chat_id: chatId },
    });
    if (els.eitaaChannel) els.eitaaChannel.value = "";
    if (state.user) state.user.eitaa = data.eitaa || data;
    renderEitaaAdmin(state.user.eitaa);
    toast("کانال اضافه شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

async function boot() {
  bindLogout();
  bindJalaliPickers();
  const initial = (location.hash || "").replace("#", "") || "account";
  setTab(["account", "plan", "platforms", "poll", "routes", "payments", "watch", "tickets", "more"].includes(initial) ? initial : "account");
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
    await Promise.all([loadRoutes(), loadPayments(), loadWatchLog(), loadTickets()]);
    render();
  } catch (err) {
    toast(err.message, "err");
  }
}

els.plan?.expires_at?.addEventListener("change", () => {
  if (els.plan.expires_at.value) els.plan.renew.checked = false;
});

boot();
