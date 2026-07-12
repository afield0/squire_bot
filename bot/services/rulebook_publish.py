from __future__ import annotations

import asyncio
import logging
import json
import os
import random
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord.ext import commands

from bot.storage.state_repo import StateRepository
from bot.utils.config import RulebookPublishConfig

LOGGER = logging.getLogger(__name__)

RULEBOOK_LAST_PUBLISHED_COMMIT = "rulebook_last_published_commit"
RULEBOOK_LAST_PUBLISHED_MESSAGE_ID = "rulebook_last_published_message_id"
RULEBOOK_LAST_PUBLISHED_AT = "rulebook_last_published_at"
RULEBOOK_LAST_PUBLISHED_CHANNEL_ID = "rulebook_last_published_channel_id"

RULEBOOK_POST_LINES = [
    "The latest rulebook has emerged from the crypt.",
    "Fresh ink, sharpened stakes, and updated rules await.",
    "A new rulebook has crossed the threshold.",
    "The night watch has filed an updated rulebook.",
    "The castle archives have yielded a new rulebook.",
    "A fresh dispatch from the vampire front is attached.",
    "The latest rules have been sealed in wax and posted.",
    "Moonlight reveals a new edition of the rulebook.",
    "The defenders have updated their field manual.",
    "A new rulebook rises for tonight's table.",
    "The latest tome is ready for brave defenders.",
    "The archive doors creak open with a new rulebook.",
]


@dataclass(slots=True)
class RulebookPublishRecord:
    commit: str
    source_commit: str
    message_id: int
    channel_id: int
    published_at: str
    message_url: str | None
    build_metadata: "RulebookBuildMetadata | None"


@dataclass(slots=True)
class RulebookPublishState:
    commit: str | None
    message_id: int | None
    channel_id: int | None
    published_at: str | None


@dataclass(slots=True)
class RulebookBuildMetadata:
    build_commit: str
    built_at: str | None
    metadata_path: Path


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
        build_metadata = self._load_build_metadata()
        published_commit = commit
        short_commit = published_commit[:12]
        commit_note = await self._get_commit_note(published_commit)
        published_at = datetime.now(UTC).isoformat()
        body = self._build_post_body(short_commit, commit_note)

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
            commit=published_commit,
            source_commit=commit,
            message_id=message.id,
            channel_id=self.config.channel_id,
            published_at=published_at,
            message_url=message.jump_url,
            build_metadata=build_metadata,
        )
        await self._store_record(record)

        if self.config.delete_previous and previous_state.message_id and previous_state.channel_id:
            await self._delete_previous(previous_state)

        LOGGER.info(
            "Published rulebook commit=%s channel_id=%s message_id=%s path=%s size=%s",
            published_commit,
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

    def _load_build_metadata(self) -> RulebookBuildMetadata | None:
        metadata_path = self._metadata_path()
        if not metadata_path.exists():
            return None
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Could not read rulebook build metadata at %s: %s", metadata_path, exc)
            return None

        build_commit = str(payload.get("build_commit") or payload.get("commit") or "").strip()
        if not build_commit:
            LOGGER.warning("Rulebook build metadata at %s does not include build_commit", metadata_path)
            return None
        built_at = payload.get("built_at")
        return RulebookBuildMetadata(
            build_commit=build_commit,
            built_at=str(built_at).strip() if built_at else None,
            metadata_path=metadata_path,
        )

    def _metadata_path(self) -> Path:
        return self.config.pdf_path.with_name(f"{self.config.pdf_path.stem}.metadata.json")

    async def _get_commit_note(self, commit: str) -> str | None:
        return await asyncio.to_thread(self._read_git_commit_note, commit)

    def _read_git_commit_note(self, commit: str) -> str | None:
        try:
            env = os.environ.copy()
            # A partial clone may need to contact its promisor remote even for
            # `git show`. Commit notes are optional, so never let that lookup
            # block the bot waiting for interactive GitHub credentials.
            env["GIT_TERMINAL_PROMPT"] = "0"
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.config.pdf_path.parent),
                    "show",
                    "-s",
                    "--format=%B",
                    commit,
                ],
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            LOGGER.warning("Could not read rulebook commit note for %s: %s", commit, exc)
            return None
        return result.stdout.strip() or None

    def _build_post_body(self, short_commit: str, commit_note: str | None) -> str:
        lines = [
            "**Latest Vampire Defenders Rulebook**",
            f"Build commit: `{short_commit}`",
            self._random_post_line(),
        ]
        if commit_note:
            lines.extend(["", "**Commit note**", self._format_commit_note(commit_note)])
        lines.extend(["", "Attached below."])
        return "\n".join(lines)

    @staticmethod
    def _format_commit_note(commit_note: str) -> str:
        normalized_lines = [line.rstrip() for line in commit_note.strip().splitlines()]
        normalized = "\n".join(normalized_lines).strip()
        if len(normalized) > 1200:
            normalized = f"{normalized[:1197].rstrip()}..."
        return "\n".join(f"> {line}" if line else ">" for line in normalized.splitlines())

    @staticmethod
    def _random_post_line() -> str:
        return random.choice(RULEBOOK_POST_LINES)
