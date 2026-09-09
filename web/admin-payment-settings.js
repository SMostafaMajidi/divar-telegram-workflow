const form = $("#pay-form");
const preview = $("#card-preview");

function currentPayment() {
  return {
    card_number: form.card_number.value,
    card_holder: form.card_holder.value,
    bank_name: form.bank_name.value,
    sheba: form.sheba.value,
    note: form.note.value,
    support_telegram: form.support_telegram.value,
    support_url: form.support_telegram.value
      ? `https://t.me/${form.support_telegram.value.replace(/^@/, "")}`
      : "",
    configured: !!(form.card_number.value.trim() && form.card_holder.value.trim()),
  };
}

function refreshPreview() {
  renderBankCard(preview, currentPayment());
}

async function load() {
  const data = await api("/api/admin/payment-settings");
  const p = data.payment || {};
  form.card_number.value = p.card_number || "";
  form.card_holder.value = p.card_holder || "";
  form.bank_name.value = p.bank_name || "";
  form.sheba.value = p.sheba || "";
  form.support_telegram.value = p.support_telegram || "";
  form.note.value = p.note || "";
  renderBankCard(preview, p);
}

["input", "change"].forEach((evt) => {
  form.addEventListener(evt, () => refreshPreview());
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const data = await api("/api/admin/payment-settings", {
      method: "POST",
      body: {
        card_number: form.card_number.value.trim(),
        card_holder: form.card_holder.value.trim(),
        bank_name: form.bank_name.value.trim(),
        sheba: form.sheba.value.trim(),
        support_telegram: form.support_telegram.value.trim(),
        note: form.note.value.trim(),
      },
    });
    toast("تنظیمات پرداخت ذخیره شد", "ok");
    renderBankCard(preview, data.payment);
  } catch (err) {
    toast(err.message, "err");
  }
});

bindLogout();
load().catch((err) => toast(err.message, "err"));
