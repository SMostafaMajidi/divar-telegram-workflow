const state = { status: {} };
const form = $("#settings-form");

function renderStatus() {
  form.poll_interval_minutes.value = state.status.poll_interval_minutes || 5;
  form.best_count.value = state.status.best_count || 5;
  form.send_photos.checked = !!state.status.send_photos;
  bindWatchControls(state);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    state.status = {
      ...state.status,
      ...(await api("/api/settings", {
        method: "PUT",
        body: {
          poll_interval_minutes: Number(form.poll_interval_minutes.value),
          best_count: Number(form.best_count.value),
          send_photos: form.send_photos.checked,
        },
      })),
    };
    renderStatus();
    toast("تنظیمات ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

async function boot() {
  bindLogout();
  try {
    state.status = await fetch("/api/status", { credentials: "same-origin" }).then((r) => r.json());
    renderStatus();
  } catch (err) {
    toast(err.message, "err");
  }
}

boot();
