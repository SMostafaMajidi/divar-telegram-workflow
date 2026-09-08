const form = $("#pay-form");

async function load() {
  const data = await api("/api/admin/payment-settings");
  const p = data.payment || {};
  form.card_number.value = p.card_number || "";
  form.card_holder.value = p.card_holder || "";
  form.support_telegram.value = p.support_telegram || "";
  form.note.value = p.note || "";
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/admin/payment-settings", {
      method: "POST",
      body: {
        card_number: form.card_number.value.trim(),
        card_holder: form.card_holder.value.trim(),
        support_telegram: form.support_telegram.value.trim(),
        note: form.note.value.trim(),
      },
    });
    toast("تنظیمات پرداخت ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

bindLogout();
load().catch((err) => toast(err.message, "err"));
