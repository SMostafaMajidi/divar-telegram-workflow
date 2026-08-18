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
