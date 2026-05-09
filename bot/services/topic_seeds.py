from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from bot.storage.daily_repo import DailyHistoryRepository


@dataclass(frozen=True, slots=True)
class TopicSeed:
    id: str
    category: str
    source_type: str
    intent: str
    weight: int
    cooldown_days: int
    source_hints: tuple[str, ...]


class TopicSeedCatalog:
    def __init__(self, seeds_path: Path, daily_repo: DailyHistoryRepository) -> None:
        self.seeds_path = seeds_path
        self.daily_repo = daily_repo
        self._seeds: list[TopicSeed] | None = None

    async def list_seeds(self) -> list[TopicSeed]:
        return self._load_seeds()

    async def choose_seed(
        self,
        today: date,
        available_source_types: Iterable[str] | None = None,
    ) -> TopicSeed:
        seeds = await self.list_seeds()
        available = set(available_source_types or {"rulebook", "mixed"})
        seeds = [seed for seed in seeds if self._source_available(seed, available)]
        if not seeds:
            raise RuntimeError("No daily topic seeds match the available local sources.")

        max_cooldown = max(seed.cooldown_days for seed in seeds)
        recent = await self.daily_repo.fetch_recent_seed_posts(today, max_cooldown)
        recent_by_seed = {item.seed_id: item.posted_date for item in recent}
        eligible = [
            seed
            for seed in seeds
            if not self._is_on_cooldown(seed, today, recent_by_seed.get(seed.id))
        ]
        if not eligible:
            eligible = seeds

        return self._weighted_choice(eligible, today)

    def _load_seeds(self) -> list[TopicSeed]:
        if self._seeds is not None:
            return self._seeds
        if not self.seeds_path.exists():
            raise RuntimeError(f"Daily topic seed catalog does not exist: {self.seeds_path}")

        payload = json.loads(self.seeds_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError("Daily topic seed catalog must contain a JSON array.")

        seeds: list[TopicSeed] = []
        for item in payload:
            seeds.append(
                TopicSeed(
                    id=str(item["id"]).strip(),
                    category=str(item["category"]).strip(),
                    source_type=str(item["source_type"]).strip(),
                    intent=str(item["intent"]).strip(),
                    weight=max(1, int(item.get("weight", 1))),
                    cooldown_days=max(0, int(item.get("cooldown_days", 0))),
                    source_hints=tuple(str(hint).strip() for hint in item.get("source_hints", []) if str(hint).strip()),
                )
            )
        if not seeds:
            raise RuntimeError("Daily topic seed catalog is empty.")
        self._seeds = seeds
        return seeds

    @staticmethod
    def _source_available(seed: TopicSeed, available: set[str]) -> bool:
        if seed.source_type == "mixed":
            return bool({"rulebook", "cards", "lore"} & available)
        return seed.source_type in available

    @staticmethod
    def _is_on_cooldown(seed: TopicSeed, today: date, last_posted: date | None) -> bool:
        if last_posted is None or seed.cooldown_days <= 0:
            return False
        return (today - last_posted).days < seed.cooldown_days

    @staticmethod
    def _weighted_choice(seeds: list[TopicSeed], today: date) -> TopicSeed:
        stable_seeds = sorted(seeds, key=lambda seed: seed.id)
        rng = random.Random(today.isoformat())
        return rng.choices(stable_seeds, weights=[seed.weight for seed in stable_seeds], k=1)[0]
