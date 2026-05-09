from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.models.rules import LLMAnswer
from bot.services.build_cards_artifact import CardsArtifactBuilder
from bot.services.build_rules_artifact import RulesArtifactBuilder
from bot.services.github_sync import GitHubRulesSyncService
from bot.services.openai_client import OpenAIRulesClient
from bot.services.rulebook_publish import RulebookPublishService
from bot.storage.state_repo import StateRepository

LOGGER = logging.getLogger(__name__)

RULES_LAST_SYNC_AT = "rules_last_sync_at"
RULES_LAST_BUILD_AT = "rules_last_build_at"
RULES_CURRENT_COMMIT = "rules_current_commit"


class RulesCog(commands.GroupCog, group_name="rules", group_description="Rules lookup commands"):
    def __init__(
        self,
        bot: commands.Bot,
        state_repo: StateRepository,
        sync_service: GitHubRulesSyncService,
        artifact_builder: RulesArtifactBuilder,
        cards_artifact_builder: CardsArtifactBuilder,
        openai_client: OpenAIRulesClient,
        rulebook_publish_service: RulebookPublishService,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.state_repo = state_repo
        self.sync_service = sync_service
        self.artifact_builder = artifact_builder
        self.cards_artifact_builder = cards_artifact_builder
        self.openai_client = openai_client
        self.rulebook_publish_service = rulebook_publish_service
        self._sync_lock = asyncio.Lock()
        if self.bot.config.rulebook.auto_publish:
            self.rulebook_auto_publish_loop.start()

    def cog_unload(self) -> None:
        if self.rulebook_auto_publish_loop.is_running():
            self.rulebook_auto_publish_loop.cancel()

    @tasks.loop(minutes=15)
    async def rulebook_auto_publish_loop(self) -> None:
        if not self.bot.config.rulebook.channel_id:
            return
        try:
            await self._sync_build_and_maybe_publish_rulebook()
        except Exception as exc:
            LOGGER.warning("Rulebook auto-publish check failed: %s", exc)

    @rulebook_auto_publish_loop.before_loop
    async def before_rulebook_auto_publish_loop(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="ask", description="Ask a rules question from the local rulebook artifact")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer(thinking=True)

        try:
            artifact_path, rulebook_text = await self._load_rulebook_text()
        except Exception as exc:
            await interaction.followup.send(f"Rules lookup failed: {exc}", ephemeral=True)
            return

        if not self.bot.config.openai.rules_use_llm:
            await interaction.followup.send(
                "LLM mode is disabled. Set `RULES_USE_LLM=true` to answer from the full rulebook artifact.",
                ephemeral=True,
            )
            return
        if not self.openai_client.available():
            await interaction.followup.send(
                self._fallback_message(
                    artifact_path=artifact_path,
                    used_openai=False,
                    latency_ms=None,
                    reason=self.openai_client.availability_error(),
                ),
                ephemeral=True,
            )
            return

        latency_ms: float | None = None
        used_openai = False
        try:
            started = time.perf_counter()
            used_openai = True
            answer = await asyncio.to_thread(
                self.openai_client.answer_rules_question,
                question,
                rulebook_text,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            await interaction.followup.send(self._format_answer(question, answer), ephemeral=False)
        except Exception as exc:
            if "started" in locals():
                latency_ms = round((time.perf_counter() - started) * 1000, 1)
            LOGGER.warning("Falling back after OpenAI failure: %s", exc)
            await interaction.followup.send(
                self._fallback_message(
                    artifact_path=artifact_path,
                    used_openai=used_openai,
                    latency_ms=latency_ms,
                    reason=str(exc),
                ),
                ephemeral=True,
            )

    @app_commands.command(name="sync", description="Sync the private rules repo and rebuild the local rulebook artifact")
    @app_commands.default_permissions(manage_guild=True)
    async def sync(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            result = await self._sync_build_and_maybe_publish_rulebook()

            lines = [
                f"Rules sync completed at commit `{result['commit']}`.",
                f"Artifact: `{result['artifact_path']}`",
                f"Artifact size: `{result['artifact_size']}` bytes",
                f"Cards artifact: `{result['cards_artifact_path']}`",
                f"Cards artifact size: `{result['cards_artifact_size']}` bytes",
            ]
            if result["rulebook_publish"]:
                lines.append(f"Rulebook PDF published: `{result['rulebook_publish'].message_id}`")
                if result["rulebook_publish"].message_url:
                    lines.append(f"Rulebook message: {result['rulebook_publish'].message_url}")
            if result["rulebook_publish_error"]:
                lines.append(f"Rulebook auto-publish failed: `{result['rulebook_publish_error']}`")

            await interaction.followup.send(
                "\n".join(lines),
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Rules sync failed: {exc}", ephemeral=True)

    @app_commands.command(name="status", description="Show the current rules repo and artifact status")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return

        last_sync_at = await self.state_repo.get(RULES_LAST_SYNC_AT)
        last_build_at = await self.state_repo.get(RULES_LAST_BUILD_AT)
        current_commit = await self.state_repo.get(RULES_CURRENT_COMMIT)
        status = await self.sync_service.get_repo_status(last_sync_at=last_sync_at)

        artifact_path = self.bot.config.rules_sync.artifact_path
        artifact_exists = artifact_path.exists()
        artifact_size = artifact_path.stat().st_size if artifact_exists else 0
        cards_artifact_path = self.bot.config.rules_sync.cards_artifact_path
        cards_artifact_exists = cards_artifact_path.exists()
        cards_artifact_size = cards_artifact_path.stat().st_size if cards_artifact_exists else 0
        lines = [
            f"Repo URL: `{status.repo_url}`",
            f"Branch: `{status.branch}`",
            f"Local repo path: `{status.local_path}`",
            f"Current synced commit: `{status.current_commit or current_commit or 'unknown'}`",
            f"Artifact path: `{artifact_path}`",
            f"Artifact exists: `{artifact_exists}`",
            f"Artifact size: `{artifact_size}` bytes",
            f"Cards artifact path: `{cards_artifact_path}`",
            f"Cards artifact exists: `{cards_artifact_exists}`",
            f"Cards artifact size: `{cards_artifact_size}` bytes",
            f"Last successful sync: `{last_sync_at or 'never'}`",
            f"Last artifact build: `{last_build_at or 'never'}`",
            f"LLM mode enabled: `{self.bot.config.openai.rules_use_llm}`",
            f"OpenAI available: `{self.openai_client.available()}`",
            f"OpenAI model: `{self.bot.config.openai.model}`",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="debug", description="Admin-only debug details for a full-rulebook rules query")
    @app_commands.default_permissions(manage_guild=True)
    async def debug(self, interaction: discord.Interaction, question: str) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        artifact_loaded = False
        artifact_path = self.bot.config.rules_sync.artifact_path
        artifact_chars = 0
        used_openai = False
        latency_ms: float | None = None

        try:
            artifact_path, rulebook_text = await self._load_rulebook_text()
            artifact_loaded = True
            artifact_chars = len(rulebook_text)

            if self.bot.config.openai.rules_use_llm:
                started = time.perf_counter()
                await asyncio.to_thread(
                    self.openai_client.answer_rules_question,
                    question,
                    rulebook_text,
                )
                latency_ms = round((time.perf_counter() - started) * 1000, 1)
                used_openai = True
        except Exception as exc:
            LOGGER.warning("Rules debug command encountered an error: %s", exc)

        lines = [
            f"Artifact loaded: `{artifact_loaded}`",
            f"Artifact path: `{artifact_path}`",
            f"Artifact size (chars): `{artifact_chars}`",
            f"OpenAI enabled: `{self.bot.config.openai.rules_use_llm}`",
            f"OpenAI used: `{used_openai}`",
            f"OpenAI available: `{self.openai_client.available()}`",
            f"OpenAI availability error: `{self.openai_client.availability_error() or 'none'}`",
            f"Model: `{self.bot.config.openai.model}`",
            f"Latency: `{latency_ms if latency_ms is not None else 'n/a'} ms`",
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

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

    async def _build_artifact(self) -> Path:
        if self.bot.config.rules_sync.build_command:
            await self._run_build_command()
            artifact_path = self.artifact_builder.artifact_path()
            if not artifact_path.exists():
                raise RuntimeError(f"Build command completed but no artifact was found at {artifact_path}")
            LOGGER.info("Rules artifact build completed path=%s size=%s", artifact_path, artifact_path.stat().st_size)
            return artifact_path

        artifact_path = self.artifact_builder.build()
        LOGGER.info("Rules artifact build completed path=%s size=%s", artifact_path, artifact_path.stat().st_size)
        return artifact_path

    async def _sync_build_and_maybe_publish_rulebook(self) -> dict[str, object]:
        async with self._sync_lock:
            commit = await self.sync_service.ensure_repo_synced()
            artifact_path = await self._build_artifact()
            cards_artifact_path = await asyncio.to_thread(self.cards_artifact_builder.build)

            now = datetime.now(UTC).isoformat()
            await self.state_repo.set(RULES_LAST_SYNC_AT, now)
            await self.state_repo.set(RULES_LAST_BUILD_AT, now)
            await self.state_repo.set(RULES_CURRENT_COMMIT, commit)

            rulebook_publish = None
            rulebook_publish_error = None
            try:
                rulebook_publish = await self.rulebook_publish_service.maybe_publish_for_commit(commit)
            except Exception as exc:
                rulebook_publish_error = str(exc)
                LOGGER.warning("Rulebook auto-publish failed after sync: %s", exc)
            return {
                "commit": commit,
                "artifact_path": artifact_path,
                "artifact_size": artifact_path.stat().st_size,
                "cards_artifact_path": cards_artifact_path,
                "cards_artifact_size": cards_artifact_path.stat().st_size,
                "rulebook_publish": rulebook_publish,
                "rulebook_publish_error": rulebook_publish_error,
            }

    async def _load_rulebook_text(self) -> tuple[Path, str]:
        artifact_path = self.artifact_builder.artifact_path()
        if not artifact_path.exists():
            raise RuntimeError("No local rulebook artifact is available. Run `/rules sync` first.")

        # TODO: If the rulebook outgrows full-context prompts, add an optional retrieval path here.
        rulebook_text = await asyncio.to_thread(artifact_path.read_text, encoding="utf-8")
        LOGGER.info("Loaded rules artifact path=%s chars=%s", artifact_path, len(rulebook_text))
        return artifact_path, rulebook_text

    def _format_answer(self, question: str, answer: LLMAnswer) -> str:
        lines = [
            f"Question: {question.strip()}",
            "",
            answer.answer.strip(),
        ]

        if answer.ambiguity_note and answer.status == "ambiguous":
            lines.append("")
            lines.append(f"Uncertainty: {answer.ambiguity_note}")

        if answer.citations:
            lines.append("")
            lines.append("Sources:")
            for citation in answer.citations[:4]:
                lines.append(f"- {citation.label}")

        return self._trim_for_discord("\n".join(lines))

    def _fallback_message(
        self,
        artifact_path: Path,
        used_openai: bool,
        latency_ms: float | None,
        reason: str | None,
    ) -> str:
        LOGGER.info(
            "Rules fallback activated artifact=%s used_openai=%s latency_ms=%s reason=%s",
            artifact_path,
            used_openai,
            latency_ms,
            reason,
        )
        lines = [
            "I couldn't get a grounded answer from OpenAI right now.",
            "The local rulebook artifact is still available, but the LLM answer path failed or timed out.",
            f"Artifact: `{artifact_path}`",
        ]
        if reason:
            lines.append(f"Reason: `{reason}`")
        return "\n".join(lines)

    @staticmethod
    def _trim_for_discord(text: str, limit: int = 1900) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _has_manage_guild(interaction: discord.Interaction) -> bool:
        permissions = interaction.permissions
        return bool(permissions and permissions.manage_guild)
