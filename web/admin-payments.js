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
    const receipt = inv.has_receipt
      ? `<p class="meta"><a class="ghost small" href="/api/invoices/${inv.id}/receipt" target="_blank" rel="noreferrer">مشاهده فیش</a>${inv.receipt_name ? ` · ${inv.receipt_name}` : ""}</p>`
      : `<p class="meta">فیش آپلود نشده</p>`;
    const actions =
      inv.status === "pending" || inv.status === "awaiting_review"
        ? `<div class="row">
            <button class="primary small" type="button" data-confirm="${inv.id}" ${inv.has_receipt ? "" : "disabled"}>تأیید و فعال‌سازی پلن</button>
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
          <p class="meta">${inv.plan_name} · ${inv.amount_label} · شناسه <b dir="ltr">${inv.ref_code}</b>${
            inv.payment_method === "bale_wallet" ? " · بله" : inv.payment_method === "card" ? " · کارت" : ""
          }</p>
          <p class="meta">یوزرنیم: @${inv.login_username || "—"} · توضیح: ${inv.payer_note || "—"}</p>
          <p class="meta">${typeof formatJalali === "function" ? formatJalali(inv.created_at, { withTime: true }) : inv.created_at}</p>
        </div>
        <span class="pill ${inv.status === "paid" ? "ok" : inv.status === "awaiting_review" ? "warn" : ""}">${STATUS[inv.status] || inv.status}</span>
      </div>
      ${receipt}
      ${actions}
    `;
    list.append(card);
  }
  list.querySelectorAll("[data-confirm]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("پرداخت تأیید شود و حساب مشتری با انقضای پلن فعال گردد؟")) return;
      try {
        const data = await api(`/api/admin/invoices/${btn.dataset.confirm}/confirm`, {
          method: "POST",
          body: {},
        });
        const exp = data.user?.expires_at
          ? typeof formatJalali === "function"
            ? formatJalali(data.user.expires_at)
            : data.user.expires_at
          : "—";
        toast(`حساب فعال شد · پلن ${data.user?.plan_name || data.invoice?.plan_name || ""} · تا ${exp}`, "ok");
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
