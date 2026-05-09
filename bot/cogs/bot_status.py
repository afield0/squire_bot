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
        artifact_path = self.bot.config.rules_sync.artifact_path
        cards_artifact_path = self.bot.config.rules_sync.cards_artifact_path
        rules_loaded = "yes" if artifact_path.exists() else "no"
        cards_loaded = "yes" if cards_artifact_path.exists() else "no"
        rules_summary = f"Rules artifact: `{artifact_path}`"
        cards_summary = f"Cards artifact: `{cards_artifact_path}`"
        lines = [
            f"Latency: `{round(self.bot.latency * 1000, 1)} ms`",
            f"Database: `{self.bot.database.path}`",
            f"Rules loaded: `{rules_loaded}`",
            rules_summary,
            f"Cards loaded: `{cards_loaded}`",
            cards_summary,
            f"LLM mode: `{self.bot.config.openai.rules_use_llm}`",
            f"Model: `{self.bot.config.openai.model}`",
            f"Topic channel: `{self.bot.config.daily.topic_channel_id}`",
            f"Daily LLM mode: `{self.bot.config.daily.use_llm}`",
            f"Daily seed catalog: `{self.bot.config.daily.topic_seeds_path}`",
            f"Design prompt enabled: `{self.bot.config.daily.enable_design_prompt}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
