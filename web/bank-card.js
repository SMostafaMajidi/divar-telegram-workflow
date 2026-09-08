function formatCardNumber(raw) {
  const digits = String(raw || "").replace(/\D/g, "").slice(0, 16);
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ").trim();
}

function renderBankCard(target, payment = {}) {
  if (!target) return;
  const configured = !!(payment.card_number && payment.card_holder);
  if (!configured) {
    target.innerHTML = `<p class="meta">اطلاعات کارت هنوز تنظیم نشده است.</p>`;
    return;
  }
  const number = formatCardNumber(payment.card_number);
  const holder = payment.card_holder || "";
  target.innerHTML = `
    <div class="bank-card" dir="ltr">
      <div class="bank-card-chip" aria-hidden="true"></div>
      <p class="bank-card-label">Card Number</p>
      <p class="bank-card-number" id="bank-card-number-text">${number}</p>
      <div class="bank-card-footer">
        <div>
          <p class="bank-card-label">Card Holder</p>
          <p class="bank-card-holder">${holder}</p>
        </div>
        <button type="button" class="bank-card-copy" data-copy-card>کپی شماره</button>
      </div>
    </div>
    ${payment.note ? `<p class="meta bank-card-note">${payment.note}</p>` : ""}
    ${payment.support_url ? `<p class="meta"><a href="${payment.support_url}" target="_blank" rel="noreferrer">پشتیبانی تلگرام</a></p>` : ""}
  `;
  const btn = target.querySelector("[data-copy-card]");
  btn?.addEventListener("click", async () => {
    const digits = String(payment.card_number || "").replace(/\D/g, "");
    try {
      await navigator.clipboard.writeText(digits);
      btn.textContent = "کپی شد";
      setTimeout(() => {
        btn.textContent = "کپی شماره";
      }, 1500);
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = digits;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      btn.textContent = "کپی شد";
      setTimeout(() => {
        btn.textContent = "کپی شماره";
      }, 1500);
    }
  });
}
