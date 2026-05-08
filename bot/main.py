from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.cogs.bot_status import BotStatusCog
from bot.cogs.daily import DailyCog
from bot.cogs.polls import PollsCog
from bot.cogs.rules import RulesCog
from bot.services.build_rules_artifact import RulesArtifactBuilder
from bot.services.content import DailyContentService
from bot.services.github_sync import GitHubRulesSyncService
from bot.services.openai_client import OpenAIRulesClient
from bot.storage.db import Database
from bot.storage.poll_repo import PollRepository
from bot.storage.state_repo import StateRepository
from bot.utils.config import AppConfig, load_config
from bot.utils.logging import configure_logging

LOGGER = logging.getLogger(__name__)


class VampireDefendersBot(commands.Bot):
    def __init__(self, config: AppConfig) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            application_id=config.discord_application_id,
        )
        self.config = config
        self.database = Database(config.sqlite_path)
        self.state_repo = StateRepository(self.database)
        self.poll_repo = PollRepository(self.database)
        self.rules_sync = GitHubRulesSyncService(config.rules_sync)
        self.rules_artifact_builder = RulesArtifactBuilder(config.rules_sync)
        self.openai_rules_client = OpenAIRulesClient(config.openai)
        self.daily_content_service = DailyContentService()

    async def setup_hook(self) -> None:
        self.database.initialize()

        await self.add_cog(
            RulesCog(
                bot=self,
                state_repo=self.state_repo,
                sync_service=self.rules_sync,
                artifact_builder=self.rules_artifact_builder,
                openai_client=self.openai_rules_client,
            )
        )
        await self.add_cog(
            DailyCog(
                bot=self,
                state_repo=self.state_repo,
                content_service=self.daily_content_service,
            )
        )
        await self.add_cog(
            PollsCog(
                bot=self,
                poll_repo=self.poll_repo,
            )
        )
        await self.add_cog(BotStatusCog(bot=self))

        if self.config.discord_guild_id:
            guild = discord.Object(id=self.config.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            LOGGER.info("Synced %s guild commands", len(synced))
        else:
            synced = await self.tree.sync()
            LOGGER.info("Synced %s global commands", len(synced))


async def run_bot() -> None:
    config = load_config()
    configure_logging(config.log_level)
    bot = VampireDefendersBot(config)
    async with bot:
        await bot.start(config.discord_bot_token)


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
