const $ = (sel, root = document) => root.querySelector(sel);

const DEFAULT_EXCLUDE = [
  "تصادفی",
  "چپی",
  "اسقاط",
  "موتور سوخته",
  "یاتاقان",
  "شاسی خورده",
  "خوردگی شاسی",
  "شاسی رنگ",
  "رنگ شاسی",
  "پوسیدگی",
  "زنگ زدگی",
];

const CHANNEL_LABELS = { telegram: "تلگرام", bale: "بله", eitaa: "ایتا" };

const state = {
  filters: [],
  chats: [],
  messengers: [],
  destinations: [],
  eitaa: null,
  tickets: [],
  activeTicket: null,
  status: {},
  user: null,
  categoryTree: [],
  categoryFlat: [],
  categoryTrail: [],
  divarSchema: [],
  divarValues: {},
  cities: [],
  exclude: [],
  editing: null,
};

const els = {
  list: $("#filter-list"),
  results: $("#results"),
  resultsTitle: $("#results-title"),
  resultsMeta: $("#results-meta"),
  toast: $("#toast"),
  editor: $("#editor"),
  form: $("#filter-form"),
  cityInput: $("#city-input"),
  cityChips: $("#city-chips"),
  citySuggest: $("#city-suggest"),
  cityPopular: $("#city-popular"),
  excludeInput: $("#exclude-input"),
  excludeChips: $("#exclude-chips"),
  aiPill: $("#ai-pill"),
  runBtn: $("#run-btn"),
  addBtn: $("#add-btn"),
  logoutBtn: $("#logout-btn"),
  categorySearch: $("#category-search"),
  categoryGrid: $("#category-grid"),
  categoryCrumb: $("#category-crumb"),
  categorySelected: $("#category-selected"),
  divarFields: $("#divar-fields"),
  apiKey: null,
  feedLink: $("#feed-link"),
  welcome: $("#welcome"),
  planLine: $("#plan-line"),
  filterQuota: $("#filter-quota"),
  apiDocsMenu: $("#api-docs-menu"),
  apiDocsFoot: $("#api-docs-foot"),
  apiDocsSep: $("#api-docs-sep"),
  destList: $("#dest-list"),
  destChannel: $("#dest-channel"),
  destChat: $("#dest-chat"),
  destEitaaId: $("#dest-eitaa-id"),
  destHint: $("#dest-hint"),
  destAddBtn: $("#dest-add-btn"),
  ticketList: $("#ticket-list"),
  ticketAddBtn: $("#ticket-add-btn"),
  ticketEditor: $("#ticket-editor"),
  ticketForm: $("#ticket-form"),
  ticketId: $("#ticket-id"),
  ticketSubject: $("#ticket-subject"),
  ticketBody: $("#ticket-body"),
  ticketCompose: $("#ticket-compose"),
  ticketThread: $("#ticket-thread"),
  ticketReplyBox: $("#ticket-reply-box"),
  ticketReply: $("#ticket-reply"),
  ticketCloseBtn: $("#ticket-close-btn"),
  ticketSubmitBtn: $("#ticket-submit-btn"),
  ticketEditorTitle: $("#ticket-editor-title"),
};

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "checked") node.checked = !!value;
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401) {
    location.href = "/";
    throw new Error("نیاز به ورود");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "خطا در ارتباط با سرور");
  return data;
}

function toast(message, kind = "") {
  els.toast.hidden = !message;
  els.toast.className = `toast ${kind}`.trim();
  els.toast.textContent = message || "";
}

function priceText(filter) {
  const min = filter.price_min_million;
  const max = filter.price_max_million;
  if (min == null && max == null) return "بدون محدودیت قیمت";
  if (min != null && max != null) return `${min} تا ${max} میلیون`;
  if (min != null) return `از ${min} میلیون`;
  return `تا ${max} میلیون`;
}

function chatLabel(chat) {
  const kinds = { private: "خصوصی", group: "گروه", supergroup: "گروه", channel: "کانال" };
  const kind = kinds[chat.type] || "";
  const channel = CHANNEL_LABELS[chat.channel] || chat.channel || "";
  const name = chat.name || (chat.username ? `@${chat.username}` : chat.id);
  const base = kind ? `${name} · ${kind}` : String(name);
  return channel ? `${channel} · ${base}` : base;
}

function destKey(d) {
  return `${d.channel || "telegram"}:${d.chat_id}`;
}

function formatDestinations(filter) {
  const dests = filter.destinations || [];
  if (!dests.length) {
    return filter.chat_id ? chatLabel({ id: filter.chat_id, channel: "telegram", type: "private" }) : "بدون مقصد";
  }
  return dests
    .map((d) => {
      const chat = state.chats.find(
        (c) => c.channel === (d.channel || "telegram") && String(c.id) === String(d.chat_id),
      );
      return chat
        ? chatLabel(chat)
        : `${CHANNEL_LABELS[d.channel] || d.channel} · ${d.chat_id}`;
    })
    .join(" · ");
}

function fillChannelSelect(select, selected) {
  if (!select) return;
  select.replaceChildren();
  const channels = (state.messengers.length
    ? state.messengers.filter((m) => m.enabled !== false).map((m) => m.channel)
    : ["telegram"]
  ).filter((ch) => ch !== "eitaa" || state.user?.capabilities?.allow_eitaa !== false);
  const unique = [...new Set(channels.length ? channels : ["telegram"])];
  for (const ch of unique) {
    const label = CHANNEL_LABELS[ch] || ch;
    select.append(el("option", { value: ch, text: label }));
  }
  if (selected && unique.includes(selected)) select.value = selected;
  else if (unique.length) select.value = unique[0];
}

