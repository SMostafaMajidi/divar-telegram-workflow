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
  renderBankCard(payInfo, payment || {});
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
    const canUpload = inv.status === "pending" || inv.status === "awaiting_review";
    const receiptLink = inv.has_receipt
      ? `<p class="meta"><a href="/api/invoices/${inv.id}/receipt" target="_blank" rel="noreferrer">مشاهده فیش آپلودشده</a></p>`
      : "";
    const actions = canUpload
      ? `<div class="receipt-upload">
          <label class="meta">فیش واریز (عکس یا PDF)
            <input type="file" data-file accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf">
          </label>
          <input data-note placeholder="توضیح اختیاری" value="${inv.payer_note || ""}">
          <button class="primary small" type="button" data-paid="${inv.id}">ارسال فیش برای تأیید</button>
          <p class="hint">فیش را اینجا آپلود کنید؛ نیازی به ارسال در تلگرام نیست.</p>
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
      <p class="meta">مبلغ را کارت‌به‌کارت کنید و شناسه واریز را در توضیحات بنویسید، بعد فیش را آپلود کنید.</p>
      ${receiptLink}
      ${actions}
    `;
    list.append(card);
  }
  list.querySelectorAll("[data-paid]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.paid;
      const wrap = btn.closest(".invoice-card");
      const note = wrap.querySelector("[data-note]")?.value || "";
      const fileInput = wrap.querySelector("[data-file]");
      const file = fileInput?.files?.[0];
      if (!file) {
        toast("فیش واریز را انتخاب کنید", "err");
        return;
      }
      btn.disabled = true;
      try {
        const fd = new FormData();
        fd.append("receipt", file);
        fd.append("payer_note", note);
        const res = await fetch(`/api/invoices/${id}/paid`, {
          method: "POST",
          credentials: "same-origin",
          body: fd,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "خطا");
        toast("فیش ثبت شد؛ منتظر تأیید ادمین بمانید.", "ok");
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
