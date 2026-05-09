from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.models.cards import NormalizedCard
from bot.services.cards import CardRepository


class CardsCog(commands.GroupCog, group_name="card", group_description="Card lookup commands"):
    def __init__(self, card_repository: CardRepository) -> None:
        super().__init__()
        self.card_repository = card_repository

    @app_commands.command(name="show", description="Show one card by name or id")
    async def show(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            results = self.card_repository.search_cards(query, limit=5)
        except Exception as exc:
            await interaction.followup.send(f"Card lookup failed: {exc}", ephemeral=True)
            return

        if not results:
            await interaction.followup.send(f"No card matched `{query}`.", ephemeral=True)
            return

        best = results[0]
        second = results[1] if len(results) > 1 else None
        if best.score < 0.72 or (second and best.score < 1.0 and best.score - second.score < 0.08):
            lines = [f"Multiple cards could match `{query}`. Try a more specific name or id:"]
            lines.extend(f"- {result.card.render_summary()}" for result in results[:5])
            await interaction.followup.send(self._trim_for_discord("\n".join(lines)), ephemeral=True)
            return

        await self._send_card_detail(interaction, best.card)

    @app_commands.command(name="search", description="Search cards by name, id, or type")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            results = self.card_repository.search_cards(query, limit=10)
        except Exception as exc:
            await interaction.followup.send(f"Card search failed: {exc}", ephemeral=True)
            return

        if not results:
            await interaction.followup.send(f"No cards matched `{query}`.", ephemeral=True)
            return

        lines = [f"Card matches for `{query}`:"]
        lines.extend(f"- {result.card.render_summary()}" for result in results)
        await interaction.followup.send(self._trim_for_discord("\n".join(lines)), ephemeral=True)

    @app_commands.command(name="random", description="Show a random card, optionally filtered by type")
    async def random(self, interaction: discord.Interaction, type: str | None = None) -> None:
        await interaction.response.defer(thinking=True)
        try:
            card = self.card_repository.random_card(type)
        except Exception as exc:
            await interaction.followup.send(f"Random card failed: {exc}", ephemeral=True)
            return

        if card is None:
            type_note = f" of type `{type}`" if type else ""
            await interaction.followup.send(f"No cards{type_note} are available.", ephemeral=True)
            return

        await self._send_card_detail(interaction, card)

    async def _send_card_detail(self, interaction: discord.Interaction, card: NormalizedCard) -> None:
        image_path = self.card_repository.image_path_for(card)
        if image_path:
            await interaction.followup.send(file=discord.File(image_path))
        await interaction.followup.send(card.render_detail())

    @staticmethod
    def _trim_for_discord(text: str, limit: int = 1900) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."