function syncDestInputs() {
  const channel = els.destChannel?.value || "telegram";
  const isEitaa = channel === "eitaa";
  const eitaaChats = state.chats.filter((c) => (c.channel || "") === "eitaa");
  if (els.destChat) {
    els.destChat.hidden = isEitaa && !eitaaChats.length;
  }
  if (els.destEitaaId) {
    els.destEitaaId.hidden = !(isEitaa && !eitaaChats.length);
  }
  if (els.destHint) {
    if (!isEitaa) {
      els.destHint.textContent =
        "اول پیام‌رسان، بعد چت. می‌توانید چند مقصد از چند پیام‌رسان اضافه کنید.";
    } else if (!state.user?.eitaa_configured && !(state.eitaa && state.eitaa.configured)) {
      els.destHint.textContent = "اول در صفحه چت‌ها توکن ایتا را ذخیره کنید، بعد کانال اضافه کنید.";
    } else if (!eitaaChats.length) {
      els.destHint.textContent = "شناسه کانال را وارد کنید یا از صفحه چت‌ها کانال اضافه کنید.";
    } else {
      els.destHint.textContent = "یکی از کانال‌های ایتای ذخیره‌شده را انتخاب کنید.";
    }
  }
}

function fillDestChatSelect(select, channel, selected) {
  if (!select) return;
  const ch = channel || "telegram";
  if (ch === "eitaa") {
    const matched = state.chats.filter((c) => (c.channel || "") === "eitaa");
    select.replaceChildren(
      el("option", {
        value: "",
        text: matched.length ? "انتخاب کانال ایتا" : "اول کانال ایتا را در صفحه چت‌ها اضافه کنید",
      }),
    );
    for (const chat of matched) {
      select.append(el("option", { value: chat.id, text: chatLabel(chat) }));
    }
    if (selected) {
      if (![...select.options].some((o) => o.value === String(selected))) {
        select.append(el("option", { value: selected, text: selected }));
      }
      select.value = String(selected);
    } else if (matched.length === 1) {
      select.value = String(matched[0].id);
    }
    syncDestInputs();
    return;
  }
  const matched = state.chats.filter((c) => (c.channel || "telegram") === ch);
  select.replaceChildren(
    el("option", {
      value: "",
      text: matched.length ? "انتخاب چت" : "چتی برای این پیام‌رسان نیست — ربات را استارت/لاگین کنید",
    }),
  );
  for (const chat of matched) {
    select.append(el("option", { value: chat.id, text: chatLabel(chat) }));
  }
  if (selected) {
    if (![...select.options].some((o) => o.value === String(selected))) {
      select.append(el("option", { value: selected, text: selected }));
    }
    select.value = String(selected);
  } else if (matched.length === 1) {
    select.value = String(matched[0].id);
  }
  syncDestInputs();
}

async function refreshMessengerState() {
  const [chats, messengers, me] = await Promise.all([
    api("/api/chats"),
    api("/api/messengers"),
    api("/api/me"),
  ]);
  state.chats = chats.chats || [];
  state.messengers = messengers.messengers || me.messengers || [];
  if (me.user) state.user = me.user;
}

function renderDestList() {
  if (!els.destList) return;
  els.destList.replaceChildren();
  if (!state.destinations.length) {
    els.destList.append(el("p", { class: "meta", text: "هنوز مقصدی اضافه نشده." }));
    return;
  }
  for (const dest of state.destinations) {
    const chat = state.chats.find(
      (c) => (c.channel || "telegram") === dest.channel && String(c.id) === String(dest.chat_id),
    );
    const label = chat
      ? chatLabel(chat)
      : `${CHANNEL_LABELS[dest.channel] || dest.channel} · ${dest.chat_id}`;
    els.destList.append(
      el("div", { class: "dest-chip" }, [
        el("span", { text: label }),
        el("button", {
          type: "button",
          class: "ghost small",
          text: "حذف",
          onClick: () => {
            state.destinations = state.destinations.filter((d) => destKey(d) !== destKey(dest));
            renderDestList();
          },
        }),
      ]),
    );
  }
}

function renderMessengers() {
  if (!els.messengerList) return;
  els.messengerList.replaceChildren();
  if (!state.messengers.length) {
    els.messengerList.append(el("p", { class: "meta", text: "فعلاً ربات فعالی تنظیم نشده." }));
    return;
  }
  for (const m of state.messengers) {
    if (m.channel === "eitaa") continue; // dedicated setup section below
    const meta = m.linked
      ? "متصل است · برای چت‌های بیشتر باز کنید"
      : "برای اتصال استارت/لاگین کنید";
    const attrs = { class: `messenger-card ${m.linked ? "linked" : ""}` };
    if (m.deep_link) {
      attrs.href = m.deep_link;
      attrs.target = "_blank";
      attrs.rel = "noreferrer";
    }
    els.messengerList.append(
      el(m.deep_link ? "a" : "div", attrs, [
        el("strong", { text: m.label }),
        el("span", { class: "meta", text: meta }),
      ]),
    );
  }
}

