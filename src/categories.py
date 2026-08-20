from __future__ import annotations

from typing import Any

# Divar postlist slugs that the search API still accepts.
TREE: list[dict[str, Any]] = [
    {
        "slug": "vehicles",
        "name": "وسایل نقلیه",
        "children": [
            {"slug": "light", "name": "سواری و وانت"},
            {"slug": "rental", "name": "اجاره خودرو"},
            {"slug": "classic", "name": "کلاسیک"},
            {"slug": "heavy", "name": "سنگین"},
            {"slug": "motorcycles", "name": "موتورسیکلت"},
            {"slug": "parts-accessories", "name": "قطعات و لوازم جانبی خودرو"},
            {"slug": "boat", "name": "قایق و جت‌اسکی"},
        ],
    },
    {
        "slug": "real-estate",
        "name": "املاک",
        "children": [
            {
                "slug": "residential-sell",
                "name": "فروش مسکونی",
                "children": [
                    {"slug": "apartment-sell", "name": "آپارتمان"},
                    {"slug": "house-villa-sell", "name": "خانه و ویلا"},
                    {"slug": "plot-old", "name": "زمین و کلنگی"},
                    {"slug": "presell", "name": "پیش‌فروش"},
                ],
            },
            {
                "slug": "residential-rent",
                "name": "اجاره مسکونی",
                "children": [
                    {"slug": "apartment-rent", "name": "آپارتمان"},
                    {"slug": "house-villa-rent", "name": "خانه و ویلا"},
                ],
            },
            {
                "slug": "commercial-sell",
                "name": "فروش اداری و تجاری",
                "children": [
                    {"slug": "office-sell", "name": "دفتر کار"},
                    {"slug": "shop-sell", "name": "مغازه"},
                    {"slug": "industry-agriculture-business-sell", "name": "صنعتی، کشاورزی و تجاری"},
                ],
            },
            {
                "slug": "commercial-rent",
                "name": "اجاره اداری و تجاری",
                "children": [
                    {"slug": "office-rent", "name": "دفتر کار"},
                    {"slug": "shop-rent", "name": "مغازه"},
                    {"slug": "industry-agriculture-business-rent", "name": "صنعتی، کشاورزی و تجاری"},
                ],
            },
            {"slug": "temporary-rent", "name": "اجاره کوتاه‌مدت"},
            {"slug": "real-estate-services", "name": "خدمات املاک"},
        ],
    },
    {
        "slug": "electronic-devices",
        "name": "کالای دیجیتال",
        "children": [
            {
                "slug": "mobile-tablet",
                "name": "موبایل و تبلت",
                "children": [
                    {"slug": "mobile-phones", "name": "گوشی موبایل"},
                    {"slug": "tablet", "name": "تبلت"},
                    {"slug": "mobile-tablet-accessories", "name": "لوازم جانبی"},
                    {"slug": "sim-card", "name": "سیم‌کارت"},
                ],
            },
            {
                "slug": "computers",
                "name": "رایانه",
                "children": [
                    {"slug": "laptops", "name": "لپ‌تاپ"},
                    {"slug": "desktops", "name": "کامپیوتر رومیزی"},
                    {"slug": "parts-and-accessories", "name": "قطعات و لوازم جانبی"},
                    {"slug": "modem-and-network-equipment", "name": "مودم و شبکه"},
                    {"slug": "printer-scaner-copier", "name": "پرینتر و اسکنر"},
                ],
            },
            {"slug": "game-consoles-and-video-games", "name": "کنسول بازی"},
            {"slug": "audio-video", "name": "صوتی و تصویری"},
            {"slug": "camera-camcoders", "name": "دوربین"},
            {"slug": "phone", "name": "تلفن رومیزی"},
        ],
    },
    {
        "slug": "home-kitchen",
        "name": "خانه و آشپزخانه",
        "children": [
            {"slug": "furniture", "name": "مبلمان و دکوراسیون"},
            {"slug": "chair-bench", "name": "صندلی و نیمکت"},
            {"slug": "home-lighting", "name": "روشنایی"},
            {"slug": "appliance", "name": "لوازم خانگی برقی"},
            {"slug": "carpet-moquette", "name": "فرش و گلیم"},
            {"slug": "kitchen-utensils", "name": "ظروف و لوازم آشپزی"},
        ],
    },
    {
        "slug": "services",
        "name": "خدمات",
        "children": [
            {"slug": "car-and-motor", "name": "خودرو و موتور"},
            {"slug": "catering", "name": "پذیرایی و مراسم"},
            {"slug": "computer-and-mobile", "name": "رایانه و موبایل"},
            {"slug": "accounting-and-finance", "name": "مالی و حسابداری"},
            {"slug": "transport", "name": "حمل و نقل"},
            {"slug": "craftsmen", "name": "پیشه‌وران"},
            {"slug": "beauty-and-haircare", "name": "آرایشگری و زیبایی"},
            {"slug": "cleaning", "name": "نظافت"},
            {"slug": "teaching", "name": "آموزشی"},
        ],
    },
    {
        "slug": "personal",
        "name": "وسایل شخصی",
        "children": [
            {"slug": "clothing", "name": "لباس"},
            {"slug": "shoes-belt-bag", "name": "کیف، کفش و کمربند"},
            {"slug": "jewelry-and-watches", "name": "زیورآلات و ساعت"},
            {"slug": "health-beauty", "name": "آرایشی و بهداشتی"},
            {"slug": "childrens-clothing-and-shoe", "name": "لباس و کفش کودک"},
            {"slug": "childrens-furniture", "name": "اسباب کودک"},
        ],
    },
    {
        "slug": "leisure-hobbies",
        "name": "سرگرمی و فراغت",
        "children": [
            {"slug": "ticket", "name": "بلیت"},
            {"slug": "travel-packages", "name": "تور و سفر"},
            {"slug": "sport", "name": "ورزش"},
            {"slug": "book-student-literature", "name": "کتاب و لوازم‌تحریر"},
            {"slug": "bicycle", "name": "دوچرخه"},
            {"slug": "musical-instruments", "name": "آلات موسیقی"},
        ],
    },
    {
        "slug": "animals",
        "name": "حیوانات",
        "children": [
            {"slug": "cat", "name": "گربه"},
            {"slug": "dog", "name": "سگ"},
            {"slug": "birds", "name": "پرنده"},
            {"slug": "fish", "name": "ماهی"},
            {"slug": "farm-animals", "name": "حیوانات مزرعه"},
        ],
    },
    {
        "slug": "tools-materials-equipment",
        "name": "تجهیزات و صنعتی",
        "children": [
            {"slug": "building-equipment", "name": "تجهیزات ساختمانی"},
            {"slug": "industrial-machinery", "name": "ماشین‌آلات صنعتی"},
            {"slug": "toolbox", "name": "ابزارآلات"},
            {"slug": "shop-and-cash", "name": "تجهیزات فروشگاه"},
        ],
    },
    {
        "slug": "jobs",
        "name": "استخدام",
        "children": [
            {"slug": "administration-and-hr", "name": "اداری و منابع انسانی"},
            {"slug": "computer-and-it", "name": "رایانه و فناوری"},
            {"slug": "sales-marketing", "name": "فروش و بازاریابی"},
            {"slug": "education", "name": "آموزشی"},
            {"slug": "industrial-technology", "name": "صنعتی و فنی"},
            {"slug": "care-health-beauty", "name": "درمانی و زیبایی"},
        ],
    },
    {
        "slug": "community",
        "name": "اجتماعی",
        "children": [
            {"slug": "lost-and-found", "name": "گم‌شده‌ها"},
            {"slug": "volunteers", "name": "داوطلبانه"},
            {"slug": "event", "name": "رویداد"},
        ],
    },
]


