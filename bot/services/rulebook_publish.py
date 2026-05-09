from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import discord
from discord.ext import commands

from bot.storage.state_repo import StateRepository
from bot.utils.config import RulebookPublishConfig

LOGGER = logging.getLogger(__name__)

RULEBOOK_LAST_PUBLISHED_COMMIT = "rulebook_last_published_commit"
RULEBOOK_LAST_PUBLISHED_MESSAGE_ID = "rulebook_last_published_message_id"
RULEBOOK_LAST_PUBLISHED_AT = "rulebook_last_published_at"
RULEBOOK_LAST_PUBLISHED_CHANNEL_ID = "rulebook_last_published_channel_id"


@dataclass(slots=True)
class RulebookPublishRecord:
    commit: str
    message_id: int
    channel_id: int
    published_at: str
    message_url: str | None


@dataclass(slots=True)
class RulebookPublishState:
    commit: str | None
    message_id: int | None
    channel_id: int | None
    published_at: str | None


class RulebookPublishService:
    def __init__(
        self,
        config: RulebookPublishConfig,
        state_repo: StateRepository,
        bot: commands.Bot,
    ) -> None:
        self.config = config
        self.state_repo = state_repo
        self.bot = bot

    async def publish(self, commit: str) -> RulebookPublishRecord:
        if not commit:
            raise RuntimeError("Current rules repo commit is unavailable. Run `/rules sync` first.")
        if not self.config.channel_id:
            raise RuntimeError("RULEBOOK_CHANNEL_ID is not configured.")
        if not self.config.pdf_path.exists():
            raise RuntimeError(f"No rulebook PDF was found at {self.config.pdf_path}. Run the rules sync/build first.")
        if not self.config.pdf_path.is_file():
            raise RuntimeError(f"Configured rulebook PDF path is not a file: {self.config.pdf_path}")

        channel = await self._resolve_channel(self.config.channel_id)
        upload_limit = self._upload_limit(channel)
        file_size = self.config.pdf_path.stat().st_size
        if upload_limit and file_size > upload_limit:
            raise RuntimeError(
                f"Rulebook PDF is too large for this Discord upload limit "
                f"({file_size} bytes > {upload_limit} bytes)."
            )

        previous_state = await self.get_state()
        short_commit = commit[:12]
        published_at = datetime.now(UTC).isoformat()
        body = "\n".join(
            [
                "**Latest Vampire Defenders Rulebook**",
                f"Build commit: `{short_commit}`",
                "",
                "Attached below.",
            ]
        )

        try:
            message = await channel.send(
                content=body,
                file=discord.File(self.config.pdf_path, filename=self.config.pdf_path.name),
            )
        except discord.Forbidden as exc:
            raise RuntimeError("Bot lacks permission to post messages or attach files in the rulebook channel.") from exc
        except discord.HTTPException as exc:
            raise RuntimeError(f"Discord rejected the rulebook upload: {exc}") from exc

        record = RulebookPublishRecord(
            commit=commit,
            message_id=message.id,
            channel_id=self.config.channel_id,
            published_at=published_at,
            message_url=message.jump_url,
        )
        await self._store_record(record)

        if self.config.delete_previous and previous_state.message_id and previous_state.channel_id:
            await self._delete_previous(previous_state)

        LOGGER.info(
            "Published rulebook commit=%s channel_id=%s message_id=%s path=%s size=%s",
            commit,
            self.config.channel_id,
            message.id,
            self.config.pdf_path,
            file_size,
        )
        return record

    async def maybe_publish_for_commit(self, commit: str) -> RulebookPublishRecord | None:
        if not self.config.auto_publish:
            return None
        if not self.config.channel_id:
            return None
        state = await self.get_state()
        if state.commit == commit:
            return None
        return await self.publish(commit)

    async def get_state(self) -> RulebookPublishState:
        message_id = await self._get_int(RULEBOOK_LAST_PUBLISHED_MESSAGE_ID)
        channel_id = await self._get_int(RULEBOOK_LAST_PUBLISHED_CHANNEL_ID)
        return RulebookPublishState(
            commit=await self.state_repo.get(RULEBOOK_LAST_PUBLISHED_COMMIT),
            message_id=message_id,
            channel_id=channel_id,
            published_at=await self.state_repo.get(RULEBOOK_LAST_PUBLISHED_AT),
        )

    async def _resolve_channel(self, channel_id: int) -> discord.abc.Messageable:
        cached = self.bot.get_channel(channel_id)
        if cached and hasattr(cached, "send"):
            return cached

        try:
            fetched = await self.bot.fetch_channel(channel_id)
        except discord.NotFound as exc:
            raise RuntimeError(f"Configured rulebook channel does not exist: {channel_id}") from exc
        except discord.Forbidden as exc:
            raise RuntimeError(f"Bot cannot access the configured rulebook channel: {channel_id}") from exc
        except discord.HTTPException as exc:
            raise RuntimeError(f"Could not resolve configured rulebook channel {channel_id}: {exc}") from exc

        if not hasattr(fetched, "send"):
            raise RuntimeError(f"Configured rulebook channel cannot receive messages: {channel_id}")
        return fetched

    async def _store_record(self, record: RulebookPublishRecord) -> None:
        await self.state_repo.set(RULEBOOK_LAST_PUBLISHED_COMMIT, record.commit)
        await self.state_repo.set(RULEBOOK_LAST_PUBLISHED_MESSAGE_ID, str(record.message_id))
        await self.state_repo.set(RULEBOOK_LAST_PUBLISHED_AT, record.published_at)
        await self.state_repo.set(RULEBOOK_LAST_PUBLISHED_CHANNEL_ID, str(record.channel_id))

    async def _delete_previous(self, state: RulebookPublishState) -> None:
        if not state.channel_id or not state.message_id:
            return
        try:
            channel = await self._resolve_channel(state.channel_id)
            if not hasattr(channel, "fetch_message"):
                LOGGER.warning("Cannot delete previous rulebook message; channel does not support fetch_message")
                return
            message = await channel.fetch_message(state.message_id)
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException, RuntimeError) as exc:
            LOGGER.warning(
                "Failed to delete previous rulebook message channel_id=%s message_id=%s: %s",
                state.channel_id,
                state.message_id,
                exc,
            )

    async def _get_int(self, key: str) -> int | None:
        value = await self.state_repo.get(key)
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            LOGGER.warning("Ignoring non-integer state value for %s: %s", key, value)
            return None

    @staticmethod
    def _upload_limit(channel: discord.abc.Messageable) -> int | None:
        guild = getattr(channel, "guild", None)
        return getattr(guild, "filesize_limit", None) or 25 * 1024 * 1024
