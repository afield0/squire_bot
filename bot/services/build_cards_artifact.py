from __future__ import annotations

import importlib
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from bot.utils.config import RulesSyncConfig, load_rules_sync_config

LOGGER = logging.getLogger(__name__)

CARD_FIELDS = (
    "hp",
    "attack",
    "attack_dice",
    "persistent",
    "cost",
    "description",
    "effects",
    "availability",
    "grant",
    "inventory",
    "inventory_growth",
    "owner_bonus",
    "owner_bonus_castle_hp",
    "owner_bonus_victory_points",
    "vp",
    "flavor_text",
    "tags",
    "copies",
    "loot",
    "abilities",
)

CARD_ASSET_DIRS = {
    "attacker": "attackers",
    "defender": "defenders",
    "battle": "battle_cards",
    "location": "locations",
    "castle_improvement": "castle_improvements",
    "objective": "objectives",
}


class CardsArtifactBuilder:
    def __init__(self, config: RulesSyncConfig) -> None:
        self.config = config

    def build(self) -> Path:
        registry = self._load_registry()
        cards = [self._normalize_card(card_id, card) for card_id, card in sorted(registry.items())]
        artifact_path = self.artifact_path()
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": {
                "built_at": datetime.now(UTC).isoformat(),
                "source_repo": str(self.config.local_checkout_path),
                "card_count": len(cards),
            },
            "cards": cards,
        }
        artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        LOGGER.info("Built cards artifact at %s with %s cards", artifact_path, len(cards))
        return artifact_path

    def artifact_path(self) -> Path:
        return self.config.cards_artifact_path

    def _load_registry(self) -> dict[str, object]:
        checkout_path = self.config.local_checkout_path
        registry_path = checkout_path / "vampire_defenders" / "cards" / "registry.py"
        if not registry_path.exists():
            raise RuntimeError(
                f"Card registry is missing from the local checkout: {registry_path}. "
                "Update GITHUB_RULES_INCLUDE_PATHS and run `/rules sync`."
            )

        checkout_str = str(checkout_path)
        sys.path.insert(0, checkout_str)
        try:
            for module_name in list(sys.modules):
                if module_name == "vampire_defenders" or module_name.startswith("vampire_defenders."):
                    sys.modules.pop(module_name, None)
            module = importlib.import_module("vampire_defenders.cards.registry")
            registry = getattr(module, "CARD_REGISTRY", None)
        finally:
            try:
                sys.path.remove(checkout_str)
            except ValueError:
                pass

        if not isinstance(registry, dict):
            raise RuntimeError("vampire_defenders.cards.registry.CARD_REGISTRY was not a dictionary.")
        return registry

    def _normalize_card(self, card_id: str, card: object) -> dict[str, Any]:
        raw = asdict(card) if is_dataclass(card) else dict(getattr(card, "__dict__", {}))
        card_type = self._card_type(card)
        normalized: dict[str, Any] = {
            "id": self._json_safe(raw.get("id", card_id)),
            "name": self._json_safe(raw.get("name", card_id)),
            "card_type": card_type,
        }
        for field_name in CARD_FIELDS:
            if field_name not in raw:
                continue
            value = self._json_safe(raw[field_name])
            if value in (None, "", [], {}):
                continue
            normalized[field_name] = value
        image_path = self._card_image_path(str(normalized["id"]), card_type)
        if image_path:
            normalized["image_path"] = image_path
        return normalized

    def _card_image_path(self, card_id: str, card_type: str) -> str | None:
        asset_dir = CARD_ASSET_DIRS.get(card_type)
        if not asset_dir:
            return None
        asset_root = self.config.local_checkout_path / "assets" / "cards" / "rendered" / asset_dir
        for suffix in (".png", ".webp", ".jpg", ".jpeg"):
            path = asset_root / f"{card_id}{suffix}"
            if path.exists():
                return str(path)
        return None

    @staticmethod
    def _card_type(card: object) -> str:
        class_name = type(card).__name__
        if class_name == "AttackerCardDef":
            return "attacker"
        if class_name == "DefenderCardDef":
            return "defender"
        if class_name == "BattleCardDef":
            return "battle"
        if class_name == "CastleLocationDef":
            return "castle_improvement"
        if class_name == "LocationCardDef":
            return "location"
        if class_name == "ObjectiveCardDef":
            return "objective"
        return class_name.removesuffix("CardDef").removesuffix("Def").lower()

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if is_dataclass(value):
            return cls._json_safe(asdict(value))
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {str(cls._json_safe(key)): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (tuple, list, set, frozenset)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if callable(value):
            return None
        return str(value)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    config = load_rules_sync_config()
    artifact_path = CardsArtifactBuilder(config).build()
    print(artifact_path)


if __name__ == "__main__":
    main()
