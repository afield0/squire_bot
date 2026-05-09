from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.github_sync import GitHubRulesSyncService
from bot.services.rulebook_publish import RulebookPublishService

LOGGER = logging.getLogger(__name__)


class RulebookCog(commands.GroupCog, group_name="rulebook", group_description="Published rulebook PDF commands"):
    def __init__(
        self,
        bot: commands.Bot,
        sync_service: GitHubRulesSyncService,
        publish_service: RulebookPublishService,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.sync_service = sync_service
        self.publish_service = publish_service

    @app_commands.command(name="post", description="Publish the current local rulebook PDF")
    @app_commands.default_permissions(manage_guild=True)
    async def post(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            commit = await self.sync_service.get_current_commit()
            record = await self.publish_service.publish(commit)
            lines = [
                "Rulebook published.",
                f"Commit: `{record.commit}`",
                f"PDF path: `{self.bot.config.rulebook.pdf_path}`",
            ]
            if record.build_metadata and record.build_metadata.built_at:
                lines.append(f"PDF built at: `{record.build_metadata.built_at}`")
            if record.message_url:
                lines.append(f"Message: {record.message_url}")
            await interaction.followup.send("\n".join(lines), ephemeral=True)
        except Exception as exc:
            LOGGER.exception("Manual rulebook publish failed")
            await interaction.followup.send(f"Rulebook publish failed: {exc}", ephemeral=True)

    @app_commands.command(name="latest", description="Show the latest published rulebook message")
    async def latest(self, interaction: discord.Interaction) -> None:
        state = await self.publish_service.get_state()
        if not state.commit or not state.message_id:
            await interaction.response.send_message("No rulebook has been published yet.", ephemeral=True)
            return

        lines = [
            "**Latest Vampire Defenders Rulebook**",
            f"Build commit: `{state.commit[:12]}`",
            f"Published: `{state.published_at or 'unknown'}`",
        ]
        message_url = self._message_url(state.channel_id, state.message_id)
        if message_url:
            lines.append(f"Message: {message_url}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="status", description="Show rulebook publishing status")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        state = await self.publish_service.get_state()
        pdf_path = self.bot.config.rulebook.pdf_path
        metadata_path = pdf_path.with_name(f"{pdf_path.stem}.metadata.json")
        pdf_exists = pdf_path.exists()
        pdf_size = pdf_path.stat().st_size if pdf_exists else 0
        try:
            current_commit = await self.sync_service.get_current_commit()
        except Exception as exc:
            current_commit = f"unavailable: {exc}"

        lines = [
            f"Configured channel id: `{self.bot.config.rulebook.channel_id or 'unset'}`",
            f"Configured PDF path: `{pdf_path}`",
            f"Metadata path: `{metadata_path}`",
            f"Metadata exists: `{metadata_path.exists()}`",
            f"PDF exists: `{pdf_exists}`",
            f"PDF size: `{pdf_size}` bytes",
            f"Current synced commit: `{current_commit}`",
            f"Latest published commit: `{state.commit or 'never'}`",
            f"Latest published time: `{state.published_at or 'never'}`",
            f"Latest published message id: `{state.message_id or 'none'}`",
            f"Latest published channel id: `{state.channel_id or 'none'}`",
            f"Auto-publish enabled: `{self.bot.config.rulebook.auto_publish}`",
            f"Delete previous enabled: `{self.bot.config.rulebook.delete_previous}`",
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @staticmethod
    def _has_manage_guild(interaction: discord.Interaction) -> bool:
        permissions = interaction.permissions
        return bool(permissions and permissions.manage_guild)

    def _message_url(self, channel_id: int | None, message_id: int | None) -> str | None:
        if not channel_id or not message_id or not self.bot.config.discord_guild_id:
            return None
        return f"https://discord.com/channels/{self.bot.config.discord_guild_id}/{channel_id}/{message_id}"
