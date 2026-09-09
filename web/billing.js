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

let paymentState = {};
let messengersState = [];

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

function baleLinked() {
  return (messengersState || []).some((m) => m.channel === "bale" && m.linked);
}

function baleDeepLink() {
  const m = (messengersState || []).find((x) => x.channel === "bale");
  return (m && m.deep_link) || "";
}

function renderPay(payment) {
  paymentState = payment || {};
  const parts = [];
  if (paymentState.bale_wallet_ready) {
    parts.push(`<div class="pay-method">
      <h3>پرداخت با کیف‌پول بله</h3>
      <p class="meta">فاکتور باز را انتخاب کنید و دکمه «پرداخت با بله» را بزنید؛ درخواست پول در چت بله برایتان می‌آید و بعد از پرداخت، اشتراک خودکار فعال می‌شود.</p>
      ${
        baleLinked()
          ? `<p class="hint ok-hint">حساب بله وصل است.</p>`
          : `<p class="hint">ابتدا بله را در <a href="/app">پنل</a> وصل کنید${
              baleDeepLink() ? ` یا <a href="${baleDeepLink()}" target="_blank" rel="noreferrer">همین‌جا باز کنید</a>` : ""
            }.</p>`
      }
    </div>`);
  }
  if (paymentState.configured) {
    parts.push(`<div class="pay-method">
      <h3>پرداخت کارت‌به‌کارت</h3>
      <div id="bank-card-mount"></div>
    </div>`);
  }
  if (!parts.length) {
    payInfo.innerHTML = `<p class="empty">روش پرداختی تنظیم نشده است.</p>`;
    return;
  }
  payInfo.innerHTML = parts.join("");
  const mount = document.getElementById("bank-card-mount");
  if (mount) renderBankCard(mount, paymentState);
}

function receiptDropHtml(inv) {
  const inputId = `receipt-${inv.id}`;
  const baleBtn =
    paymentState.bale_wallet_ready && inv.status === "pending"
      ? `<button class="primary small" type="button" data-bale="${inv.id}">پرداخت با بله</button>`
      : "";
  return `<div class="receipt-upload">
    ${baleBtn ? `<div class="row pay-bale-row">${baleBtn}<span class="meta">یا کارت‌به‌کارت:</span></div>` : ""}
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
    <button class="ghost small" type="button" data-paid="${inv.id}">ثبت رسید و ارسال برای بررسی</button>
    <p class="hint">فیش را اینجا آپلود کنید؛ نیازی به ارسال در تلگرام نیست.</p>
  </div>`;
}

function methodLabel(inv) {
  if (inv.payment_method === "bale_wallet") return " · کیف‌پول بله";
  if (inv.payment_method === "card") return " · کارت‌به‌کارت";
  return "";
}

function showBalePayNotice(card, openUrl) {
  if (!card) return;
  let box = card.querySelector("[data-bale-notice]");
  if (!box) {
    box = document.createElement("div");
    box.className = "bale-pay-notice";
    box.dataset.baleNotice = "1";
    const mount = card.querySelector(".receipt-upload") || card;
    mount.prepend(box);
  }
  box.innerHTML = `
    <strong>الان به بله بروید</strong>
    <p>درخواست پول داخل چت بازوی ما ارسال شد. همان پیام را باز کنید و پرداخت را تکمیل کنید؛ اشتراک خودکار فعال می‌شود.</p>
    <a class="primary small" href="${openUrl}" target="_blank" rel="noreferrer">باز کردن بله</a>
  `;
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
          <span>شناسه واریز: <b dir="ltr">${inv.ref_code}</b>${methodLabel(inv)}</span>
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
  list.querySelectorAll("[data-bale]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!baleLinked()) {
        const link = baleDeepLink();
        toast(link ? "اول بله را وصل کنید" : "حساب بله وصل نیست", "err");
        if (link) window.open(link, "_blank", "noopener");
        return;
      }
      btn.disabled = true;
      const wrap = btn.closest(".invoice-card");
      try {
        const data = await api(`/api/invoices/${btn.dataset.bale}/pay-bale`, {
          method: "POST",
          body: {},
        });
        const openUrl = data?.bale?.open_url || baleDeepLink() || "https://ble.ir/";
        showBalePayNotice(wrap, openUrl);
        toast("فاکتور به بله ارسال شد — الان همان‌جا پرداخت کنید.", "ok");
        window.open(openUrl, "_blank", "noopener");
        btn.disabled = false;
        btn.textContent = "ارسال مجدد به بله";
      } catch (err) {
        toast(err.message, "err");
        btn.disabled = false;
      }
    });
  });
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
    const [inv, pay, messengers] = await Promise.all([
      api("/api/invoices"),
      api("/api/payment-info"),
      api("/api/messengers").catch(() => ({ messengers: [] })),
    ]);
    messengersState = messengers.messengers || [];
    renderPay(pay.payment);
    renderInvoices(inv.invoices || []);
    const hash = location.hash.replace("#", "");
    if (hash) document.getElementById(hash)?.scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    toast(err.message, "err");
  }
}

boot();
