from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from bot.services.build_rules_artifact import RulesArtifactBuilder
from bot.services.github_sync import GitHubRulesSyncService
from bot.services.retrieval import RulesRetrievalService
from bot.services.rules_index import RulesIndexService
from bot.storage.state_repo import StateRepository

RULES_LAST_SYNC_AT = "rules_last_sync_at"
RULES_LAST_BUILD_AT = "rules_last_build_at"
RULES_CURRENT_COMMIT = "rules_current_commit"
RULES_CHUNK_COUNT = "rules_chunk_count"


class RulesCog(commands.GroupCog, group_name="rules", group_description="Rules lookup commands"):
    def __init__(
        self,
        bot: commands.Bot,
        state_repo: StateRepository,
        sync_service: GitHubRulesSyncService,
        artifact_builder: RulesArtifactBuilder,
        index_service: RulesIndexService,
        retrieval_service: RulesRetrievalService,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.state_repo = state_repo
        self.sync_service = sync_service
        self.artifact_builder = artifact_builder
        self.index_service = index_service
        self.retrieval_service = retrieval_service

    @app_commands.command(name="ask", description="Ask a rules question using the local rules index")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        if not self.retrieval_service.has_index():
            await interaction.response.send_message(
                "No rules index is loaded yet. Run `/rules sync` first.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.retrieval_service.answer_question(question),
            ephemeral=False,
        )

    @app_commands.command(name="sync", description="Sync the private rules repo and rebuild the local index")
    @app_commands.default_permissions(manage_guild=True)
    async def sync(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            commit = await self.sync_service.ensure_repo_synced()
            artifact_path = await self._build_artifact()
            index_path = self.index_service.build_index(commit)
            await self.retrieval_service.load()

            now = datetime.now(UTC).isoformat()
            chunk_count = self.retrieval_service.metadata.chunk_count if self.retrieval_service.metadata else 0
            await self.state_repo.set(RULES_LAST_SYNC_AT, now)
            await self.state_repo.set(RULES_LAST_BUILD_AT, now)
            await self.state_repo.set(RULES_CURRENT_COMMIT, commit)
            await self.state_repo.set(RULES_CHUNK_COUNT, str(chunk_count))

            await interaction.followup.send(
                "\n".join(
                    [
                        f"Rules sync completed at commit `{commit}`.",
                        f"Artifact: `{artifact_path}`",
                        f"Index: `{index_path}`",
                        f"Chunks: `{chunk_count}`",
                    ]
                ),
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Rules sync failed: {exc}", ephemeral=True)

    @app_commands.command(name="status", description="Show the current rules repo and index status")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return

        last_sync_at = await self.state_repo.get(RULES_LAST_SYNC_AT)
        last_build_at = await self.state_repo.get(RULES_LAST_BUILD_AT)
        current_commit = await self.state_repo.get(RULES_CURRENT_COMMIT)
        chunk_count = await self.state_repo.get(RULES_CHUNK_COUNT)
        status = await self.sync_service.get_repo_status(last_sync_at=last_sync_at)

        lines = [
            f"Repo URL: `{status.repo_url}`",
            f"Branch: `{status.branch}`",
            f"Local repo path: `{status.local_path}`",
            f"Include paths: `{', '.join(status.include_paths)}`",
            f"Repo exists: `{status.repo_exists}`",
            f"Git repo: `{status.is_git_repo}`",
            f"Current synced commit: `{status.current_commit or current_commit or 'unknown'}`",
            f"Artifact path: `{self.bot.config.rules_sync.artifact_path}`",
            f"Index path: `{self.bot.config.rules_sync.rules_index_path}`",
            f"Chunk count: `{chunk_count or (self.retrieval_service.metadata.chunk_count if self.retrieval_service.metadata else 0)}`",
            f"Last successful sync: `{last_sync_at or 'never'}`",
            f"Last artifact build: `{last_build_at or 'never'}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    async def _run_build_command(self) -> None:
        command = self.bot.config.rules_sync.build_command
        if not command:
            return

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.bot.config.paths.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            output = stderr.decode().strip() or stdout.decode().strip() or "Build command failed."
            raise RuntimeError(output)

    async def _build_artifact(self) -> str:
        if self.bot.config.rules_sync.build_command:
            await self._run_build_command()
            artifact_path = self.artifact_builder.artifact_path()
            if not artifact_path.exists():
                raise RuntimeError(f"Build command completed but no artifact was found at {artifact_path}")
            return str(artifact_path)

        return str(self.artifact_builder.build())

    @staticmethod
    def _has_manage_guild(interaction: discord.Interaction) -> bool:
        permissions = interaction.permissions
        return bool(permissions and permissions.manage_guild)
