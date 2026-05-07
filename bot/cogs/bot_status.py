from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class BotStatusCog(commands.GroupCog, group_name="bot", group_description="Bot health and status"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(name="status", description="Show bot health and loaded services")
    async def status(self, interaction: discord.Interaction) -> None:
        rules_loaded = "yes" if self.bot.retrieval_service.has_index() else "no"
        rules_summary = self.bot.retrieval_service.get_sources_summary()
        lines = [
            f"Latency: `{round(self.bot.latency * 1000, 1)} ms`",
            f"Database: `{self.bot.database.path}`",
            f"Rules loaded: `{rules_loaded}`",
            rules_summary,
            f"Topic channel: `{self.bot.config.daily.topic_channel_id}`",
            f"Design prompt enabled: `{self.bot.config.daily.enable_design_prompt}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
