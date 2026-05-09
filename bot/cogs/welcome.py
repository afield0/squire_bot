from __future__ import annotations

import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands

from bot.storage.state_repo import StateRepository

LOGGER = logging.getLogger(__name__)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot, state_repo: StateRepository) -> None:
        self.bot = bot
        self.state_repo = state_repo

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not self.bot.config.welcome.enabled:
            return
        state_key = self._state_key(member.guild.id, member.id)
        if await self.state_repo.get(state_key):
            return

        handled = False
        if self.bot.config.welcome.channel_id:
            handled = await self._send_channel_greeting(member) or handled
        if self.bot.config.welcome.dm_enabled:
            handled = await self._send_dm(member) or handled

        if handled:
            await self.state_repo.set(state_key, datetime.now(UTC).isoformat())

    async def _send_channel_greeting(self, member: discord.Member) -> bool:
        channel_id = self.bot.config.welcome.channel_id
        if not channel_id:
            return False
        try:
            channel = await self._resolve_channel(channel_id)
            await channel.send(
                f"Welcome {member.mention} to Vampire Defenders. "
                "Use `/rulebook latest`, `/rules ask`, and `/card search` when you need a hand at the table."
            )
            return True
        except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
            LOGGER.warning("Failed to send welcome greeting for member_id=%s: %s", member.id, exc)
            return False

    async def _send_dm(self, member: discord.Member) -> bool:
        try:
            await member.send(self._capabilities_message(member.guild.name))
            return True
        except (discord.Forbidden, discord.HTTPException) as exc:
            LOGGER.warning("Failed to DM welcome capabilities to member_id=%s: %s", member.id, exc)
            return False

    async def _resolve_channel(self, channel_id: int) -> discord.abc.Messageable:
        cached = self.bot.get_channel(channel_id)
        if cached and hasattr(cached, "send"):
            return cached

        fetched = await self.bot.fetch_channel(channel_id)
        if hasattr(fetched, "send"):
            return fetched
        raise RuntimeError(f"Configured welcome channel cannot receive messages: {channel_id}")

    @staticmethod
    def _capabilities_message(guild_name: str) -> str:
        return "\n".join(
            [
                f"Welcome to {guild_name}. I help with Vampire Defenders playtest materials.",
                "",
                "Useful commands:",
                "- `/rulebook latest` shows the latest published rulebook PDF.",
                "- `/rules ask` answers rules questions from the local rulebook.",
                "- `/card show`, `/card search`, and `/card random` help look up cards.",
                "- `/bot status` shows whether the bot is online and loaded.",
                "",
                "Admins can also sync rules, publish the rulebook, schedule daily prompts, and manage polls.",
            ]
        )

    @staticmethod
    def _state_key(guild_id: int, member_id: int) -> str:
        return f"welcome_greeted:{guild_id}:{member_id}"