function renderEitaaSetup(data) {
  state.eitaa = data || state.eitaa || {};
  const eitaa = state.eitaa;
  if (els.eitaaInstructions) {
    els.eitaaInstructions.replaceChildren();
    for (const step of eitaa.instructions || []) {
      els.eitaaInstructions.append(el("li", { text: step }));
    }
  }
  if (els.eitaaTokenStatus) {
    els.eitaaTokenStatus.textContent = eitaa.configured
      ? `توکن ذخیره شده: ${eitaa.token_masked || "••••"}`
      : "هنوز توکنی ذخیره نشده.";
  }
  if (els.eitaaTokenClear) els.eitaaTokenClear.hidden = !eitaa.configured;
  if (els.eitaaChannelList) {
    els.eitaaChannelList.replaceChildren();
    const channels = eitaa.channels || [];
    if (!channels.length) {
      els.eitaaChannelList.append(el("p", { class: "meta", text: "کانالی اضافه نشده." }));
    } else {
      for (const chat of channels) {
        els.eitaaChannelList.append(
          el("div", { class: "dest-chip" }, [
            el("span", { text: chatLabel(chat) }),
            el("button", {
              type: "button",
              class: "ghost small",
              text: "حذف",
              onClick: async () => {
                try {
                  const data = await api(`/api/eitaa/channels/${encodeURIComponent(chat.id)}`, {
                    method: "DELETE",
                  });
                  renderEitaaSetup(data);
                  await refreshMessengerState();
                  toast("کانال حذف شد", "ok");
                } catch (err) {
                  toast(err.message, "err");
                }
              },
            }),
          ]),
        );
      }
    }
  }
  if (state.user) state.user.eitaa_configured = !!eitaa.configured;
}

function fillChatSelect(select, selected) {
  if (!select) return;
  const privateId = String(state.user?.telegram_chat_id || "");
  select.replaceChildren(el("option", { value: "", text: "چت شخصی (پیش‌فرض)" }));
  for (const chat of state.chats) {
    if (privateId && String(chat.id) === privateId && (chat.channel || "telegram") === "telegram") continue;
    select.append(el("option", { value: chat.id, text: chatLabel(chat) }));
  }
  const selectedValue =
    selected && privateId && String(selected) === privateId ? "" : selected || "";
  if (selectedValue && ![...select.options].some((item) => item.value === String(selectedValue))) {
    select.append(el("option", { value: selectedValue, text: selectedValue }));
  }
  select.value = selectedValue || "";
}

function findTrail(slug, nodes = state.categoryTree, trail = []) {
  for (const node of nodes) {
    const next = trail.concat(node);
    if (node.slug === slug) return next;
    const found = findTrail(slug, node.children || [], next);
    if (found) return found;
  }
  return [];
}

function selectedCategory() {
  return els.form.category.value || "";
}

function setCategory(slug, { drill = false } = {}) {
  if (state.divarSchema.length && els.divarFields) {
    state.divarValues = { ...state.divarValues, ...collectDivarFields() };
  }
  const node = state.categoryFlat.find((item) => item.slug === slug);
  els.form.category.value = slug;
  els.categorySelected.textContent = node?.path || slug || "یک دسته انتخاب کنید";
  if (drill) {
    const trail = findTrail(slug);
    const last = trail[trail.length - 1];
    if (last?.children?.length) state.categoryTrail = trail;
    else state.categoryTrail = trail.slice(0, -1);
  }
  renderCategoryPicker();
  loadDivarFields(slug);
}

function currentCategoryChildren() {
  if (!state.categoryTrail.length) return state.categoryTree;
  const last = state.categoryTrail[state.categoryTrail.length - 1];
  return last.children || [];
}

function renderCategoryPicker() {
  if (!els.categoryGrid) return;
  const q = (els.categorySearch.value || "").trim();
  els.categoryCrumb.replaceChildren();
  els.categoryCrumb.append(
    el("button", {
      type: "button",
      text: "همه دسته‌ها",
      onClick: () => {
        state.categoryTrail = [];
        els.categorySearch.value = "";
        renderCategoryPicker();
      },
    })
  );
  for (let i = 0; i < state.categoryTrail.length; i += 1) {
    const node = state.categoryTrail[i];
    els.categoryCrumb.append(
      el("button", {
        type: "button",
        text: node.name,
        onClick: () => {
          state.categoryTrail = state.categoryTrail.slice(0, i + 1);
          els.categorySearch.value = "";
          renderCategoryPicker();
        },
      })
    );
  }

  const current = selectedCategory();
  els.categoryGrid.replaceChildren();
  if (q) {
    const needle = q.replace(/\s+/g, "");
    const matches = state.categoryFlat.filter(
      (item) => item.name.includes(q) || item.path.includes(q) || item.slug.includes(needle)
    );
    if (!matches.length) {
      els.categoryGrid.append(el("p", { class: "empty", text: "دسته‌ای با این نام نیست." }));
      return;
    }
    for (const item of matches.slice(0, 24)) {
      els.categoryGrid.append(
        el("button", {
          type: "button",
          class: item.slug === current ? "active" : "",
          text: item.path,
          onClick: () => setCategory(item.slug, { drill: true }),
        })
      );
    }
    return;
  }

  const parent = state.categoryTrail[state.categoryTrail.length - 1];
  if (parent) {
    els.categoryGrid.append(
      el("button", {
        type: "button",
        class: `pick-here ${parent.slug === current ? "active" : ""}`,
        text: `انتخاب «${parent.name}»`,
        onClick: () => setCategory(parent.slug),
      })
    );
  }
  for (const node of currentCategoryChildren()) {
    const label = node.children?.length ? `${node.name} ›` : node.name;
    els.categoryGrid.append(
      el("button", {
        type: "button",
        class: node.slug === current ? "active" : "",
        text: label,
        onClick: () => {
          if (node.children?.length) {
            state.categoryTrail = state.categoryTrail.concat(node);
            renderCategoryPicker();
            return;
          }
          setCategory(node.slug);
        },
      })
    );
  }
}

