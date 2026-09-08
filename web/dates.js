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

/** Parse 1404/6/17 or ۱۴۰۴/۰۶/۱۷ → ISO end of day Asia/Tehran */
function fromJalaliInput(value) {
  const raw = toLatinDigits(value).trim().replace(/[-\.]/g, "/");
  if (!raw) return "";
  const m = raw.match(/^(\d{3,4})\s*\/\s*(\d{1,2})\s*\/\s*(\d{1,2})$/);
  if (!m) throw new Error("تاریخ را به صورت سال/ماه/روز شمسی وارد کنید");
  const jy = Number(m[1]);
  const jm = Number(m[2]);
  const jd = Number(m[3]);
  if (jm < 1 || jm > 12 || jd < 1 || jd > 31) throw new Error("تاریخ شمسی نامعتبر است");
  const { gy, gm, gd } = jalaliToGregorian(jy, jm, jd);
  const y = String(gy).padStart(4, "0");
  const mo = String(gm).padStart(2, "0");
  const day = String(gd).padStart(2, "0");
  return `${y}-${mo}-${day}T23:59:59+03:30`;
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
