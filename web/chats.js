const $ = (sel, root = document) => root.querySelector(sel);
const CHANNEL_LABELS = { telegram: "تلگرام", bale: "بله", eitaa: "ایتا" };

const state = { user: null, messengers: [], chats: [], eitaa: null, caps: {} };

const els = {
  toast: $("#toast"),
  messengerList: $("#messenger-list"),
  chatList: $("#chat-list"),
  eitaaSetup: $("#eitaa-setup"),
  eitaaLocked: $("#eitaa-locked"),
  eitaaInstructions: $("#eitaa-instructions"),
  eitaaToken: $("#eitaa-token"),
  eitaaTokenSave: $("#eitaa-token-save"),
  eitaaTokenClear: $("#eitaa-token-clear"),
  eitaaTokenStatus: $("#eitaa-token-status"),
  eitaaChannelId: $("#eitaa-channel-id"),
  eitaaChannelAdd: $("#eitaa-channel-add"),
  eitaaChannelList: $("#eitaa-channel-list"),
};

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child == null) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
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
    throw new Error("نیاز به ورود");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "خطا");
  return data;
}

function toast(message, kind = "") {
  els.toast.hidden = !message;
  els.toast.className = `toast ${kind}`.trim();
  els.toast.textContent = message || "";
}

function chatLabel(chat) {
  const kinds = { private: "خصوصی", group: "گروه", supergroup: "گروه", channel: "کانال" };
  const kind = kinds[chat.type] || "";
  const channel = CHANNEL_LABELS[chat.channel] || chat.channel || "";
  const name = chat.name || (chat.username ? `@${chat.username}` : chat.id);
  const base = kind ? `${name} · ${kind}` : String(name);
  return channel ? `${channel} · ${base}` : base;
}

function renderMessengers() {
  els.messengerList.replaceChildren();
  const list = (state.messengers || []).filter(
    (m) => m.channel !== "eitaa" && m.enabled !== false && !m.plan_locked,
  );
  if (!list.length) {
    els.messengerList.append(el("p", { class: "meta", text: "ربات فعالی برای پلن شما نیست." }));
    return;
  }
  for (const m of list) {
    const attrs = { class: `messenger-card ${m.linked ? "linked" : ""}` };
    if (m.deep_link) {
      attrs.href = m.deep_link;
      attrs.target = "_blank";
      attrs.rel = "noreferrer";
    }
    els.messengerList.append(
      el(m.deep_link ? "a" : "div", attrs, [
        el("strong", { text: m.label }),
        el("span", {
          class: "meta",
          text: m.linked ? "متصل است" : "برای اتصال استارت/لاگین کنید",
        }),
      ]),
    );
  }
}

function renderChats() {
  els.chatList.replaceChildren();
  if (!state.chats.length) {
    els.chatList.append(el("p", { class: "meta", text: "هنوز چتی کشف نشده." }));
    return;
  }
  for (const chat of state.chats) {
    els.chatList.append(el("div", { class: "dest-chip" }, [el("span", { text: chatLabel(chat) })]));
  }
}

function renderEitaa() {
  const allowed = !!state.caps.allow_eitaa;
  if (els.eitaaSetup) els.eitaaSetup.hidden = !allowed;
  if (els.eitaaLocked) els.eitaaLocked.hidden = allowed;
  if (!allowed) return;
  const eitaa = state.eitaa || {};
  if (els.eitaaInstructions) {
    els.eitaaInstructions.replaceChildren();
    for (const step of eitaa.instructions || []) {
      els.eitaaInstructions.append(el("li", { text: step }));
    }
  }
  if (els.eitaaTokenStatus) {
    els.eitaaTokenStatus.textContent = eitaa.configured
      ? `توکن ذخیره شده: ${eitaa.token_masked || "••••"}`
      : "هنوز توکنی ذخیره نشده.";
  }
  if (els.eitaaTokenClear) els.eitaaTokenClear.hidden = !eitaa.configured;
  if (els.eitaaChannelList) {
    els.eitaaChannelList.replaceChildren();
    const channels = eitaa.channels || [];
    if (!channels.length) {
      els.eitaaChannelList.append(el("p", { class: "meta", text: "کانالی اضافه نشده." }));
    } else {
      for (const chat of channels) {
        els.eitaaChannelList.append(
          el("div", { class: "dest-chip" }, [
            el("span", { text: chatLabel(chat) }),
            el("button", {
              type: "button",
              class: "ghost small",
              text: "حذف",
              onClick: async () => {
                try {
                  const data = await api(`/api/eitaa/channels/${encodeURIComponent(chat.id)}`, {
                    method: "DELETE",
                  });
                  state.eitaa = data;
                  renderEitaa();
                  await boot();
                  toast("کانال حذف شد", "ok");
                } catch (err) {
                  toast(err.message, "err");
                }
              },
            }),
          ]),
        );
      }
    }
  }
}

els.eitaaTokenSave?.addEventListener("click", async () => {
  const token = String(els.eitaaToken?.value || "").trim();
  if (!token) return toast("توکن را وارد کنید", "err");
  try {
    const data = await api("/api/eitaa", { method: "POST", body: { token } });
    if (els.eitaaToken) els.eitaaToken.value = "";
    state.eitaa = data.eitaa || data;
    renderEitaa();
    await boot();
    toast("توکن ذخیره شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.eitaaTokenClear?.addEventListener("click", async () => {
  if (!confirm("توکن حذف شود؟")) return;
  try {
    state.eitaa = await api("/api/eitaa", { method: "DELETE" });
    renderEitaa();
    toast("حذف شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

els.eitaaChannelAdd?.addEventListener("click", async () => {
  const chatId = String(els.eitaaChannelId?.value || "").trim();
  if (!chatId) return toast("شناسه کانال را وارد کنید", "err");
  try {
    const data = await api("/api/eitaa/channels", { method: "POST", body: { chat_id: chatId } });
    if (els.eitaaChannelId) els.eitaaChannelId.value = "";
    state.eitaa = data.eitaa || data;
    renderEitaa();
    await boot();
    toast("کانال اضافه شد", "ok");
  } catch (err) {
    toast(err.message, "err");
  }
});

async function boot() {
  try {
    const [me, messengers, chats, eitaa] = await Promise.all([
      api("/api/me"),
      api("/api/messengers"),
      api("/api/chats"),
      api("/api/eitaa").catch(() => ({})),
    ]);
    state.user = me.user;
    state.caps = me.user?.capabilities || {};
    state.messengers = messengers.messengers || [];
    state.chats = chats.chats || [];
    state.eitaa = eitaa;
    renderMessengers();
    renderChats();
    renderEitaa();
  } catch (err) {
    location.replace("/");
  }
}

boot();
