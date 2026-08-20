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
    location.href = "/app/login";
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
    els.list.append(el("p", { class: "empty", text: "هنوز فیلتری ثبت نشده است." }));
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
        text: `${filter.category_path || filter.category} · ${filter.query || "بدون عبارت"} · ${filter.cities.join("، ")} · ${priceText(filter)} · مقصد: ${filter.chat_id || "چت شخصی"}`,
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
  if (!state.user) return;
  els.welcome.textContent = `@${state.user.login_username || state.user.telegram_username}`;
  els.aiPill.textContent = state.user.ai_enabled ? "هوش مصنوعی فعال" : "هوش مصنوعی غیرفعال";
  els.aiPill.className = `pill ${state.user.ai_enabled ? "ok" : "warn"}`;
  els.runBtn.disabled = !state.user.ai_enabled;
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
  return {
    id: data.get("id") || undefined,
    name: data.get("name"),
    query: data.get("query"),
    cities: state.cities,
    exclude_title: state.exclude,
    max_pages: data.get("max_pages") || 3,
    enabled: els.form.enabled.checked,
    category: data.get("category") || "",
    chat_id: data.get("chat_id") || "",
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

function openEditor(filter = null) {
  state.editing = filter;
  els.form.reset();
  els.form.id.value = filter?.id || "";
  els.form.name.value = filter?.name || "";
  els.form.query.value = filter?.query || "";
  els.form.max_pages.value = filter?.max_pages || 3;
  els.form.enabled.checked = filter ? !!filter.enabled : true;
  if (els.form.chat_id) els.form.chat_id.value = filter?.chat_id || "";
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
  location.href = "/app/login";
});

els.categorySearch?.addEventListener("input", () => {
  renderCategoryPicker();
});

async function loadFeed() {
  const data = await api("/api/feed");
  renderResults(data.listings || [], "آگهی‌های اخیر", `${(data.listings || []).length} مورد`);
}

async function boot() {
  try {
    const [me, filters, categories] = await Promise.all([
      api("/api/me"),
      api("/api/filters"),
      api("/api/categories"),
    ]);
    state.user = me.user;
    state.filters = filters.filters || [];
    state.categoryTree = categories.tree || [];
    state.categoryFlat = categories.flat || [];
    renderFilters();
    renderStatus();
    await loadFeed();
  } catch (err) {
    location.replace("/app/login");
  }
}

boot();