function renderFilters() {
  els.list.replaceChildren();
  if (!state.filters.length) {
    els.list.append(
      el("div", { class: "empty-state" }, [
        el("h3", { text: "هنوز فیلتری نداری" }),
        el("p", {
          class: "meta",
          text: "با یک فیلتر شروع کن؛ آگهی‌های تازه به مقصدهایی که انتخاب می‌کنی می‌رسند.",
        }),
        el("button", {
          class: "primary",
          type: "button",
          text: "ساخت اولین فیلتر",
          onClick: () => openEditor(),
        }),
      ]),
    );
    return;
  }
  for (const filter of state.filters) {
    const card = el("article", { class: `card filter-card ${filter.enabled ? "" : "off"}` }, [
      el("div", { class: "card-top" }, [
        el("div", {}, [
          el("h3", { text: filter.name }),
          el("p", {
            class: "meta",
            text: `${filter.category_path || filter.category} · ${filter.cities.join("، ") || "بدون شهر"}`,
          }),
        ]),
        el("label", { class: "check" }, [
          el("input", {
            type: "checkbox",
            checked: filter.enabled,
            onChange: async (event) => {
              try {
                const data = await api(`/api/filters/${filter.id}/toggle`, {
                  method: "POST",
                  body: { enabled: event.target.checked },
                });
                replaceFilter(data.filter);
              } catch (err) {
                toast(err.message, "err");
              }
            },
          }),
          "فعال",
        ]),
      ]),
      el("p", {
        class: "meta filter-meta",
        text: `${filter.query ? `جستجو: ${filter.query} · ` : ""}${priceText(filter)}`,
      }),
      el("p", { class: "meta", text: `مقصدها: ${formatDestinations(filter)}` }),
      el("div", { class: "card-actions" }, [
        el("button", {
          class: "ghost small",
          type: "button",
          text: "پیش‌نمایش",
          onClick: () => preview(filter),
        }),
        el("button", {
          class: "ghost small",
          type: "button",
          text: "ویرایش",
          onClick: () => openEditor(filter),
        }),
        el("button", {
          class: "ghost small",
          type: "button",
          text: "حذف",
          onClick: () => removeFilter(filter),
        }),
      ]),
    ]);
    els.list.append(card);
  }
}

function replaceFilter(updated) {
  const index = state.filters.findIndex((item) => item.id === updated.id);
  if (index >= 0) state.filters[index] = updated;
  else state.filters.push(updated);
  renderFilters();
}

function renderStatus() {
  if (!state.user) return;
  const name = state.user.login_username || state.user.telegram_username || "حساب من";
  els.welcome.textContent = `@${name}`;
  const plan = state.user.plan_name || state.user.plan_id || "—";
  const status = state.user.subscription_status || "—";
  const max = state.user.max_filters;
  const used = state.filters.length;
  const exp = state.user.expires_at ? formatJalali(state.user.expires_at) : null;
  if (els.planLine) {
    els.planLine.textContent = exp
      ? `پلن ${plan} · ${status} · تا ${exp}`
      : `پلن ${plan} · ${status}`;
  }
  if (els.filterQuota) {
    const parts = [max != null ? `${used} از ${max} فیلتر` : `${used} فیلتر`];
    if (state.user.max_criteria != null && Number(state.user.max_criteria) > 0) {
      parts.push(`تا ${state.user.max_criteria} معیار روی هر فیلتر`);
    }
    els.filterQuota.textContent = parts.join(" · ");
  }
  const aiOn = !!state.user.ai_enabled;
  if (els.aiPill) {
    els.aiPill.hidden = !aiOn;
    els.aiPill.textContent = "هوش مصنوعی فعال";
    els.aiPill.className = "pill ok";
  }
  if (els.runBtn) {
    els.runBtn.hidden = !aiOn;
    els.runBtn.disabled = !aiOn;
  }
  const apiOn = !!state.user.api_access;
  if (els.apiDocsMenu) els.apiDocsMenu.hidden = !apiOn;
  if (els.apiDocsFoot) els.apiDocsFoot.hidden = !apiOn;
  if (els.apiDocsSep) els.apiDocsSep.hidden = !apiOn;
  if (els.feedLink) {
    const slug = state.user.public_slug || state.user.login_username || state.user.telegram_username;
    els.feedLink.innerHTML = `صفحه اختصاصی: <a href="/u/${slug}" target="_blank">/u/${slug}</a>`;
  }
}

function renderResults(listings, title, meta) {
  els.resultsTitle.textContent = title || "نتایج";
  els.resultsMeta.textContent = meta || "";
  els.results.replaceChildren();
  if (!listings || !listings.length) {
    els.results.append(
      el("p", {
        class: "empty",
        text: "نتیجه‌ای نیست. یک فیلتر را پیش‌نمایش بگیر یا فیلتر جدید بساز.",
      })
    );
    return;
  }
  for (const item of listings) {
    els.results.append(
      el("a", { class: "ad", href: item.url, target: "_blank", rel: "noreferrer" }, [
        item.image_url ? el("img", { src: item.image_url, alt: item.title }) : el("div"),
        el("div", { class: "pad" }, [
          el("strong", { text: item.title }),
          el("div", { class: "price", text: item.price || "توافقی" }),
          el("div", { class: "loc", text: [item.location, item.mileage].filter(Boolean).join(" · ") }),
        ]),
      ])
    );
  }
}

function renderChips(root, values, onRemove) {
  root.replaceChildren();
  for (const value of values) {
    root.append(
      el("span", { class: "chip" }, [
        value,
        el("button", {
          type: "button",
          text: "×",
          onClick: () => onRemove(value),
        }),
      ])
    );
  }
}

