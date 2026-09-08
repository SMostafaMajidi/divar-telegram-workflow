const state = { plans: [], editing: null };
const els = {
  list: $("#list"),
  editor: $("#editor"),
  form: $("#plan-form"),
  title: $("#editor-title"),
  newBtn: $("#new-btn"),
  close: $("#close-editor"),
  deleteBtn: $("#delete-btn"),
};

function criteriaLabel(plan) {
  if (plan.max_criteria == null || plan.max_criteria === "") return "نامحدود";
  return String(plan.max_criteria);
}

function render() {
  els.list.replaceChildren();
  for (const plan of state.plans) {
    const card = document.createElement("article");
    card.className = `invoice-card ${plan.active ? "" : "off"}`;
    card.innerHTML = `
      <div class="card-top">
        <div>
          <h3>${plan.name} <span class="meta">(${plan.id})</span></h3>
          <p class="meta">${plan.price_label || "—"} · ${plan.max_filters} فیلتر · معیار: ${criteriaLabel(plan)} · پایش ${plan.poll_interval_minutes}د</p>
          <p class="meta">${plan.tagline || ""}</p>
        </div>
        <div class="user-hero-pills">
          ${plan.ai_enabled ? '<span class="pill ok">AI</span>' : ""}
          ${plan.api_access ? '<span class="pill ok">API</span>' : ""}
          <span class="pill ${plan.active ? "ok" : "warn"}">${plan.active ? "فعال" : "غیرفعال"}</span>
        </div>
      </div>
      <button class="ghost small" type="button" data-edit="${plan.id}">ویرایش</button>
    `;
    els.list.append(card);
  }
  els.list.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.onclick = () => openEditor(state.plans.find((p) => p.id === btn.dataset.edit));
  });
}

function openEditor(plan = null) {
  state.editing = plan;
  els.form.reset();
  els.form.create.value = plan ? "0" : "1";
  els.title.textContent = plan ? `ویرایش «${plan.name}»` : "پلن جدید";
  els.form.id.readOnly = !!plan;
  els.deleteBtn.hidden = !plan || ["trial", "basic", "pro"].includes(plan.id);
  if (plan) {
    els.form.id.value = plan.id;
    els.form.name.value = plan.name || "";
    els.form.tagline.value = plan.tagline || "";
    els.form.price_toman.value = plan.price_toman ?? 0;
    els.form.duration_days.value = plan.duration_days ?? 30;
    els.form.max_filters.value = plan.max_filters ?? 1;
    els.form.max_criteria.value = plan.max_criteria == null ? "" : plan.max_criteria;
    els.form.poll_interval_minutes.value = plan.poll_interval_minutes ?? 5;
    els.form.sort_order.value = plan.sort_order ?? 0;
    els.form.ai_enabled.checked = !!plan.ai_enabled;
    els.form.api_access.checked = !!plan.api_access;
    els.form.active.checked = plan.active !== false;
    els.form.features.value = (plan.features || []).join("\n");
  } else {
    els.form.active.checked = true;
    els.form.duration_days.value = 30;
    els.form.max_filters.value = 3;
    els.form.poll_interval_minutes.value = 5;
  }
  els.editor.showModal();
}

els.newBtn.onclick = () => openEditor();
els.close.onclick = () => els.editor.close();

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const create = els.form.create.value === "1";
  const body = {
    create,
    id: els.form.id.value.trim().toLowerCase(),
    name: els.form.name.value.trim(),
    tagline: els.form.tagline.value.trim(),
    price_toman: Number(els.form.price_toman.value || 0),
    duration_days: Number(els.form.duration_days.value || 30),
    max_filters: Number(els.form.max_filters.value || 0),
    max_criteria: els.form.max_criteria.value.trim() === "" ? null : Number(els.form.max_criteria.value),
    poll_interval_minutes: Number(els.form.poll_interval_minutes.value || 5),
    sort_order: Number(els.form.sort_order.value || 0),
    ai_enabled: els.form.ai_enabled.checked,
    api_access: els.form.api_access.checked,
    active: els.form.active.checked,
    features: els.form.features.value,
  };
  try {
    await api("/api/admin/plans", { method: "POST", body });
    els.editor.close();
    toast("پلن ذخیره شد", "ok");
    await load();
  } catch (err) {
    toast(err.message, "err");
  }
});

els.deleteBtn.onclick = async () => {
  const id = els.form.id.value;
  if (!id || !confirm(`پلن ${id} حذف شود؟`)) return;
  try {
    await api(`/api/admin/plans/${id}`, { method: "DELETE" });
    els.editor.close();
    toast("حذف شد", "ok");
    await load();
  } catch (err) {
    toast(err.message, "err");
  }
};

async function load() {
  const data = await api("/api/admin/plans");
  state.plans = data.plans || [];
  render();
}

bindLogout();
load().catch((err) => toast(err.message, "err"));
