function formatCardNumber(raw) {
  const digits = String(raw || "").replace(/\D/g, "").slice(0, 16);
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ").trim();
}

function formatSheba(raw) {
  const clean = String(raw || "").replace(/\s/g, "").toUpperCase();
  if (!clean) return "";
  return clean.replace(/(.{4})(?=.)/g, "$1 ").trim();
}

function copyText(text, onDone) {
  const value = String(text || "");
  const done = () => onDone && onDone();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(value).then(done).catch(() => {
      window.prompt("کپی کنید:", value);
      done();
    });
    return;
  }
  const area = document.createElement("textarea");
  area.value = value;
  document.body.append(area);
  area.select();
  document.execCommand("copy");
  area.remove();
  done();
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
  const bank = payment.bank_name || "کارت بانکی";
  const shebaRaw = String(payment.sheba || "").replace(/\s/g, "").toUpperCase();
  const shebaFmt = formatSheba(shebaRaw);
  const shebaBlock = shebaRaw
    ? `<div class="bank-card-sheba">
        <span class="bank-card-label">شبا</span>
        <strong class="bank-card-sheba-num" data-raw="${shebaRaw}" dir="ltr">${shebaFmt}</strong>
        <button type="button" class="bank-card-copy ghost-copy" data-copy-sheba>کپی شبا</button>
      </div>`
    : "";
  target.innerHTML = `
    <div class="bank-card" dir="ltr">
      <div class="bank-card-top">
        <span class="bank-card-chip" aria-hidden="true"></span>
        <span class="bank-card-bank">${bank}</span>
      </div>
      <div class="bank-card-number" data-raw="${String(payment.card_number || "").replace(/\D/g, "")}">${number}</div>
      ${shebaBlock}
      <div class="bank-card-bottom">
        <div>
          <span class="bank-card-label">به نام</span>
          <strong class="bank-card-holder">${holder}</strong>
        </div>
        <button type="button" class="bank-card-copy" data-copy-card>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          <span data-copy-label>کپی شماره کارت</span>
        </button>
      </div>
    </div>
    ${payment.note ? `<p class="meta bank-card-note">${payment.note}</p>` : ""}
    ${payment.support_url ? `<p class="meta"><a href="${payment.support_url}" target="_blank" rel="noreferrer">پشتیبانی تلگرام</a></p>` : ""}
  `;
  const copyBtn = target.querySelector("[data-copy-card]");
  const copyLabel = copyBtn?.querySelector("[data-copy-label]");
  copyBtn?.addEventListener("click", () => {
    const digits = String(payment.card_number || "").replace(/\D/g, "");
    copyText(digits, () => {
      if (!copyLabel) return;
      copyLabel.textContent = "کپی شد!";
      setTimeout(() => {
        copyLabel.textContent = "کپی شماره کارت";
      }, 1800);
    });
  });
  const shebaBtn = target.querySelector("[data-copy-sheba]");
  shebaBtn?.addEventListener("click", () => {
    copyText(shebaRaw, () => {
      shebaBtn.textContent = "کپی شد!";
      setTimeout(() => {
        shebaBtn.textContent = "کپی شبا";
      }, 1800);
    });
  });
}

function bindReceiptDrop(root) {
  if (!root) return;
  const input = root.querySelector('input[type="file"]');
  const title = root.querySelector("[data-drop-title]");
  const preview = root.querySelector("[data-drop-preview]");
  if (!input) return;
  root._pickedFile = null;

  function showFile(file) {
    if (!file) return;
    root._pickedFile = file;
    if (title) title.textContent = file.name;
    if (!preview) return;
    if (file.type && file.type.startsWith("image/")) {
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
    } else {
      preview.hidden = true;
      preview.removeAttribute("src");
    }
  }

  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    showFile(file);
  });
  ["dragenter", "dragover"].forEach((ev) => {
    root.addEventListener(ev, (e) => {
      e.preventDefault();
      root.classList.add("is-dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    root.addEventListener(ev, (e) => {
      e.preventDefault();
      root.classList.remove("is-dragover");
    });
  });
  root.addEventListener("drop", (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (!files || !files.length) return;
    showFile(files[0]);
  });
}

function pickedReceiptFile(wrap) {
  const drop = wrap?.querySelector("[data-drop]");
  if (drop && drop._pickedFile) return drop._pickedFile;
  const fileInput = wrap?.querySelector("[data-file]");
  return fileInput?.files?.[0] || null;
}