function formPayload() {
  const data = new FormData(els.form);
  const destinations = state.destinations.length
    ? state.destinations.map((d) => ({
        channel: d.channel || "telegram",
        chat_id: String(d.chat_id),
        enabled: d.enabled !== false,
      }))
    : [];
  const legacyChat =
    destinations.find((d) => d.channel === "telegram")?.chat_id ||
    destinations[0]?.chat_id ||
    data.get("chat_id") ||
    "";
  if (els.form.chat_id) els.form.chat_id.value = legacyChat;
  return {
    id: data.get("id") || undefined,
    name: data.get("name"),
    query: data.get("query"),
    cities: state.cities,
    exclude_title: state.exclude,
    max_pages: data.get("max_pages") || 3,
    enabled: els.form.enabled.checked,
    category: data.get("category") || "",
    chat_id: legacyChat,
    destinations,
    fields: collectDivarFields(),
  };
}

function isTomanField(field) {
  return (field.unit || "").includes("تومان") || field.key === "price";
}

function rangeParts(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return {
      min: value.min ?? value.minimum ?? "",
      max: value.max ?? value.maximum ?? "",
    };
  }
  return { min: "", max: "" };
}

function displayRangeValue(field, raw) {
  if (raw === "" || raw == null) return "";
  const number = Number(raw);
  if (isTomanField(field) && Number.isFinite(number)) return String(Math.round(number / 1_000_000));
  return String(raw);
}

function storeRangeValue(field, raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  if (isTomanField(field)) return String(Math.round(Number(text) * 1_000_000));
  return text;
}

async function loadDivarFields(slug) {
  if (!els.divarFields) return;
  els.divarFields.replaceChildren(el("p", { class: "muted", text: "در حال خواندن فیلترهای دیوار…" }));
  try {
    const data = await api(`/api/divar-filters?category=${encodeURIComponent(slug)}`);
    state.divarSchema = data.fields || [];
    renderDivarFields();
  } catch (err) {
    els.divarFields.replaceChildren(el("p", { class: "empty", text: err.message }));
  }
}

function renderDivarFields() {
  if (!els.divarFields) return;
  els.divarFields.replaceChildren();
  if (!state.divarSchema.length) {
    els.divarFields.append(el("p", { class: "muted", text: "این دسته فیلتر اضافه‌ای ندارد." }));
    return;
  }
  for (const field of state.divarSchema) {
    els.divarFields.append(renderDivarField(field, state.divarValues[field.key]));
  }
}

function emptyOption() {
  return el("option", { value: "", text: "بدون محدودیت" });
}

function renderDivarField(field, value) {
  const title = field.unit ? `${field.title} (${field.unit})` : field.title;
  if (field.ui === "toggle") {
    return el("label", { class: "check" }, [
      el("input", {
        type: "checkbox",
        "data-divar": field.key,
        "data-ui": field.ui,
        checked: value === true,
      }),
      title,
    ]);
  }
  if (field.ui === "range_input" || field.ui === "range_select") {
    const parts = rangeParts(value);
    const toman = isTomanField(field);
    const fromLabel = toman ? "حداقل (میلیون تومان)" : "از";
    const toLabel = toman ? "حداکثر (میلیون تومان)" : "تا";
    const control = (bound, current) => {
      if (field.ui === "range_select") {
        const options = bound === "min" ? field.from_options || [] : field.to_options || [];
        const select = el("select", { "data-divar": field.key, "data-bound": bound, "data-ui": field.ui });
        select.append(emptyOption());
        for (const option of options) {
          select.append(el("option", { value: option.value, text: option.label }));
        }
        select.value = current === "" || current == null ? "" : String(current);
        if (current && select.value !== String(current)) {
          select.append(el("option", { value: String(current), text: String(current) }));
          select.value = String(current);
        }
        return select;
      }
      return el("input", {
        type: "number",
        min: "0",
        step: "1",
        "data-divar": field.key,
        "data-bound": bound,
        "data-ui": field.ui,
        value: displayRangeValue(field, current),
        placeholder: toman ? "مثلاً ۳۰۰" : "",
      });
    };
    return el("div", { class: "row" }, [
      el("label", {}, [fromLabel, control("min", parts.min)]),
      el("label", {}, [toLabel, control("max", parts.max)]),
    ]);
  }
  if (field.ui === "tags") {
    return el("label", {}, [
      title,
      el("input", {
        "data-divar": field.key,
        "data-ui": field.ui,
        value: Array.isArray(value) ? value.join("، ") : value || "",
        placeholder: field.placeholder || "با ویرگول جدا کن",
      }),
    ]);
  }
  if (field.ui === "chips") {
    const selected = new Set((value || []).map(String));
    return el("div", { class: "field" }, [
      el("span", { text: title }),
      el("div", { class: "chip-options" },
        (field.options || []).map((option) =>
          el("label", {}, [
            el("input", {
              type: "checkbox",
              "data-divar": field.key,
              "data-ui": field.ui,
              value: option.value,
              checked: selected.has(String(option.value)),
            }),
            option.label,
          ])
        )
      ),
    ]);
  }
  if (field.ui === "multi") {
    const selected = new Set((value || []).map(String));
    const select = el("select", {
      multiple: true,
      "data-divar": field.key,
      "data-ui": field.ui,
    });
    for (const option of field.options || []) {
      const node = el("option", { value: option.value, text: option.label });
      node.selected = selected.has(String(option.value));
      select.append(node);
    }
    return el("label", {}, [title, select]);
  }
  const select = el("select", { "data-divar": field.key, "data-ui": "select" });
  select.append(emptyOption());
  for (const option of field.options || []) {
    select.append(el("option", { value: option.value, text: option.label }));
  }
  select.value = value == null ? "" : String(value);
  return el("label", {}, [title, select]);
}

