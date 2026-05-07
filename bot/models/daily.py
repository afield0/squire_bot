from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DailyPost:
    title: str
    body: str

    def render(self) -> str:
        return f"**{self.title}**\n{self.body}"
