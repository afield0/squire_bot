from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DailyPost:
    title: str
    body: str
    category: str | None = None
    source_labels: list[str] | None = None
    seed_id: str | None = None

    def render(self) -> str:
        lines = [f"**{self.title}**", self.body]
        if self.source_labels:
            lines.append("")
            lines.append("Sources:")
            lines.extend(f"- {label}" for label in self.source_labels[:4])
        return "\n".join(lines)
