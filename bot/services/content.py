from __future__ import annotations

import asyncio
import logging
from datetime import date

from bot.models.daily import DailyPost
from bot.services.daily_llm import DailyLLMComposer
from bot.services.daily_sources import DailySourceGatherer
from bot.services.topic_seeds import TopicSeedCatalog

LOGGER = logging.getLogger(__name__)


class DailyContentService:
    def __init__(
        self,
        seed_catalog: TopicSeedCatalog,
        source_gatherer: DailySourceGatherer,
        llm_composer: DailyLLMComposer,
    ) -> None:
        self.seed_catalog = seed_catalog
        self.source_gatherer = source_gatherer
        self.llm_composer = llm_composer

    async def build_topic_of_day(self, today: date) -> DailyPost:
        seed = await self.seed_catalog.choose_seed(
            today,
            available_source_types=self.source_gatherer.available_source_types(),
        )
        sources = await self.source_gatherer.gather(seed)
        if self.llm_composer.available() and sources.has_sources:
            try:
                return await asyncio.to_thread(self.llm_composer.compose, seed, sources)
            except Exception as exc:
                LOGGER.warning("Daily LLM composition failed; using template fallback: %s", exc)
        return self.llm_composer.fallback_post(seed, sources)

    def build_design_prompt(self, today: date) -> DailyPost:
        prompts = [
            "Design one small rule tweak that increases player cooperation without reducing tension.",
            "Pitch a new enemy behavior that changes how players value positioning.",
            "Draft a playtest question that would expose balance problems in the midgame.",
            "Invent a new card concept that helps recovery after a bad round.",
            "Propose one scenario modifier that makes the opening turns less scripted.",
        ]
        prompt = prompts[today.toordinal() % len(prompts)]
        return DailyPost(
            title="Vampire Defenders Daily Design Prompt",
            body=prompt,
        )
