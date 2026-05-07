from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.github_sync import GitHubRulesSyncService
from bot.services.retrieval import RulesRetrievalService
from bot.services.rules_build import RulesBuildService


class AdminCog(commands.GroupCog, group_name="admin", group_description="Admin and maintenance commands"):
    def __init__(
        self,
        bot: commands.Bot,
        sync_service: GitHubRulesSyncService,
        build_service: RulesBuildService,
        retrieval_service: RulesRetrievalService,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.sync_service = sync_service
        self.build_service = build_service
        self.retrieval_service = retrieval_service

    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name="sync-rules", description="Clone or pull the configured rules repository")
    async def sync_rules(
        self,
        interaction: discord.Interaction,
        rebuild: bool = True,
    ) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            revision = await self.sync_service.ensure_local_checkout()
            artifact_path = None
            index_path = None
            if rebuild:
                artifact_path = await self.build_service.build_artifact(revision)
                index_path = await self.build_service.build_index(artifact_path, revision)
                await self.retrieval_service.load()

            lines = [f"Rules sync completed at revision `{revision}`."]
            if artifact_path:
                lines.append(f"Artifact: `{artifact_path}`")
            if index_path:
                lines.append(f"Index: `{index_path}`")
            await interaction.followup.send("\n".join(lines), ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Rules sync failed: {exc}", ephemeral=True)

    @app_commands.default_permissions(manage_guild=True)
    @app_commands.command(name="rebuild-rules", description="Rebuild and reload the local rules index")
    async def rebuild_rules(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            revision = await self.sync_service.get_current_revision()
            artifact_path = await self.build_service.build_artifact(revision)
            index_path = await self.build_service.build_index(artifact_path, revision)
            await self.retrieval_service.load()
            await interaction.followup.send(
                f"Rules rebuild completed.\nArtifact: `{artifact_path}`\nIndex: `{index_path}`",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Rules rebuild failed: {exc}", ephemeral=True)

    @staticmethod
    def _has_manage_guild(interaction: discord.Interaction) -> bool:
        permissions = interaction.permissions
        return bool(permissions and permissions.manage_guild)