def flatten(
    nodes: list[dict[str, Any]] | None = None,
    trail: list[str] | None = None,
) -> list[dict[str, Any]]:
    nodes = active_tree() if nodes is None else nodes
    trail = trail or []
    out: list[dict[str, Any]] = []
    for node in nodes:
        path = trail + [str(node["name"])]
        kids = list(node.get("children") or [])
        out.append(
            {
                "slug": node["slug"],
                "name": node["name"],
                "path": " / ".join(path),
                "has_children": bool(kids),
            }
        )
        if kids:
            out.extend(flatten(kids, path))
    return out


def find_category(slug: str) -> dict[str, Any] | None:
    needle = (slug or "").strip()
    if not needle:
        return None
    for item in flatten():
        if item["slug"] == needle:
            return item
    return {"slug": needle, "name": needle, "path": needle, "has_children": False}


_live_tree: list[dict[str, Any]] | None = None


def active_tree() -> list[dict[str, Any]]:
    global _live_tree
    if _live_tree is not None:
        return _live_tree
    try:
        from config_store import DATA_DIR
        from divar import DivarClient

        _live_tree = DivarClient(DATA_DIR).category_tree() or TREE
    except Exception:
        _live_tree = TREE
    return _live_tree


def category_payload() -> dict[str, Any]:
    tree = active_tree()
    return {"tree": tree, "flat": flatten(tree)}
