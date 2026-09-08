const state = { user: null };
const userId = location.pathname.split("/").filter(Boolean).pop();

const els = {
  title: $("#page-title"),
  head: $("#user-head"),
  profile: $("#profile-form"),
  poll: $("#poll-form"),
  slotHint: $("#slot-hint"),
  rotate: $("#rotate-btn"),
  feed: $("#feed-link"),
  apiKey: $("#api-key"),
  deleteBtn: $("#delete-btn"),
};

function render() {
  const user = state.user;
  if (!user) return;
  const handle = user.login_username || user.telegram_username || user.id;
  els.title.textContent = `@${handle}`;
  document.title = `@${handle} — ادمین`;
  els.head.innerHTML = `
    <div class="card-top">
      <div>
        <p class="meta">${user.display_name || ""} · تلگرام: @${user.telegram_username || "—"}</p>
        <p class="meta">${user.filter_count || 0} فیلتر · ساخته‌شده: ${(user.created_at || "").slice(0, 10)}</p>
      </div>
      <div class="row">
        <span class="pill ${user.linked ? "ok" : "warn"}">${user.linked ? "متصل" : "منتظر ربات"}</span>
        <span class="pill ${user.active ? "ok" : ""}">${user.active ? "فعال" : "غیرفعال"}</span>
      </div>
    </div>
  `;
  els.profile.display_name.value = user.display_name || "";
  els.profile.ai_enabled.checked = !!user.ai_enabled;
  els.profile.active.checked = !!user.active;
  els.poll.poll_interval_minutes.value =
    user.poll_interval_minutes ?? user.effective_poll_interval_minutes ?? 5;
  els.poll.poll_offset_minutes.value = user.poll_offset_minutes ?? user.effective_poll_offset_minutes ?? 0;
  els.poll.best_count.value = user.best_count ?? user.effective_best_count ?? 5;
  els.slotHint.textContent = slotHint(user);
  els.feed.href = `/u/${user.public_slug || user.login_username || user.telegram_username}`;
  els.apiKey.textContent = user.api_key ? `API key: ${user.api_key}` : "";
}

els.profile.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const data = await api(`/api/admin/users/${userId}`, {
      method: "PUT",
      body: {
        display_name: els.profile.display_name.value,
        ai_enabled: els.profile.ai_enabled.checked,
        active: els.profile.active.checked,
      },
    });
    state.user = data.user;
    render();
    toast("اطلاعات ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.poll.addEventListener("submit", async (e) => {
  e.preventDefault();
  const interval = optionalNumber(els.poll.poll_interval_minutes.value);
  const offset = optionalNumber(els.poll.poll_offset_minutes.value);
  const best = optionalNumber(els.poll.best_count.value);
  if (interval == null || interval < 1) {
    toast("فاصله پایش را وارد کنید", "err");
    return;
  }
  if (offset == null || offset < 0) {
    toast("زمان پایه نامعتبر است", "err");
    return;
  }
  if (best == null || best < 1) {
    toast("تعداد آگهی برتر را وارد کنید", "err");
    return;
  }
  try {
    const data = await api(`/api/admin/users/${userId}`, {
      method: "PUT",
      body: {
        poll_interval_minutes: interval,
        poll_offset_minutes: offset,
        best_count: best,
      },
    });
    state.user = data.user;
    render();
    toast(`پایش ذخیره شد — ${(data.user.slot_preview || []).join("، ")}`, "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.rotate.onclick = async () => {
  if (!confirm("کلید API جدید ساخته شود؟ کلید قبلی از کار می‌افتد.")) return;
  try {
    const data = await api(`/api/admin/users/${userId}/rotate-key`, { method: "POST", body: {} });
    state.user = data.user;
    render();
    toast("کلید جدید ساخته شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
};

els.deleteBtn.onclick = async () => {
  const handle = state.user?.login_username || state.user?.telegram_username || userId;
  if (!confirm(`حساب @${handle} کامل حذف شود؟ این کار برگشت‌پذیر نیست.`)) return;
  if (!confirm("مطمئن هستید؟ فیلترها و داده‌های این مشتری پاک می‌شود.")) return;
  try {
    await api(`/api/admin/users/${userId}`, { method: "DELETE" });
    toast("حساب حذف شد", "ok");
    setTimeout(() => {
      location.href = "/admin";
    }, 600);
  } catch (err) {
    toast(err.message, "err");
  }
};

async function boot() {
  bindLogout();
  if (!userId) {
    toast("شناسه مشتری نامعتبر است", "err");
    return;
  }
  try {
    const data = await api(`/api/admin/users/${userId}`);
    state.user = data.user;
    render();
  } catch (err) {
    toast(err.message, "err");
  }
}

boot();
