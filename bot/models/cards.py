from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DISPLAY_FIELDS = (
    "hp",
    "attack",
    "attack_dice",
    "persistent",
    "cost",
    "copies",
    "vp",
    "availability",
    "grant",
    "inventory",
    "inventory_growth",
    "owner_bonus",
    "owner_bonus_castle_hp",
    "owner_bonus_victory_points",
    "loot",
    "abilities",
    "tags",
)


@dataclass(frozen=True, slots=True)
class NormalizedCard:
    id: str
    name: str
    card_type: str
    fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NormalizedCard":
        core = {"id", "name", "card_type"}
        fields = {key: value for key, value in payload.items() if key not in core}
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            card_type=str(payload["card_type"]),
            fields=fields,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "card_type": self.card_type, **self.fields}

    def short_label(self) -> str:
        return f"{self.name} ({self.card_type})"

    def render_summary(self) -> str:
        detail = self._compact_details(limit=3)
        return f"**{self.name}** `({self.card_type})`" + (f" - {detail}" if detail else "")

    def render_detail(self) -> str:
        lines = ["", f"**{self.name}**", f"Type: `{self.card_type}`", f"ID: `{self.id}`"]
        details = self._detail_lines()
        if details:
            lines.append("")
            lines.extend(details)
        text = self.fields.get("description") or self.fields.get("flavor_text")
        if text:
            lines.append("")
            lines.append(str(text))
        effects = self.fields.get("effects")
        if effects:
            lines.append("")
            lines.append("Effects:")
            lines.extend(f"- {effect}" for effect in effects[:4])
        return self._trim_for_discord("\n".join(lines))

    def render_excerpt(self) -> str:
        parts = [self.short_label()]
        compact = self._compact_details(limit=5)
        if compact:
            parts.append(compact)
        description = self.fields.get("description") or self.fields.get("flavor_text")
        if description:
            parts.append(str(description))
        effects = self.fields.get("effects")
        if effects:
            parts.append("Effects: " + "; ".join(str(effect) for effect in effects[:3]))
        return self._trim_for_discord("\n".join(parts), limit=700)

    def _detail_lines(self) -> list[str]:
        lines: list[str] = []
        for field_name in DISPLAY_FIELDS:
            value = self.fields.get(field_name)
            if value in (None, "", [], {}, ()):
                continue
            lines.append(f"{self._label(field_name)}: `{self._format_value(value)}`")
        return lines

    def _compact_details(self, limit: int) -> str:
        details: list[str] = []
        for field_name in DISPLAY_FIELDS:
            value = self.fields.get(field_name)
            if value in (None, "", [], {}, ()):
                continue
            details.append(f"{self._label(field_name)} {self._format_value(value)}")
            if len(details) >= limit:
                break
        return "; ".join(details)

    @staticmethod
    def _label(field_name: str) -> str:
        return field_name.replace("_", " ").title()

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, dict):
            return ", ".join(f"{key}: {val}" for key, val in value.items())
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    @staticmethod
    def _trim_for_discord(text: str, limit: int = 1900) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."


@dataclass(frozen=True, slots=True)
class CardSearchResult:
    card: NormalizedCard
    score: float
    reason: str