function collectDivarFields() {
  const out = {};
  for (const field of state.divarSchema) {
    const nodes = [...els.divarFields.querySelectorAll(`[data-divar="${field.key}"]`)];
    if (!nodes.length) continue;
    if (field.ui === "toggle") {
      if (nodes[0].checked) out[field.key] = true;
      continue;
    }
    if (field.ui === "range_input" || field.ui === "range_select") {
      const minNode = nodes.find((node) => node.dataset.bound === "min");
      const maxNode = nodes.find((node) => node.dataset.bound === "max");
      const min = field.ui === "range_input" ? storeRangeValue(field, minNode?.value) : (minNode?.value || "");
      const max = field.ui === "range_input" ? storeRangeValue(field, maxNode?.value) : (maxNode?.value || "");
      if (min || max) out[field.key] = { ...(min ? { min } : {}), ...(max ? { max } : {}) };
      continue;
    }
    if (field.ui === "chips") {
      const values = nodes.filter((node) => node.checked).map((node) => node.value);
      if (values.length) out[field.key] = values;
      continue;
    }
    if (field.ui === "multi") {
      const values = [...nodes[0].selectedOptions].map((option) => option.value).filter(Boolean);
      if (values.length) out[field.key] = values;
      continue;
    }
    if (field.ui === "tags") {
      const values = String(nodes[0].value || "")
        .split(/[،,]+/)
        .map((item) => item.trim())
        .filter(Boolean);
      if (values.length) out[field.key] = values;
      continue;
    }
    if (nodes[0].value) out[field.key] = nodes[0].value;
  }
  return out;
}

async function openEditor(filter = null) {
  state.editing = filter;
  els.form.reset();
  els.form.id.value = filter?.id || "";
  els.form.name.value = filter?.name || "";
  els.form.query.value = filter?.query || "";
  els.form.max_pages.value = filter?.max_pages || 3;
  els.form.enabled.checked = filter ? !!filter.enabled : true;
  try {
    await refreshMessengerState();
  } catch (err) {
    toast(err.message, "err");
  }
  state.destinations = (filter?.destinations || [])
    .filter((d) => d && d.chat_id)
    .map((d) => ({
      channel: d.channel || "telegram",
      chat_id: String(d.chat_id),
      enabled: d.enabled !== false,
    }));
  if (!state.destinations.length && filter?.chat_id) {
    state.destinations = [
      { channel: "telegram", chat_id: String(filter.chat_id), enabled: true },
    ];
  }
  const preferredChannel =
    state.destinations[0]?.channel ||
    state.messengers.find((m) => m.linked)?.channel ||
    state.messengers[0]?.channel ||
    "telegram";
  fillChannelSelect(els.destChannel, preferredChannel);
  fillDestChatSelect(els.destChat, els.destChannel?.value || preferredChannel);
  renderDestList();
  if (els.form.chat_id) {
    els.form.chat_id.value = state.destinations[0]?.chat_id || filter?.chat_id || "";
  }
  state.divarValues = { ...(filter?.fields || {}) };
  const slug = filter?.category || "light";
  els.form.category.value = slug;
  const trail = findTrail(slug);
  const last = trail[trail.length - 1];
  state.categoryTrail = last?.children?.length ? trail : trail.slice(0, -1);
  els.categorySearch.value = "";
  setCategory(slug);
  state.cities = [...(filter?.cities || [])];
  state.exclude = [...(filter?.exclude_title || [])];
  $("#editor-title").textContent = filter ? "ویرایش فیلتر" : "فیلتر جدید";
  refreshChips();
  loadPopularCities();
  els.editor.showModal();
  els.form.name.focus();
}

function refreshChips() {
  renderChips(els.cityChips, state.cities, (value) => {
    state.cities = state.cities.filter((item) => item !== value);
    refreshChips();
  });
  renderChips(els.excludeChips, state.exclude, (value) => {
    state.exclude = state.exclude.filter((item) => item !== value);
    refreshChips();
  });
}

function addCity(name) {
  if (!name || state.cities.includes(name)) return;
  state.cities.push(name);
  els.cityInput.value = "";
  els.citySuggest.hidden = true;
  refreshChips();
}

function addExclude(word) {
  const value = word.trim();
  if (!value || state.exclude.includes(value)) return;
  state.exclude.push(value);
  els.excludeInput.value = "";
  refreshChips();
}

async function loadPopularCities() {
  try {
    const data = await api("/api/cities");
    els.cityPopular.replaceChildren(
      ...data.cities.map((city) =>
        el("button", {
          type: "button",
          text: city.name,
          onClick: () => addCity(city.name),
        })
      )
    );
  } catch (err) {
    toast(err.message, "err");
  }
}

let cityTimer = null;
els.cityInput.addEventListener("input", () => {
  clearTimeout(cityTimer);
  const q = els.cityInput.value.trim();
  cityTimer = setTimeout(async () => {
    if (!q) {
      els.citySuggest.hidden = true;
      return;
    }
    try {
      const data = await api(`/api/cities?q=${encodeURIComponent(q)}`);
      els.citySuggest.replaceChildren(
        ...data.cities.map((city) =>
          el("button", {
            type: "button",
            text: city.name,
            onClick: () => addCity(city.name),
          })
        )
      );
      els.citySuggest.hidden = data.cities.length === 0;
    } catch (err) {
      toast(err.message, "err");
    }
  }, 180);
});

els.cityInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    const first = els.citySuggest.querySelector("button");
    if (first) addCity(first.textContent);
  }
});

els.excludeInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addExclude(els.excludeInput.value);
  }
});

async function preview(filter) {
  toast("در حال جستجوی دیوار…");
  try {
    const data = await api("/api/preview", { method: "POST", body: filter });
    toast(`${data.count} آگهی پیدا شد`, "ok");
    renderResults(data.listings, data.filter || "نتایج", `${data.count} آگهی`);
  } catch (err) {
    toast(err.message, "err");
  }
}

