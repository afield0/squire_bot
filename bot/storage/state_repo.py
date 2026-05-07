from __future__ import annotations

import asyncio

from bot.storage.db import Database


class StateRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, key: str) -> str | None:
        return await asyncio.to_thread(self._get, key)

    def _get(self, key: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT state_value FROM bot_state WHERE state_key = ?",
                (key,),
            ).fetchone()
            return row["state_value"] if row else None

    async def set(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._set, key, value)

    def _set(self, key: str, value: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO bot_state (state_key, state_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(state_key)
                DO UPDATE SET state_value = excluded.state_value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )
