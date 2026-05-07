from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.storage.state_repo import StateRepository


@dataclass(slots=True)
class ScheduledJob:
    key: str
    hour: int
    minute: int


class SchedulerService:
    def __init__(self, state_repo: StateRepository, timezone_name: str) -> None:
        self.state_repo = state_repo
        self.timezone = ZoneInfo(timezone_name)

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    async def should_run(self, job: ScheduledJob) -> bool:
        now = self.now()
        if (now.hour, now.minute) < (job.hour, job.minute):
            return False

        last_run = await self.state_repo.get(job.key)
        return last_run != now.date().isoformat()

    async def mark_ran(self, job: ScheduledJob) -> None:
        await self.state_repo.set(job.key, self.now().date().isoformat())