async function removeFilter(filter) {
  if (!confirm(`فیلتر «${filter.name}» حذف شود؟`)) return;
  try {
    await api(`/api/filters/${filter.id}`, { method: "DELETE" });
    state.filters = state.filters.filter((item) => item.id !== filter.id);
    renderFilters();
    toast("فیلتر حذف شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formPayload();
  if (!payload.destinations.length) {
    toast("حداقل یک مقصد ارسال اضافه کنید", "err");
    return;
  }
  try {
    const method = payload.id ? "PUT" : "POST";
    const path = payload.id ? `/api/filters/${payload.id}` : "/api/filters";
    const data = await api(path, { method, body: payload });
    replaceFilter(data.filter);
    els.editor.close();
    toast("فیلتر ذخیره شد", "ok");
    await preview(data.filter);
  } catch (err) {
    toast(err.message, "err");
  }
});

els.destChannel?.addEventListener("change", () => {
  fillDestChatSelect(els.destChat, els.destChannel.value);
  syncDestInputs();
});

els.destAddBtn?.addEventListener("click", () => {
  const channel = els.destChannel?.value || "telegram";
  let chatId = "";
  if (channel === "eitaa") {
    const eitaaChats = state.chats.filter((c) => (c.channel || "") === "eitaa");
    if (eitaaChats.length && els.destChat && !els.destChat.hidden) {
      chatId = els.destChat.value;
    } else {
      chatId = String(els.destEitaaId?.value || "")
        .trim()
        .replace(/^@+/, "")
        .replace(/^https?:\/\/(www\.)?eitaa\.com\//i, "")
        .replace(/\/$/, "");
    }
    if (!chatId) {
      toast("کانال ایتا را انتخاب یا وارد کنید", "err");
      return;
    }
  } else {
    chatId = els.destChat?.value;
    if (!chatId) {
      toast("چت را انتخاب کنید", "err");
      return;
    }
  }
  if (state.destinations.some((d) => destKey(d) === destKey({ channel, chat_id: chatId }))) {
    toast("این مقصد قبلاً اضافه شده", "err");
    return;
  }
  state.destinations.push({ channel, chat_id: chatId, enabled: true });
  if (channel === "eitaa" && els.destEitaaId) els.destEitaaId.value = "";
  renderDestList();
});

els.eitaaTokenSave?.addEventListener("click", async () => {
  const token = String(els.eitaaToken?.value || "").trim();
  if (!token) {
    toast("توکن را وارد کنید", "err");
    return;
  }
  els.eitaaTokenSave.disabled = true;
  try {
    const data = await api("/api/eitaa", { method: "POST", body: { token } });
    if (els.eitaaToken) els.eitaaToken.value = "";
    renderEitaaSetup(data.eitaa || data);
    await refreshMessengerState();
    toast("توکن ایتا ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  } finally {
    els.eitaaTokenSave.disabled = false;
  }
});

els.eitaaTokenClear?.addEventListener("click", async () => {
  if (!confirm("توکن ایتایار حذف شود؟")) return;
  try {
    const data = await api("/api/eitaa", { method: "DELETE" });
    renderEitaaSetup(data);
    await refreshMessengerState();
    toast("توکن حذف شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.eitaaChannelAdd?.addEventListener("click", async () => {
  const chatId = String(els.eitaaChannelId?.value || "").trim();
  if (!chatId) {
    toast("شناسه کانال را وارد کنید", "err");
    return;
  }
  els.eitaaChannelAdd.disabled = true;
  try {
    const data = await api("/api/eitaa/channels", {
      method: "POST",
      body: { chat_id: chatId },
    });
    if (els.eitaaChannelId) els.eitaaChannelId.value = "";
    renderEitaaSetup(data.eitaa || data);
    await refreshMessengerState();
    toast("کانال اضافه شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  } finally {
    els.eitaaChannelAdd.disabled = false;
  }
});

$("#preview-form-btn").addEventListener("click", async () => {
  try {
    await preview(formPayload());
  } catch (err) {
    toast(err.message, "err");
  }
});

$("#close-editor").addEventListener("click", () => els.editor.close());
els.addBtn.addEventListener("click", () => openEditor());

els.runBtn.addEventListener("click", async () => {
  if (!state.user?.ai_enabled) {
    toast("رتبه‌بندی هوشمند برای حساب شما فعال نیست. از پشتیبانی درخواست دهید.", "err");
    return;
  }
  els.runBtn.disabled = true;
  toast("در حال انتخاب آگهی‌های برتر…");
  try {
    const data = await api("/api/run", { method: "POST", body: {} });
    toast(data.message, "ok");
    renderResults(data.listings, "ارسال‌شده‌ها", data.message);
  } catch (err) {
    toast(err.message, "err");
  } finally {
    els.runBtn.disabled = !state.user?.ai_enabled;
  }
});

els.logoutBtn?.addEventListener("click", async () => {
  await api("/api/logout", { method: "POST", body: {} });
  location.href = "/";
});

els.categorySearch?.addEventListener("input", () => {
  renderCategoryPicker();
});

async function loadFeed() {
  const data = await api("/api/feed");
  renderResults(data.listings || [], "آگهی‌های اخیر", `${(data.listings || []).length} مورد`);
}

async function loadChats() {
  const data = await api("/api/chats");
  state.chats = data.chats || [];
  renderFilters();
}

function ticketStatusLabel(status) {
  return status === "closed" ? "بسته" : "باز";
}

function renderTickets() {
  if (!els.ticketList) return;
  els.ticketList.replaceChildren();
  if (!state.tickets.length) {
    els.ticketList.append(
      el("p", { class: "meta", text: "هنوز تیکتی ندارید. اگر سوال یا مشکلی بود، تیکت جدید بزنید." }),
    );
    return;
  }
  for (const ticket of state.tickets) {
    els.ticketList.append(
      el("button", {
        type: "button",
        class: `ticket-card ${ticket.status === "closed" ? "off" : ""}`,
        onClick: () => openTicket(ticket.id),
      }, [
        el("div", { class: "card-top" }, [
          el("strong", { text: ticket.subject || "بدون موضوع" }),
          el("span", {
            class: `pill ${ticket.status === "closed" ? "warn" : "ok"}`,
            text: ticketStatusLabel(ticket.status),
          }),
        ]),
        el("p", {
          class: "meta",
          text: ticket.last_body
            ? `${ticket.last_sender === "admin" ? "پشتیبانی" : "شما"}: ${ticket.last_body}`
            : "بدون پیام",
        }),
      ]),
    );
  }
}

async function loadTickets() {
  const data = await api("/api/tickets");
  state.tickets = data.tickets || [];
  renderTickets();
}

function renderTicketThread(ticket) {
  if (!els.ticketThread) return;
  els.ticketThread.replaceChildren();
  for (const msg of ticket.messages || []) {
    const mine = msg.sender === "user";
    els.ticketThread.append(
      el("div", { class: `ticket-bubble ${mine ? "mine" : "theirs"}` }, [
        el("p", { class: "meta", text: mine ? "شما" : "پشتیبانی" }),
        el("div", { text: msg.body }),
        el("p", {
          class: "meta",
          text: typeof formatJalali === "function" ? formatJalali(msg.created_at) : msg.created_at,
        }),
      ]),
    );
  }
  els.ticketThread.scrollTop = els.ticketThread.scrollHeight;
}

function openNewTicket() {
  state.activeTicket = null;
  if (els.ticketId) els.ticketId.value = "";
  if (els.ticketSubject) els.ticketSubject.value = "";
  if (els.ticketBody) els.ticketBody.value = "";
  if (els.ticketReply) els.ticketReply.value = "";
  if (els.ticketCompose) els.ticketCompose.hidden = false;
  if (els.ticketThread) els.ticketThread.hidden = true;
  if (els.ticketReplyBox) els.ticketReplyBox.hidden = true;
  if (els.ticketCloseBtn) els.ticketCloseBtn.hidden = true;
  if (els.ticketEditorTitle) els.ticketEditorTitle.textContent = "تیکت جدید";
  if (els.ticketSubmitBtn) els.ticketSubmitBtn.textContent = "ارسال تیکت";
  els.ticketEditor?.showModal();
}

async function openTicket(ticketId) {
  try {
    const data = await api(`/api/tickets/${ticketId}`);
    const ticket = data.ticket;
    state.activeTicket = ticket;
    if (els.ticketId) els.ticketId.value = ticket.id;
    if (els.ticketCompose) els.ticketCompose.hidden = true;
    if (els.ticketThread) els.ticketThread.hidden = false;
    if (els.ticketReplyBox) els.ticketReplyBox.hidden = ticket.status === "closed";
    if (els.ticketCloseBtn) els.ticketCloseBtn.hidden = ticket.status === "closed";
    if (els.ticketReply) els.ticketReply.value = "";
    if (els.ticketEditorTitle) els.ticketEditorTitle.textContent = ticket.subject || "تیکت";
    if (els.ticketSubmitBtn) {
      els.ticketSubmitBtn.textContent = ticket.status === "closed" ? "بستن" : "ارسال پاسخ";
      els.ticketSubmitBtn.hidden = ticket.status === "closed";
    }
    renderTicketThread(ticket);
    els.ticketEditor?.showModal();
  } catch (err) {
    toast(err.message, "err");
  }
}

els.ticketAddBtn?.addEventListener("click", () => openNewTicket());
$("#close-ticket-editor")?.addEventListener("click", () => els.ticketEditor?.close());

els.ticketCloseBtn?.addEventListener("click", async () => {
  const id = els.ticketId?.value;
  if (!id) return;
  try {
    await api(`/api/tickets/${id}/close`, { method: "POST", body: {} });
    toast("تیکت بسته شد", "ok");
    els.ticketEditor?.close();
    await loadTickets();
  } catch (err) {
    toast(err.message, "err");
  }
});

els.ticketForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    if (!state.activeTicket) {
      const data = await api("/api/tickets", {
        method: "POST",
        body: {
          subject: els.ticketSubject?.value || "",
          body: els.ticketBody?.value || "",
        },
      });
      toast("تیکت ثبت شد", "ok");
      els.ticketEditor?.close();
      await loadTickets();
      if (data.ticket?.id) openTicket(data.ticket.id);
      return;
    }
    const reply = (els.ticketReply?.value || "").trim();
    if (!reply) {
      toast("متن پاسخ را بنویسید", "err");
      return;
    }
    const data = await api(`/api/tickets/${state.activeTicket.id}/messages`, {
      method: "POST",
      body: { body: reply },
    });
    state.activeTicket = data.ticket;
    if (els.ticketReply) els.ticketReply.value = "";
    renderTicketThread(data.ticket);
    await loadTickets();
    toast("پاسخ ارسال شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

async function boot() {
  try {
    const [me, filters, categories, chats, messengers] = await Promise.all([
      api("/api/me"),
      api("/api/filters"),
      api("/api/categories"),
      api("/api/chats"),
      api("/api/messengers"),
    ]);
    state.user = me.user;
    state.filters = filters.filters || [];
    state.chats = chats.chats || [];
    state.messengers = messengers.messengers || me.messengers || [];
    state.categoryTree = categories.tree || [];
    state.categoryFlat = categories.flat || [];
    renderStatus();
    renderFilters();
    await Promise.all([loadFeed(), loadTickets()]);
  } catch (err) {
    location.replace("/");
  }
}

bindNavMenus();
boot();
