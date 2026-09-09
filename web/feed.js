const username = location.pathname.split("/").filter(Boolean).pop();
const results = document.getElementById("results");
const title = document.getElementById("title");
const toast = document.getElementById("toast");

title.textContent = `@${username}`;

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

fetch(`/api/public/feed/${encodeURIComponent(username)}`)
  .then((r) => r.json())
  .then((data) => {
    if (data.error) throw new Error(data.error);
    const listings = data.listings || [];
    results.replaceChildren();
    if (!listings.length) {
      results.append(el("p", { class: "empty", text: "هنوز آگهی‌ای در این صفحه ثبت نشده است." }));
      return;
    }
    for (const item of listings) {
      results.append(
        el("a", { class: "ad", href: item.url, target: "_blank", rel: "noreferrer" }, [
          item.image_url ? el("img", { src: item.image_url, alt: item.title }) : el("div"),
          el("div", { class: "pad" }, [
            el("strong", { text: item.title }),
            el("div", { class: "price", text: item.price || "توافقی" }),
            el("div", { class: "loc", text: [item.location, item.filter_name].filter(Boolean).join(" · ") }),
          ]),
        ])
      );
    }
  })
  .catch((err) => {
    toast.hidden = false;
    toast.className = "toast err";
    toast.textContent = err.message || "خطا";
  });
