const $ = (s) => document.querySelector(s);
const toastEl = $("#toast");
const list = $("#list");
const payInfo = $("#pay-info");

const STATUS = {
  pending: "در انتظار پرداخت",
  awaiting_review: "در صف تأیید",
  paid: "پرداخت‌شده",
  rejected: "رد شده",
  cancelled: "لغو شده",
};

function toast(msg, kind = "") {
  toastEl.hidden = !msg;
  toastEl.className = `toast ${kind}`.trim();
  toastEl.textContent = msg || "";
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
    throw new Error("ورود لازم است");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "خطا");
  return data;
}

function renderPay(payment) {
  if (!payment) return;
  if (payment.configured) {
    payInfo.innerHTML = `
      <h3>کارت مقصد</h3>
      <p class="meta">${payment.note || ""}</p>
      <p><b>${payment.card_holder}</b></p>
      <p class="mono" dir="ltr">${payment.card_number}</p>
      ${payment.support_url ? `<p class="meta"><a href="${payment.support_url}" target="_blank">پشتیبانی</a></p>` : ""}
    `;
  } else {
    payInfo.innerHTML = `<p class="meta">کارت هنوز تنظیم نشده؛ بعد از صدور فاکتور با پشتیبانی هماهنگ کنید.</p>`;
  }
}

function renderInvoices(invoices) {
  list.replaceChildren();
  if (!invoices.length) {
    list.innerHTML = `<p class="empty">فاکتوری نیست. از <a href="/pricing">صفحه پلن‌ها</a> خرید را شروع کنید.</p>`;
    return;
  }
  for (const inv of invoices) {
    const card = document.createElement("article");
    card.className = "invoice-card";
    card.id = inv.id;
    const actions =
      inv.status === "pending" || inv.status === "awaiting_review"
        ? `<div class="row">
            <input data-note placeholder="کد پیگیری واریز (اختیاری)" value="${inv.payer_note || ""}">
            <button class="primary small" type="button" data-paid="${inv.id}">پرداخت کردم</button>
          </div>`
        : "";
    card.innerHTML = `
      <div class="card-top">
        <div>
          <h3>${inv.plan_name}</h3>
          <p class="meta">${inv.amount_label} · شناسه واریز: <b dir="ltr">${inv.ref_code}</b></p>
        </div>
        <span class="pill ${inv.status === "paid" ? "ok" : inv.status === "rejected" ? "warn" : ""}">${STATUS[inv.status] || inv.status}</span>
      </div>
      <p class="meta">شناسه واریز را در توضیحات کارت‌به‌کارت بنویسید تا سریع تأیید شود.</p>
      ${actions}
    `;
    list.append(card);
  }
  list.querySelectorAll("[data-paid]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.paid;
      const note = btn.closest(".invoice-card").querySelector("[data-note]")?.value || "";
      btn.disabled = true;
      try {
        await api(`/api/invoices/${id}/paid`, { method: "POST", body: { payer_note: note } });
        toast("ثبت شد؛ بعد از تأیید پشتیبانی پلن فعال می‌شود.", "ok");
        await boot();
      } catch (err) {
        toast(err.message, "err");
        btn.disabled = false;
      }
    });
  });
}

async function boot() {
  try {
    const [inv, pay] = await Promise.all([api("/api/invoices"), api("/api/payment-info")]);
    renderPay(pay.payment);
    renderInvoices(inv.invoices || []);
    const hash = location.hash.replace("#", "");
    if (hash) document.getElementById(hash)?.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    toast(err.message, "err");
  }
}

boot();
