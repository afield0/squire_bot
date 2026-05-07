from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.models.polls import PollOption
from bot.storage.poll_repo import PollRepository


class PollsCog(commands.GroupCog, group_name="poll", group_description="Playtest poll commands"):
    OPTION_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    def __init__(self, bot: commands.Bot, poll_repo: PollRepository) -> None:
        super().__init__()
        self.bot = bot
        self.poll_repo = poll_repo

    @app_commands.command(name="create", description="Create a playtest poll")
    @app_commands.default_permissions(manage_guild=True)
    async def create(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str,
        allow_vote_changes: bool = False,
    ) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return
        await interaction.response.defer(thinking=False, ephemeral=True)
        parsed_options = [part.strip() for part in options.split(",") if part.strip()]
        if len(parsed_options) < 2:
            await interaction.followup.send(
                "Provide at least two comma-separated options.",
                ephemeral=True,
            )
            return
        if len(parsed_options) > len(self.OPTION_EMOJIS):
            await interaction.followup.send(
                f"Provide at most {len(self.OPTION_EMOJIS)} options.",
                ephemeral=True,
            )
            return
        if not interaction.channel or not hasattr(interaction.channel, "send"):
            await interaction.followup.send(
                "This command must be used in a server text channel.",
                ephemeral=True,
            )
            return

        option_emojis = self.OPTION_EMOJIS[: len(parsed_options)]
        poll_id = await self.poll_repo.create_poll(
            question=question,
            created_by=interaction.user.id,
            options=parsed_options,
            option_emojis=option_emojis,
            allow_vote_changes=allow_vote_changes,
        )
        option_rows = await self.poll_repo.get_options(poll_id)
        poll_message = await interaction.channel.send(
            self._render_poll_message(poll_id, question, option_rows, allow_vote_changes)
        )
        for option in option_rows:
            await poll_message.add_reaction(option.emoji)

        await self.poll_repo.attach_message(
            poll_id=poll_id,
            channel_id=interaction.channel.id,
            message_id=poll_message.id,
        )
        await interaction.followup.send(
            f"Poll `{poll_id}` created in {interaction.channel.mention}. Vote by reacting to the poll message.",
            ephemeral=True,
        )

    @app_commands.command(name="results", description="Show poll results")
    @app_commands.default_permissions(manage_guild=True)
    async def results(self, interaction: discord.Interaction, id: int) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return
        results = await self.poll_repo.get_results(id)
        if not results:
            await interaction.response.send_message("Poll not found.", ephemeral=True)
            return

        lines = [
            f"Poll `{results.poll.id}`: {results.poll.question}",
            f"Status: {'open' if results.poll.is_open else 'closed'}",
        ]
        lines.extend(
            f"- {option.emoji} `{option.id}` {option.option_text}: **{count}** vote(s)"
            for option, count in results.options
        )
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="close", description="Close an existing poll")
    @app_commands.default_permissions(manage_guild=True)
    async def close(self, interaction: discord.Interaction, id: int) -> None:
        if not self._has_manage_guild(interaction):
            await interaction.response.send_message("Manage Server is required.", ephemeral=True)
            return
        closed = await self.poll_repo.close_poll(id)
        if not closed:
            await interaction.response.send_message(
                "Poll not found or already closed.",
                ephemeral=True,
            )
            return
        await self._close_poll_message(id)
        await interaction.response.send_message(f"Poll `{id}` is now closed.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id:
            return
        await self._handle_reaction_add(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id:
            return
        poll = await self.poll_repo.get_poll_by_message(payload.message_id)
        if not poll or not poll.is_open:
            return
        option = await self.poll_repo.get_option_by_emoji(poll.id, str(payload.emoji))
        if not option:
            return
        await self.poll_repo.remove_vote(poll.id, option.id, payload.user_id)

    @staticmethod
    def _has_manage_guild(interaction: discord.Interaction) -> bool:
        permissions = interaction.permissions
        return bool(permissions and permissions.manage_guild)

    async def _handle_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        poll = await self.poll_repo.get_poll_by_message(payload.message_id)
        if not poll:
            return

        message = await self._fetch_message(payload.channel_id, payload.message_id)
        if not poll.is_open:
            await self._remove_user_reaction(message, str(payload.emoji), payload.user_id)
            return

        option = await self.poll_repo.get_option_by_emoji(poll.id, str(payload.emoji))
        if not option:
            return

        status, previous_option_id = await self.poll_repo.record_reaction_vote(
            poll_id=poll.id,
            option_id=option.id,
            user_id=payload.user_id,
        )

        if status == "duplicate_blocked":
            await self._remove_user_reaction(message, str(payload.emoji), payload.user_id)
            return
        if status == "updated" and previous_option_id is not None:
            previous_option = await self._get_option_by_id(poll.id, previous_option_id)
            if previous_option:
                await self._remove_user_reaction(message, previous_option.emoji, payload.user_id)
            return
        if status in {"closed", "invalid_option"}:
            await self._remove_user_reaction(message, str(payload.emoji), payload.user_id)

    async def _close_poll_message(self, poll_id: int) -> None:
        poll = await self.poll_repo.get_poll(poll_id)
        if not poll or not poll.channel_id or not poll.message_id:
            return

        message = await self._fetch_message(poll.channel_id, poll.message_id)
        if not message:
            return

        options = await self.poll_repo.get_options(poll_id)
        updated = self._render_poll_message(
            poll.id,
            poll.question,
            options,
            poll.allow_vote_changes,
            is_open=False,
        )
        await message.edit(content=updated)
        try:
            await message.clear_reactions()
        except discord.Forbidden:
            pass

    async def _fetch_message(
        self,
        channel_id: int,
        message_id: int,
    ) -> discord.Message | None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                return None
        if not isinstance(channel, discord.abc.Messageable):
            return None
        try:
            return await channel.fetch_message(message_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return None

    async def _remove_user_reaction(
        self,
        message: discord.Message | None,
        emoji: str,
        user_id: int,
    ) -> None:
        if message is None:
            return
        try:
            user = message.guild.get_member(user_id) if message.guild else None
            if user is None:
                user = await self.bot.fetch_user(user_id)
            await message.remove_reaction(emoji, user)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return

    async def _get_option_by_id(self, poll_id: int, option_id: int) -> PollOption | None:
        options = await self.poll_repo.get_options(poll_id)
        for option in options:
            if option.id == option_id:
                return option
        return None

    @staticmethod
    def _render_poll_message(
        poll_id: int,
        question: str,
        options: list[PollOption],
        allow_vote_changes: bool,
        is_open: bool = True,
    ) -> str:
        lines = [
            f"**Poll {poll_id}**",
            question,
            "",
            "React to vote:" if is_open else "Poll closed. Final options were:",
        ]
        lines.extend(f"{option.emoji} {option.option_text}" for option in options)
        lines.append("")
        lines.append(
            "Vote changes allowed." if allow_vote_changes else "One vote per user."
        )
        return "\n".join(lines)
