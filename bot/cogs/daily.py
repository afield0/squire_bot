from __future__ import annotations

from datetime import date

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.services.content import DailyContentService
from bot.services.scheduler import ScheduledJob, SchedulerService
from bot.storage.state_repo import StateRepository


class DailyCog(commands.GroupCog, group_name="daily", group_description="Daily scheduled content"):
    def __init__(
        self,
        bot: commands.Bot,
        state_repo: StateRepository,
        content_service: DailyContentService,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.state_repo = state_repo
        self.content_service = content_service
        self.scheduler = SchedulerService(state_repo, bot.config.daily.timezone_name)
        self.topic_job = ScheduledJob(
            key="daily_topic_of_day",
            hour=bot.config.daily.post_hour,
            minute=bot.config.daily.post_minute,
        )
        self.design_job = ScheduledJob(
            key="daily_design_prompt",
            hour=bot.config.daily.post_hour,
            minute=bot.config.daily.post_minute,
        )
        self.scheduler_loop.start()

    def cog_unload(self) -> None:
        self.scheduler_loop.cancel()

    @tasks.loop(minutes=1)
    async def scheduler_loop(self) -> None:
        await self._maybe_post_scheduled_items()

    @scheduler_loop.before_loop
    async def before_scheduler_loop(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="preview", description="Preview the current daily content")
    @app_commands.default_permissions(manage_guild=True)
    async def preview(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return
        today = self.scheduler.now().date()
        topic = self.content_service.build_topic_of_day(today).render()
        lines = [topic]
        if self.bot.config.daily.enable_design_prompt:
            lines.append("")
            lines.append(self.content_service.build_design_prompt(today).render())
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="post", description="Post the current daily content immediately")
    @app_commands.default_permissions(manage_guild=True)
    async def post(self, interaction: discord.Interaction) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self._post_for_date(self.scheduler.now().date(), mark_state=False)
            await interaction.followup.send("Daily post sent.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Daily post failed: {exc}", ephemeral=True)

    async def _maybe_post_scheduled_items(self) -> None:
        today = self.scheduler.now().date()
        if await self.scheduler.should_run(self.topic_job):
            await self._send_topic_post(today)
            await self.scheduler.mark_ran(self.topic_job)

        if (
            self.bot.config.daily.enable_design_prompt
            and self.bot.config.daily.design_prompt_channel_id
            and await self.scheduler.should_run(self.design_job)
        ):
            await self._send_design_prompt(today)
            await self.scheduler.mark_ran(self.design_job)

    async def _post_for_date(self, target_date: date, mark_state: bool) -> None:
        await self._send_topic_post(target_date)
        if mark_state:
            await self.scheduler.mark_ran(self.topic_job)

        if self.bot.config.daily.enable_design_prompt and self.bot.config.daily.design_prompt_channel_id:
            await self._send_design_prompt(target_date)
            if mark_state:
                await self.scheduler.mark_ran(self.design_job)

    async def _send_topic_post(self, target_date: date) -> None:
        channel_id = self.bot.config.daily.topic_channel_id
        if not channel_id:
            return
        channel = await self._resolve_channel(channel_id)
        if channel is None:
            return
        await channel.send(self.content_service.build_topic_of_day(target_date).render())

    async def _send_design_prompt(self, target_date: date) -> None:
        channel_id = self.bot.config.daily.design_prompt_channel_id
        if not channel_id:
            return
        channel = await self._resolve_channel(channel_id)
        if channel is None:
            return
        await channel.send(self.content_service.build_design_prompt(target_date).render())

    async def _resolve_channel(self, channel_id: int) -> discord.abc.Messageable | None:
        cached = self.bot.get_channel(channel_id)
        if cached and hasattr(cached, "send"):
            return cached

        fetched = await self.bot.fetch_channel(channel_id)
        if hasattr(fetched, "send"):
            return fetched
        return None

    @staticmethod
    def _has_manage_guild(interaction: discord.Interaction) -> bool:
        permissions = interaction.permissions
        return bool(permissions and permissions.manage_guild)
