const form = document.getElementById("login-form");
const toast = document.getElementById("toast");

function showToast(message, kind = "err") {
  toast.hidden = !message;
  toast.className = `toast ${kind}`.trim();
  toast.textContent = message || "";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  showToast("");
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        username: data.get("username"),
        password: data.get("password"),
      }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.error || "ورود ناموفق بود.");
    location.href = "/app";
  } catch (err) {
    showToast(err.message || "خطا");
  }
});

fetch("/api/status")
  .then((r) => r.json())
  .then((s) => {
    const el = document.getElementById("bot-hint");
    if (s.bot_username) {
      el.innerHTML = `ربات ثبت‌نام: <a href="https://t.me/${s.bot_username}" target="_blank">@${s.bot_username}</a>`;
    }
  })
  .catch(() => {});
