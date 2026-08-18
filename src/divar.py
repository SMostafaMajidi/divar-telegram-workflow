from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

SEARCH_URL = "https://api.divar.ir/v8/postlist/w/search"
CITIES_URL = "https://api.divar.ir/v8/places/cities"
POST_URL = "https://divar.ir/v/a/{token}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "fa",
    "Origin": "https://divar.ir",
    "Referer": "https://divar.ir/",
}

KNOWN_CITIES = {
    "isfahan": 4,
    "اصفهان": 4,
    "khomeyni-shahr": 1747,
    "خمینی شهر": 1747,
    "خمینی‌شهر": 1747,
    "najafabad": 31,
    "نجف آباد": 31,
    "نجف‌آباد": 31,
    "falavarjan": 849,
    "فلاورجان": 849,
}


@dataclass(frozen=True)
class Listing:
    token: str
    title: str
    price: str
    mileage: str
    city: str
    district: str
    image_url: str | None
    url: str
    filter_name: str

    @property
    def location(self) -> str:
        parts = [p for p in (self.city, self.district) if p]
        return "، ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "title": self.title,
            "price": self.price,
            "mileage": self.mileage,
            "city": self.city,
            "district": self.district,
            "location": self.location,
            "image_url": self.image_url,
            "url": self.url,
            "filter_name": self.filter_name,
        }


class DivarClient:
    def __init__(self, cache_dir: Path, timeout: int = 25) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._cities: dict[str, int] | None = None
        self._city_records: list[dict[str, Any]] | None = None

    def resolve_city_ids(self, cities: Iterable[str | int]) -> list[str]:
        mapping = self._city_map()
        ids: list[str] = []
        seen: set[str] = set()
        for city in cities:
            if isinstance(city, int) or str(city).isdigit():
                city_id = str(city)
            else:
                key = _norm(str(city))
                if key not in mapping:
                    raise ValueError(f"City not found: {city}")
                city_id = str(mapping[key])
            if city_id not in seen:
                seen.add(city_id)
                ids.append(city_id)
        return ids

    def search_cities(self, query: str = "", limit: int = 12) -> list[dict[str, Any]]:
        records = self._records()
        popular = [
            "اصفهان",
            "خمینی‌شهر",
            "نجف‌آباد",
            "فلاورجان",
            "تهران",
            "کرج",
            "مشهد",
            "شیراز",
        ]
        if not query.strip():
            by_name = {str(item.get("name") or ""): item for item in records}
            out: list[dict[str, Any]] = []
            for name in popular:
                item = by_name.get(name)
                if item:
                    out.append(_city_item(item))
            return out[:limit]

        needle = _norm(query)
        ranked: list[tuple[int, int, dict[str, Any]]] = []
        for item in records:
            name = str(item.get("name") or "")
            slug = str(item.get("slug") or "")
            n_name, n_slug = _norm(name), _norm(slug)
            if n_name.startswith(needle) or n_slug.startswith(needle):
                rank = 0
            elif needle in n_name or needle in n_slug:
                rank = 1
            else:
                continue
            ranked.append((rank, len(name), _city_item(item)))
        ranked.sort(key=lambda row: (row[0], row[1]))
        seen: set[int] = set()
        out = []
        for _, _, item in ranked:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def search_filter(self, spec: dict[str, Any]) -> list[Listing]:
        city_ids = self.resolve_city_ids(spec.get("cities") or [])
        payload = {
            "city_ids": city_ids,
            "source": 0,
            "search_data": {
                "form_data": {"data": _form_data(spec)},
            },
        }
        query = (spec.get("query") or "").strip()
        if query:
            payload["search_data"]["query"] = query

        max_pages = int(spec.get("max_pages") or 1)
        exclude = [_norm(w) for w in spec.get("exclude_title") or [] if str(w).strip()]
        listings: list[Listing] = []
        seen_tokens: set[str] = set()
        pagination_data = None

        for _ in range(max(1, max_pages)):
            body = dict(payload)
            if pagination_data:
                body["pagination_data"] = pagination_data
            data = self._post_search(body)
            for item in _parse_listings(data, spec.get("name") or query or "divar"):
                if item.token in seen_tokens:
                    continue
                if _should_exclude(item.title, exclude):
                    continue
                seen_tokens.add(item.token)
                listings.append(item)
            pagination = data.get("pagination") or {}
            if not pagination.get("has_next_page"):
                break
            pagination_data = pagination.get("data")
            time.sleep(0.4)
        return listings

    def _post_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(SEARCH_URL, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _city_map(self) -> dict[str, int]:
        if self._cities is not None:
            return self._cities
        mapping = {_norm(name): city_id for name, city_id in KNOWN_CITIES.items()}
        remote = self._records()
        for city in remote:
            city_id = city.get("id")
            for key in (city.get("name"), city.get("slug"), city.get("second_slug")):
                if key and city_id is not None:
                    mapping[_norm(str(key))] = int(city_id)
        self._cities = mapping
        return mapping

    def _fetch_cities(self, cache_path: Path) -> list[dict[str, Any]]:
        response = self.session.get(CITIES_URL, timeout=self.timeout)
        response.raise_for_status()
        cities = response.json().get("cities") or []
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cities, ensure_ascii=False), encoding="utf-8"
        )
        return cities

    def _load_cities_cache(self, cache_path: Path) -> list[dict[str, Any]] | None:
        if not cache_path.exists():
            return None
        age = time.time() - cache_path.stat().st_mtime
        if age > 7 * 24 * 3600:
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _records(self) -> list[dict[str, Any]]:
        if self._city_records is not None:
            return self._city_records
        cache_path = self.cache_dir / "cities.json"
        self._city_records = self._load_cities_cache(cache_path) or self._fetch_cities(cache_path)
        return self._city_records


def _city_item(city: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": city.get("id"),
        "name": city.get("name"),
        "slug": city.get("slug"),
    }


def _form_data(spec: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "category": {"str": {"value": spec.get("category") or "light"}},
    }
    price: dict[str, str] = {}
    if spec.get("price_min_toman") is not None:
        price["minimum"] = str(int(spec["price_min_toman"]))
    if spec.get("price_max_toman") is not None:
        price["maximum"] = str(int(spec["price_max_toman"]))
    if price:
        data["price"] = {"number_range": price}
    return data


def _parse_listings(data: dict[str, Any], filter_name: str) -> list[Listing]:
    listings: list[Listing] = []
    for widget in data.get("list_widgets") or []:
        if widget.get("widget_type") != "POST_ROW":
            continue
        row = widget.get("data") or {}
        token = row.get("token")
        if not token:
            continue
        web_info = (
            ((row.get("action") or {}).get("payload") or {}).get("web_info") or {}
        )
        listings.append(
            Listing(
                token=token,
                title=(row.get("title") or "").strip(),
                price=(row.get("middle_description_text") or "").strip(),
                mileage=(row.get("top_description_text") or "").strip(),
                city=(web_info.get("city_persian") or "").strip(),
                district=(web_info.get("district_persian") or "").strip(),
                image_url=_upgrade_image(row.get("image_url")),
                url=POST_URL.format(token=token),
                filter_name=filter_name,
            )
        )
    return listings


def _upgrade_image(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("/webp_thumbnail/", "/webp/")


def _should_exclude(title: str, words: list[str]) -> bool:
    normalized = _norm(title)
    return any(word and word in normalized for word in words)


def _norm(value: str) -> str:
    text = value.strip().lower()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = text.replace("\u200c", "").replace(" ", "")
    text = re.sub(r"[-_]", "", text)
    return text
