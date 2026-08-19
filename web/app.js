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

const state = {
  filters: [],
  status: {},
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
  telegramPill: $("#telegram-pill"),
  llmPill: $("#llm-pill"),
  botPill: $("#bot-pill"),
  watchPill: $("#watch-pill"),
  watchBtn: $("#watch-btn"),
  runBtn: $("#run-btn"),
  addBtn: $("#add-btn"),
  settings: $("#settings-form"),
  telegramSetup: $("#telegram-setup"),
  telegramHint: $("#telegram-setup-hint"),
  detectChatBtn: $("#detect-chat-btn"),
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
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
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

function renderFilters() {
  els.list.replaceChildren();
  if (!state.filters.length) {
    els.list.append(el("p", { class: "empty", text: "هنوز فیلتری نساختی." }));
    return;
  }
  for (const filter of state.filters) {
    const card = el("article", { class: `card ${filter.enabled ? "" : "off"}` }, [
      el("div", { class: "card-top" }, [
        el("h3", { text: filter.name }),
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
        class: "meta",
        text: `${filter.query} · ${filter.cities.join("، ")} · ${priceText(filter)}`,
      }),
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
  const ready = !!state.status.telegram_ready;
  const hasToken = !!state.status.telegram_token;
  const bot = state.status.bot_username;
  els.telegramPill.textContent = ready
    ? "تلگرام وصل است"
    : hasToken
      ? "Chat ID ندارد"
      : "تلگرام تنظیم نشده";
  els.telegramPill.className = `pill ${ready ? "ok" : "warn"}`;
  els.llmPill.textContent = state.status.llm_ready
    ? `مدل ${state.status.llm_model || ""}`.trim()
    : "مدل تنظیم نشده";
  els.llmPill.className = `pill ${state.status.llm_ready ? "ok" : "warn"}`;
  els.botPill.textContent = state.status.bot_running ? "ربات روشن" : "ربات خاموش";
  els.botPill.className = `pill ${state.status.bot_running ? "ok" : ""}`;
  els.watchPill.textContent = state.status.watching ? "پایش روشن" : "پایش خاموش";
  els.watchPill.className = `pill ${state.status.watching ? "ok" : ""}`;
  els.watchBtn.textContent = state.status.watching ? "توقف پایش" : "شروع پایش";
  els.settings.poll_interval_minutes.value = state.status.poll_interval_minutes || 3;
  els.settings.best_count.value = state.status.best_count || 5;
  els.settings.send_photos.checked = !!state.status.send_photos;

  const needsChat = hasToken && !state.status.telegram_chat;
  els.telegramSetup.hidden = !needsChat;
  if (needsChat) {
    const botLabel = bot ? `@${bot}` : "ربات";
    els.telegramHint.replaceChildren(
      "در تلگرام ",
      bot
        ? el("a", { href: `https://t.me/${bot}`, target: "_blank", text: botLabel })
        : botLabel,
      " را باز کن، ",
      el("b", { text: "/start" }),
      " بزن، بعد دکمه خواندن Chat ID را بزن."
    );
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
  return {
    id: data.get("id") || undefined,
    name: data.get("name"),
    query: data.get("query"),
    cities: state.cities,
    price_min_million: data.get("price_min_million") || null,
    price_max_million: data.get("price_max_million") || null,
    exclude_title: state.exclude,
    max_pages: data.get("max_pages") || 3,
    enabled: els.form.enabled.checked,
  };
}

function openEditor(filter = null) {
  state.editing = filter;
  els.form.reset();
  els.form.id.value = filter?.id || "";
  els.form.name.value = filter?.name || "";
  els.form.query.value = filter?.query || "";
  els.form.price_min_million.value = filter?.price_min_million ?? "";
  els.form.price_max_million.value = filter?.price_max_million ?? "";
  els.form.max_pages.value = filter?.max_pages || 3;
  els.form.enabled.checked = filter ? !!filter.enabled : true;
  state.cities = [...(filter?.cities || [])];
  state.exclude = [...(filter?.exclude_title || DEFAULT_EXCLUDE)];
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
  els.runBtn.disabled = true;
  toast("در حال انتخاب ۵ آگهی برتر…");
  try {
    const data = await api("/api/run", { method: "POST", body: {} });
    toast(data.message, "ok");
    renderResults(data.listings, "ارسال‌شده‌ها", data.message);
  } catch (err) {
    toast(err.message, "err");
  } finally {
    els.runBtn.disabled = false;
  }
});

els.detectChatBtn.addEventListener("click", async () => {
  els.detectChatBtn.disabled = true;
  toast("در حال خواندن Chat ID از تلگرام…");
  try {
    const data = await api("/api/telegram/detect-chat", { method: "POST", body: {} });
    if (data.status) state.status = { ...state.status, ...data.status };
    renderStatus();
    toast(
      data.saved
        ? `Chat ID ذخیره شد: ${data.chat_id}`
        : "چند چت پیدا شد؛ یکی را انتخاب کن.",
      "ok"
    );
  } catch (err) {
    toast(err.message, "err");
  } finally {
    els.detectChatBtn.disabled = false;
  }
});

els.watchBtn.addEventListener("click", async () => {
  try {
    const action = state.status.watching ? "stop" : "start";
    const data = await api("/api/watch", { method: "POST", body: { action } });
    state.status.watching = data.watching;
    renderStatus();
    toast(
      data.watching
        ? (data.next_watch_at
          ? `پایش روشن شد؛ نوبت بعدی ساعت ${data.next_watch_at} — فقط تازه‌ترین‌ها`
          : "پایش روشن شد؛ فقط آگهی‌های تازه می‌آیند.")
        : "پایش متوقف شد",
      "ok",
    );
  } catch (err) {
    toast(err.message, "err");
  }
});

els.settings.addEventListener("submit", async (event) => {
  event.preventDefault();
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

async function boot() {
  try {
    const [filters, status] = await Promise.all([api("/api/filters"), api("/api/status")]);
    state.filters = filters.filters || [];
    state.status = status;
    renderFilters();
    renderStatus();
    renderResults([], "نتایج");
  } catch (err) {
    toast(err.message, "err");
  }
}

boot();
