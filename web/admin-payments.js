const list = $("#list");
const filter = $("#status-filter");

const STATUS = {
  pending: "در انتظار پرداخت",
  awaiting_review: "در صف تأیید",
  paid: "پرداخت‌شده",
  rejected: "رد شده",
};

function render(invoices) {
  list.replaceChildren();
  if (!invoices.length) {
    list.append(Object.assign(document.createElement("p"), { className: "empty", textContent: "موردی نیست." }));
    return;
  }
  for (const inv of invoices) {
    const name = inv.user_name || inv.login_username || inv.telegram_username || inv.user_id;
    const card = document.createElement("article");
    card.className = "invoice-card";
    const actions =
      inv.status === "pending" || inv.status === "awaiting_review"
        ? `<div class="row">
            <button class="primary small" type="button" data-confirm="${inv.id}">تأیید و فعال‌سازی پلن</button>
            <button class="ghost small" type="button" data-reject="${inv.id}">رد</button>
            ${inv.user_id ? `<a class="ghost small" href="/admin/users/${inv.user_id}">صفحه مشتری</a>` : ""}
          </div>`
        : inv.user_id
          ? `<a class="ghost small" href="/admin/users/${inv.user_id}">صفحه مشتری</a>`
          : "";
    card.innerHTML = `
      <div class="card-top">
        <div>
          <h3>${name}</h3>
          <p class="meta">${inv.plan_name} · ${inv.amount_label} · شناسه <b dir="ltr">${inv.ref_code}</b></p>
          <p class="meta">یوزرنیم: @${inv.login_username || "—"} · پیگیری: ${inv.payer_note || "—"}</p>
          <p class="meta">${typeof formatJalali === "function" ? formatJalali(inv.created_at, { withTime: true }) : inv.created_at}</p>
        </div>
        <span class="pill ${inv.status === "paid" ? "ok" : inv.status === "awaiting_review" ? "warn" : ""}">${STATUS[inv.status] || inv.status}</span>
      </div>
      ${actions}
    `;
    list.append(card);
  }
  list.querySelectorAll("[data-confirm]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("پرداخت تأیید و پلن اعمال شود؟")) return;
      try {
        await api(`/api/admin/invoices/${btn.dataset.confirm}/confirm`, { method: "POST", body: {} });
        toast("پلن فعال شد", "ok");
        load();
      } catch (err) {
        toast(err.message, "err");
      }
    };
  });
  list.querySelectorAll("[data-reject]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("فاکتور رد شود؟")) return;
      try {
        await api(`/api/admin/invoices/${btn.dataset.reject}/reject`, { method: "POST", body: {} });
        toast("رد شد", "ok");
        load();
      } catch (err) {
        toast(err.message, "err");
      }
    };
  });
}

async function load() {
  const status = filter.value;
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  try {
    const data = await api(`/api/admin/invoices${q}`);
    render(data.invoices || []);
  } catch (err) {
    toast(err.message, "err");
  }
}

filter.onchange = load;
bindLogout();
load();
