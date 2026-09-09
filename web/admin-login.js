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
    const res = await fetch("/api/admin/login", {
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
    location.href = "/admin";
  } catch (err) {
    showToast(err.message || "خطا");
  }
});
