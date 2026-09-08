/** Jalali date helpers for fa-IR UI (no external deps). */

const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const LATIN_DIGITS = "0123456789";

function toLatinDigits(value) {
  return String(value ?? "").replace(/[۰-۹٠-٩]/g, (ch) => {
    const i = PERSIAN_DIGITS.indexOf(ch);
    if (i >= 0) return LATIN_DIGITS[i];
    const arabic = "٠١٢٣٤٥٦٧٨٩".indexOf(ch);
    return arabic >= 0 ? LATIN_DIGITS[arabic] : ch;
  });
}

function toPersianDigits(value) {
  return String(value ?? "").replace(/\d/g, (d) => PERSIAN_DIGITS[Number(d)]);
}

function parseDate(value) {
  if (!value) return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Display: ۱۴۰۴ شهریور ۱۷ */
function formatJalali(value, { withTime = false } = {}) {
  const d = parseDate(value);
  if (!d) return "—";
  const opts = {
    calendar: "persian",
    year: "numeric",
    month: "long",
    day: "numeric",
  };
  if (withTime) {
    opts.hour = "2-digit";
    opts.minute = "2-digit";
  }
  return new Intl.DateTimeFormat("fa-IR", opts).format(d);
}

/** Short: ۱۴۰۴/۰۶/۱۷ */
function formatJalaliShort(value) {
  const d = parseDate(value);
  if (!d) return "—";
  return new Intl.DateTimeFormat("fa-IR", {
    calendar: "persian",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(d)
    .replace(/‏/g, "")
    .replace(/[\/\-.]/g, "/");
}

function div(a, b) {
  return Math.trunc(a / b);
}

function gregorianToJalali(gy, gm, gd) {
  const g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  let jy;
  if (gy > 1600) {
    jy = 979;
    gy -= 1600;
  } else {
    jy = 0;
    gy -= 621;
  }
  const gy2 = gm > 2 ? gy + 1 : gy;
  let days =
    365 * gy +
    div(gy2 + 3, 4) -
    div(gy2 + 99, 100) +
    div(gy2 + 399, 400) -
    80 +
    gd +
    g_d_m[gm - 1];
  jy += 33 * div(days, 12053);
  days %= 12053;
  jy += 4 * div(days, 1461);
  days %= 1461;
  if (days > 365) {
    jy += div(days - 1, 365);
    days = (days - 1) % 365;
  }
  const jm = days < 186 ? 1 + div(days, 31) : 7 + div(days - 186, 30);
  const jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
  return { jy, jm, jd };
}

function jalaliToGregorian(jy, jm, jd) {
  let gy;
  if (jy > 979) {
    gy = 1600;
    jy -= 979;
  } else {
    gy = 621;
  }
  const days =
    365 * jy +
    div(jy, 33) * 8 +
    div((jy % 33) + 3, 4) +
    78 +
    jd +
    (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
  gy += 400 * div(days, 146097);
  let dayCount = days % 146097;
  if (dayCount >= 36525) {
    gy += 100 * div(--dayCount, 36524);
    dayCount %= 36524;
    if (dayCount >= 365) dayCount += 1;
  }
  gy += 4 * div(dayCount, 1461);
  dayCount %= 1461;
  if (dayCount >= 366) {
    gy += div(dayCount - 1, 365);
    dayCount = (dayCount - 1) % 365;
  }
  const sal_a = [
    0,
    31,
    (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0 ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  let gm = 0;
  while (gm < 13 && dayCount >= sal_a[gm]) {
    dayCount -= sal_a[gm];
    gm += 1;
  }
  return { gy, gm, gd: dayCount + 1 };
}

/** Value for text inputs: 1404/06/17 (latin digits) */
function toJalaliInput(iso) {
  const d = parseDate(iso);
  if (!d) return "";
  const { jy, jm, jd } = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  return `${jy}/${String(jm).padStart(2, "0")}/${String(jd).padStart(2, "0")}`;
}

function isJalaliLeap(jy) {
  const a = ((jy - (jy > 0 ? 474 : 473)) % 2820 + 2820) % 2820 + 474;
  return ((a + 38) * 682) % 2816 < 682;
}

function jalaliMonthLength(jy, jm) {
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  return isJalaliLeap(jy) ? 30 : 29;
}

const JALALI_MONTHS = [
  "فروردین",
  "اردیبهشت",
  "خرداد",
  "تیر",
  "مرداد",
  "شهریور",
  "مهر",
  "آبان",
  "آذر",
  "دی",
  "بهمن",
  "اسفند",
];
const JALALI_WEEKDAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

function parseJalaliParts(value) {
  const raw = toLatinDigits(value).trim().replace(/[-\.]/g, "/");
  if (!raw) return null;
  const m = raw.match(/^(\d{3,4})\s*\/\s*(\d{1,2})\s*\/\s*(\d{1,2})$/);
  if (!m) return null;
  const jy = Number(m[1]);
  const jm = Number(m[2]);
  const jd = Number(m[3]);
  if (jm < 1 || jm > 12 || jd < 1 || jd > jalaliMonthLength(jy, jm)) return null;
  return { jy, jm, jd };
}

function todayJalali() {
  const now = new Date();
  return gregorianToJalali(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

function jalaliWeekday(jy, jm, jd) {
  const g = jalaliToGregorian(jy, jm, jd);
  const d = new Date(g.gy, g.gm - 1, g.gd);
  return (d.getDay() + 1) % 7; // Saturday = 0
}

/** Parse 1404/6/17 or ۱۴۰۴/۰۶/۱۷ → ISO end of day Asia/Tehran */
function fromJalaliInput(value) {
  const parts = parseJalaliParts(value);
  if (!String(value || "").trim()) return "";
  if (!parts) throw new Error("تاریخ را به صورت سال/ماه/روز شمسی وارد کنید");
  const { gy, gm, gd } = jalaliToGregorian(parts.jy, parts.jm, parts.jd);
  const y = String(gy).padStart(4, "0");
  const mo = String(gm).padStart(2, "0");
  const day = String(gd).padStart(2, "0");
  return `${y}-${mo}-${day}T23:59:59+03:30`;
}

function closeAllJalaliPickers() {
  document.querySelectorAll(".jalali-popover").forEach((el) => el.remove());
  document.querySelectorAll(".jalali-field.open").forEach((el) => el.classList.remove("open"));
}

function renderJalaliCalendar(popover, input, view) {
  const selected = parseJalaliParts(input.value) || todayJalali();
  const jy = view.jy;
  const jm = view.jm;
  const today = todayJalali();
  const firstWeekday = jalaliWeekday(jy, jm, 1);
  const daysInMonth = jalaliMonthLength(jy, jm);

  popover.replaceChildren();
  const head = document.createElement("div");
  head.className = "jalali-cal-head";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.className = "jalali-nav";
  prev.setAttribute("aria-label", "ماه قبل");
  prev.textContent = "‹";
  const next = document.createElement("button");
  next.type = "button";
  next.className = "jalali-nav";
  next.setAttribute("aria-label", "ماه بعد");
  next.textContent = "›";
  const title = document.createElement("div");
  title.className = "jalali-cal-title";
  title.textContent = `${JALALI_MONTHS[jm - 1]} ${toPersianDigits(jy)}`;
  head.append(prev, title, next);

  const week = document.createElement("div");
  week.className = "jalali-cal-week";
  for (const name of JALALI_WEEKDAYS) {
    const cell = document.createElement("span");
    cell.textContent = name;
    week.append(cell);
  }

  const grid = document.createElement("div");
  grid.className = "jalali-cal-grid";
  for (let i = 0; i < firstWeekday; i += 1) {
    grid.append(document.createElement("span"));
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "jalali-day";
    btn.textContent = toPersianDigits(day);
    if (jy === today.jy && jm === today.jm && day === today.jd) btn.classList.add("today");
    if (jy === selected.jy && jm === selected.jm && day === selected.jd) btn.classList.add("selected");
    btn.addEventListener("click", () => {
      input.value = `${jy}/${String(jm).padStart(2, "0")}/${String(day).padStart(2, "0")}`;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.dispatchEvent(new Event("input", { bubbles: true }));
      closeAllJalaliPickers();
    });
    grid.append(btn);
  }

  const foot = document.createElement("div");
  foot.className = "jalali-cal-foot";
  const todayBtn = document.createElement("button");
  todayBtn.type = "button";
  todayBtn.className = "ghost small";
  todayBtn.textContent = "امروز";
  todayBtn.addEventListener("click", () => {
    view.jy = today.jy;
    view.jm = today.jm;
    input.value = `${today.jy}/${String(today.jm).padStart(2, "0")}/${String(today.jd).padStart(2, "0")}`;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    renderJalaliCalendar(popover, input, view);
  });
  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "ghost small";
  clearBtn.textContent = "پاک کردن";
  clearBtn.addEventListener("click", () => {
    input.value = "";
    input.dispatchEvent(new Event("change", { bubbles: true }));
    closeAllJalaliPickers();
  });
  foot.append(todayBtn, clearBtn);

  popover.append(head, week, grid, foot);

  prev.addEventListener("click", (e) => {
    e.stopPropagation();
    if (view.jm === 1) {
      view.jm = 12;
      view.jy -= 1;
    } else view.jm -= 1;
    renderJalaliCalendar(popover, input, view);
  });
  next.addEventListener("click", (e) => {
    e.stopPropagation();
    if (view.jm === 12) {
      view.jm = 1;
      view.jy += 1;
    } else view.jm += 1;
    renderJalaliCalendar(popover, input, view);
  });
}

function openJalaliPicker(field, input) {
  closeAllJalaliPickers();
  const parts = parseJalaliParts(input.value) || todayJalali();
  const view = { jy: parts.jy, jm: parts.jm };
  const popover = document.createElement("div");
  popover.className = "jalali-popover";
  popover.addEventListener("click", (e) => e.stopPropagation());
  field.append(popover);
  field.classList.add("open");
  renderJalaliCalendar(popover, input, view);
}

function bindJalaliPickers(root = document) {
  root.querySelectorAll(".jalali-field").forEach((field) => {
    if (field.dataset.bound) return;
    field.dataset.bound = "1";
    const input = field.querySelector("input");
    const trigger = field.querySelector(".jalali-trigger");
    if (!input) return;
    input.setAttribute("readonly", "readonly");
    input.setAttribute("autocomplete", "off");
    const open = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (field.classList.contains("open")) closeAllJalaliPickers();
      else openJalaliPicker(field, input);
    };
    trigger?.addEventListener("click", open);
    input.addEventListener("click", open);
    input.addEventListener("focus", () => {
      if (!field.classList.contains("open")) openJalaliPicker(field, input);
    });
  });
  if (!document.documentElement.dataset.jalaliPickerGlobal) {
    document.documentElement.dataset.jalaliPickerGlobal = "1";
    document.addEventListener("click", closeAllJalaliPickers);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllJalaliPickers();
    });
  }
}

function bindNavMenus(root = document) {
  root.querySelectorAll(".nav-menu").forEach((menu) => {
    const trigger = menu.querySelector(".menu-trigger");
    const panel = menu.querySelector(".menu-dropdown");
    if (!trigger || !panel) return;
    const close = () => {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      menu.classList.remove("open");
    };
    const open = () => {
      document.querySelectorAll(".nav-menu.open").forEach((other) => {
        if (other !== menu) {
          other.classList.remove("open");
          const p = other.querySelector(".menu-dropdown");
          const t = other.querySelector(".menu-trigger");
          if (p) p.hidden = true;
          if (t) t.setAttribute("aria-expanded", "false");
        }
      });
      panel.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      menu.classList.add("open");
    };
    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      if (panel.hidden) open();
      else close();
    });
    panel.addEventListener("click", (e) => e.stopPropagation());
    document.addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
  });
}
