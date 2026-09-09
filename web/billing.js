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
  payInfo.innerHTML = `<h3>پرداخت کارت‌به‌کارت</h3><div id="bank-card-mount"></div>`;
  renderBankCard(document.getElementById("bank-card-mount"), payment || {});
}

function receiptDropHtml(inv) {
  const inputId = `receipt-${inv.id}`;
  return `<div class="receipt-upload">
    <p class="pay-steps">۱) مبلغ را به کارت بالا واریز کنید و شناسه واریز را در توضیحات بنویسید &nbsp;·&nbsp; ۲) تصویر رسید را بارگذاری کنید</p>
    <label class="receipt-drop" data-drop for="${inputId}">
      <input id="${inputId}" type="file" data-file accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf">
      <span class="receipt-drop-icon" aria-hidden="true">
        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      </span>
      <span class="receipt-drop-title" data-drop-title>برای انتخاب فایل کلیک کنید یا اینجا رها کنید</span>
      <span class="receipt-drop-hint">JPG، PNG، WEBP یا PDF</span>
      <img class="receipt-preview-img" data-drop-preview alt="" hidden>
    </label>
    <input data-note placeholder="توضیح اختیاری" value="${inv.payer_note || ""}">
    <button class="primary small" type="button" data-paid="${inv.id}">ثبت رسید و ارسال برای بررسی</button>
    <p class="hint">فیش را اینجا آپلود کنید؛ نیازی به ارسال در تلگرام نیست.</p>
  </div>`;
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
    card.innerHTML = `
      <div class="pay-amount-box">
        <span class="pay-amount-label">${inv.plan_name}</span>
        <strong class="pay-amount-value">${inv.amount_label}</strong>
        <div class="pay-amount-meta">
          <span>شناسه واریز: <b dir="ltr">${inv.ref_code}</b></span>
          <span class="pill ${inv.status === "paid" ? "ok" : inv.status === "rejected" ? "warn" : ""}">${STATUS[inv.status] || inv.status}</span>
        </div>
      </div>
      ${receiptLink}
      ${canUpload ? receiptDropHtml(inv) : ""}
    `;
    list.append(card);
    if (canUpload) {
      const drop = card.querySelector("[data-drop]");
      bindReceiptDrop(drop);
    }
  }
  list.querySelectorAll("[data-paid]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.paid;
      const wrap = btn.closest(".invoice-card");
      const note = wrap.querySelector("[data-note]")?.value || "";
      const file = pickedReceiptFile(wrap);
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
        toast("رسید ثبت شد؛ منتظر تأیید ادمین بمانید.", "ok");
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
