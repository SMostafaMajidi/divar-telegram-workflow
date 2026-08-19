from __future__ import annotations

import json
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._tokens: set[str] = set()
        self._loaded = False

    def load(self) -> set[str]:
        if self._loaded:
            return self._tokens
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._tokens = set(data if isinstance(data, list) else data.get("tokens") or [])
            except json.JSONDecodeError:
                self._tokens = set()
        self._loaded = True
        return self._tokens

    def is_new(self, token: str) -> bool:
        return token not in self.load()

    def add_many(self, tokens: list[str]) -> None:
        current = self.load()
        current.update(tokens)
        # keep file size bounded
        ordered = list(current)
        if len(ordered) > 4000:
            ordered = ordered[-4000:]
            current = set(ordered)
        self._tokens = current
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(sorted(current), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class ChatStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._chats: dict[str, dict] = {}
        self._loaded = False

    def load(self) -> dict[str, dict]:
        if self._loaded:
            return self._chats
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                items = raw if isinstance(raw, list) else raw.get("chats") or []
                self._chats = {str(item.get("id")): item for item in items if item.get("id") is not None}
            except json.JSONDecodeError:
                self._chats = {}
        self._loaded = True
        return self._chats

    def upsert(self, chat: dict) -> dict:
        chats = self.load()
        cid = str(chat.get("id") or "").strip()
        if not cid:
            return chat
        record = {
            "id": cid,
            "type": str(chat.get("type") or ""),
            "name": str(chat.get("name") or chat.get("title") or chat.get("first_name") or "").strip(),
            "username": str(chat.get("username") or "").strip(),
        }
        previous = chats.get(cid) or {}
        if not record["name"]:
            record["name"] = previous.get("name") or ""
        chats[cid] = record
        self._chats = chats
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(list(chats.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return record

    def all(self) -> list[dict]:
        return list(self.load().values())
