from __future__ import annotations

import asyncio

from bot.models.polls import Poll, PollOption, PollResults
from bot.storage.db import Database


class PollRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_poll(
        self,
        question: str,
        created_by: int,
        options: list[str],
        option_emojis: list[str],
        allow_vote_changes: bool = False,
    ) -> int:
        return await asyncio.to_thread(
            self._create_poll,
            question,
            created_by,
            options,
            option_emojis,
            allow_vote_changes,
        )

    def _create_poll(
        self,
        question: str,
        created_by: int,
        options: list[str],
        option_emojis: list[str],
        allow_vote_changes: bool,
    ) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO polls (question, created_by, allow_vote_changes)
                VALUES (?, ?, ?)
                """,
                (question, created_by, int(allow_vote_changes)),
            )
            poll_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO poll_options (poll_id, option_text, position, emoji)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (poll_id, option_text, idx, option_emojis[idx - 1])
                    for idx, option_text in enumerate(options, start=1)
                ],
            )
            return poll_id

    async def attach_message(self, poll_id: int, channel_id: int, message_id: int) -> None:
        await asyncio.to_thread(self._attach_message, poll_id, channel_id, message_id)

    def _attach_message(self, poll_id: int, channel_id: int, message_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE polls
                SET channel_id = ?, message_id = ?
                WHERE id = ?
                """,
                (channel_id, message_id, poll_id),
            )

    async def get_poll(self, poll_id: int) -> Poll | None:
        return await asyncio.to_thread(self._get_poll, poll_id)

    def _get_poll(self, poll_id: int) -> Poll | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
            return self._row_to_poll(row) if row else None

    async def get_options(self, poll_id: int) -> list[PollOption]:
        return await asyncio.to_thread(self._get_options, poll_id)

    def _get_options(self, poll_id: int) -> list[PollOption]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM poll_options WHERE poll_id = ? ORDER BY position ASC",
                (poll_id,),
            ).fetchall()
            return [self._row_to_option(row) for row in rows]

    async def get_poll_by_message(self, message_id: int) -> Poll | None:
        return await asyncio.to_thread(self._get_poll_by_message, message_id)

    def _get_poll_by_message(self, message_id: int) -> Poll | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM polls WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            return self._row_to_poll(row) if row else None

    async def get_option_by_emoji(self, poll_id: int, emoji: str) -> PollOption | None:
        return await asyncio.to_thread(self._get_option_by_emoji, poll_id, emoji)

    def _get_option_by_emoji(self, poll_id: int, emoji: str) -> PollOption | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM poll_options
                WHERE poll_id = ? AND emoji = ?
                """,
                (poll_id, emoji),
            ).fetchone()
            return self._row_to_option(row) if row else None

    async def record_reaction_vote(
        self,
        poll_id: int,
        option_id: int,
        user_id: int,
    ) -> tuple[str, int | None]:
        return await asyncio.to_thread(self._record_reaction_vote, poll_id, option_id, user_id)

    def _record_reaction_vote(
        self,
        poll_id: int,
        option_id: int,
        user_id: int,
    ) -> tuple[str, int | None]:
        with self.database.connect() as connection:
            poll_row = connection.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
            if not poll_row:
                return "not_found", None
            if not poll_row["is_open"]:
                return "closed", None

            option_row = connection.execute(
                "SELECT * FROM poll_options WHERE id = ? AND poll_id = ?",
                (option_id, poll_id),
            ).fetchone()
            if not option_row:
                return "invalid_option", None

            existing_vote = connection.execute(
                "SELECT option_id FROM poll_votes WHERE poll_id = ? AND user_id = ?",
                (poll_id, user_id),
            ).fetchone()
            if existing_vote and int(existing_vote["option_id"]) == option_id:
                return "unchanged", option_id
            if existing_vote and not poll_row["allow_vote_changes"]:
                return "duplicate_blocked", int(existing_vote["option_id"])

            if existing_vote:
                connection.execute(
                    """
                    UPDATE poll_votes
                    SET option_id = ?, voted_at = CURRENT_TIMESTAMP
                    WHERE poll_id = ? AND user_id = ?
                    """,
                    (option_id, poll_id, user_id),
                )
                return "updated", int(existing_vote["option_id"])

            connection.execute(
                """
                INSERT INTO poll_votes (poll_id, option_id, user_id)
                VALUES (?, ?, ?)
                """,
                (poll_id, option_id, user_id),
            )
            return "recorded", None

    async def remove_vote(self, poll_id: int, option_id: int, user_id: int) -> bool:
        return await asyncio.to_thread(self._remove_vote, poll_id, option_id, user_id)

    def _remove_vote(self, poll_id: int, option_id: int, user_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM poll_votes
                WHERE poll_id = ? AND option_id = ? AND user_id = ?
                """,
                (poll_id, option_id, user_id),
            )
            return cursor.rowcount > 0

    async def close_poll(self, poll_id: int) -> bool:
        return await asyncio.to_thread(self._close_poll, poll_id)

    def _close_poll(self, poll_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE polls
                SET is_open = 0, closed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND is_open = 1
                """,
                (poll_id,),
            )
            return cursor.rowcount > 0

    async def get_results(self, poll_id: int) -> PollResults | None:
        return await asyncio.to_thread(self._get_results, poll_id)

    def _get_results(self, poll_id: int) -> PollResults | None:
        with self.database.connect() as connection:
            poll_row = connection.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
            if not poll_row:
                return None

            option_rows = connection.execute(
                """
                SELECT o.*, COUNT(v.user_id) AS vote_count
                FROM poll_options o
                LEFT JOIN poll_votes v ON v.option_id = o.id
                WHERE o.poll_id = ?
                GROUP BY o.id
                ORDER BY o.position ASC
                """,
                (poll_id,),
            ).fetchall()
            return PollResults(
                poll=self._row_to_poll(poll_row),
                options=[
                    (self._row_to_option(row), int(row["vote_count"]))
                    for row in option_rows
                ],
            )

    @staticmethod
    def _row_to_poll(row: object) -> Poll:
        return Poll(
            id=int(row["id"]),
            question=row["question"],
            created_by=int(row["created_by"]),
            channel_id=int(row["channel_id"]) if row["channel_id"] is not None else None,
            message_id=int(row["message_id"]) if row["message_id"] is not None else None,
            allow_vote_changes=bool(row["allow_vote_changes"]),
            is_open=bool(row["is_open"]),
            created_at=row["created_at"],
            closed_at=row["closed_at"],
        )

    @staticmethod
    def _row_to_option(row: object) -> PollOption:
        return PollOption(
            id=int(row["id"]),
            poll_id=int(row["poll_id"]),
            option_text=row["option_text"],
            position=int(row["position"]),
            emoji=row["emoji"],
        )
