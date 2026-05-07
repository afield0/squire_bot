from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.retrieval import RulesRetrievalService


class RulesCog(commands.GroupCog, group_name="rules", group_description="Rules lookup commands"):
    def __init__(
        self,
        bot: commands.Bot,
        retrieval_service: RulesRetrievalService,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.retrieval_service = retrieval_service

    @app_commands.command(name="ask", description="Ask a rules question using the local rules index")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        if not self.retrieval_service.has_index():
            await interaction.response.send_message(
                "No rules index is loaded yet. Run `/admin sync-rules` or `/admin rebuild-rules` first.",
                ephemeral=True,
            )
            return

        answer = self.retrieval_service.answer_question(question)
        await interaction.response.send_message(answer, ephemeral=False)

    @app_commands.command(name="sources", description="Show the currently loaded rules artifact and revision")
    @app_commands.default_permissions(manage_guild=True)
    async def sources(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            self.retrieval_service.get_sources_summary(),
            ephemeral=True,
        )

    @app_commands.command(name="debug", description="Show the same rules source and index metadata")
    @app_commands.default_permissions(manage_guild=True)
    async def debug(self, interaction: discord.Interaction) -> None:
        await self.sources(interaction)
