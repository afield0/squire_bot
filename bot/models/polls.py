from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Poll:
    id: int
    question: str
    created_by: int
    channel_id: int | None
    message_id: int | None
    allow_vote_changes: bool
    is_open: bool
    created_at: str
    closed_at: str | None


@dataclass(slots=True)
class PollOption:
    id: int
    poll_id: int
    option_text: str
    position: int
    emoji: str


@dataclass(slots=True)
class PollResults:
    poll: Poll
    options: list[tuple[PollOption, int]]
