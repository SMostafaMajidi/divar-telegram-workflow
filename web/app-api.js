const sample = document.getElementById("sample");
const feedLink = document.getElementById("feed-link");
const toast = document.getElementById("toast");

fetch("/api/me", { credentials: "same-origin" })
  .then(async (res) => {
    if (res.status === 401) {
      location.href = "/app/login";
      return null;
    }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "خطا");
    return data.user;
  })
  .then((user) => {
    if (!user) return;
    const userName = user.login_username || "USERNAME";
    sample.textContent = [
      "curl -u '" + userName + ":YOUR_PASSWORD' \\",
      "  '" + location.origin + "/api/v1/listings?limit=20'",
    ].join("\n");
    const slug = user.public_slug || user.login_username;
    if (slug) {
      feedLink.innerHTML = `فید عمومی: <a href="/u/${slug}" target="_blank">/u/${slug}</a>`;
    }
  })
  .catch((err) => {
    toast.hidden = false;
    toast.className = "toast err";
    toast.textContent = err.message || "خطا";
  });
