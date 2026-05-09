from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bot.storage.db import Database


@dataclass(frozen=True, slots=True)
class RecentDailySeedPost:
    seed_id: str
    posted_date: date


class DailyHistoryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def record_post(
        self,
        *,
        seed_id: str | None,
        category: str | None,
        posted_at: datetime,
        source_labels: list[str],
        channel_id: int,
        message_id: int,
    ) -> None:
        self._record_post(
            seed_id,
            category,
            posted_at,
            source_labels,
            channel_id,
            message_id,
        )

    def _record_post(
        self,
        seed_id: str | None,
        category: str | None,
        posted_at: datetime,
        source_labels: list[str],
        channel_id: int,
        message_id: int,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_posts (
                    seed_id,
                    category,
                    posted_at,
                    source_labels,
                    channel_id,
                    message_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    seed_id,
                    category,
                    posted_at.isoformat(),
                    json.dumps(source_labels),
                    channel_id,
                    message_id,
                ),
            )

    async def fetch_recent_seed_posts(self, today: date, days: int) -> list[RecentDailySeedPost]:
        return self._fetch_recent_seed_posts(today, days)

    def _fetch_recent_seed_posts(self, today: date, days: int) -> list[RecentDailySeedPost]:
        cutoff = today - timedelta(days=max(0, days))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT seed_id, MAX(substr(posted_at, 1, 10)) AS posted_date
                FROM daily_posts
                WHERE seed_id IS NOT NULL
                  AND substr(posted_at, 1, 10) >= ?
                GROUP BY seed_id
                """,
                (cutoff.isoformat(),),
            ).fetchall()
        return [
            RecentDailySeedPost(seed_id=row["seed_id"], posted_date=date.fromisoformat(row["posted_date"]))
            for row in rows
        ]
