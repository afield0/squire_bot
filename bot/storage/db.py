from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    channel_id INTEGER,
                    message_id INTEGER,
                    allow_vote_changes INTEGER NOT NULL DEFAULT 0,
                    is_open INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS poll_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poll_id INTEGER NOT NULL,
                    option_text TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    emoji TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS poll_votes (
                    poll_id INTEGER NOT NULL,
                    option_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    voted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (poll_id, user_id),
                    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE,
                    FOREIGN KEY (option_id) REFERENCES poll_options(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_poll_options_poll_id ON poll_options(poll_id);
                CREATE INDEX IF NOT EXISTS idx_poll_votes_option_id ON poll_votes(option_id);

                CREATE TABLE IF NOT EXISTS daily_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seed_id TEXT,
                    category TEXT,
                    posted_at TEXT NOT NULL,
                    source_labels TEXT NOT NULL DEFAULT '[]',
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_daily_posts_seed_posted_at
                ON daily_posts(seed_id, posted_at);

                CREATE INDEX IF NOT EXISTS idx_daily_posts_channel_message
                ON daily_posts(channel_id, message_id);
                """
            )
            self._migrate_schema(connection)

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        poll_columns = self._get_columns(connection, "polls")
        if "channel_id" not in poll_columns:
            connection.execute("ALTER TABLE polls ADD COLUMN channel_id INTEGER")
        if "message_id" not in poll_columns:
            connection.execute("ALTER TABLE polls ADD COLUMN message_id INTEGER")

        option_columns = self._get_columns(connection, "poll_options")
        if "emoji" not in option_columns:
            connection.execute("ALTER TABLE poll_options ADD COLUMN emoji TEXT NOT NULL DEFAULT ''")

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_polls_message_id ON polls(message_id)
            WHERE message_id IS NOT NULL
            """
        )

    @staticmethod
    def _get_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}
