from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from bot.utils.config import RulesSyncConfig

import asyncio

LOGGER = logging.getLogger(__name__)


class GitHubRulesSyncService:
    def __init__(self, config: RulesSyncConfig) -> None:
        self.config = config

    async def ensure_local_checkout(self) -> str:
        self.config.local_checkout_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.config.repo_url:
            raise RuntimeError("GITHUB_RULES_REPO_URL is not configured.")
        if not self.config.include_paths:
            raise RuntimeError("GITHUB_RULES_INCLUDE_PATHS must include at least one path.")

        if not self.config.local_checkout_path.exists():
            await self._clone_sparse()
        else:
            await self._update_sparse_settings()
            await self._pull()

        revision = await self.get_current_revision()
        LOGGER.info("Rules checkout ready at revision %s", revision)
        return revision

    async def get_current_revision(self) -> str:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.config.local_checkout_path),
            "rev-parse",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode().strip() or "Failed to resolve git revision.")
        return stdout.decode().strip()

    async def _clone_sparse(self) -> None:
        remote_url = self._authenticated_repo_url()
        LOGGER.info("Cloning rules repo into %s", self.config.local_checkout_path)
        await self._run(
            "git",
            "clone",
            "--filter=blob:none",
            "--sparse",
            "--branch",
            self.config.branch,
            remote_url,
            str(self.config.local_checkout_path),
        )
        await self._update_sparse_settings()

    async def _update_sparse_settings(self) -> None:
        await self._run(
            "git",
            "-C",
            str(self.config.local_checkout_path),
            "sparse-checkout",
            "set",
            "--no-cone",
            *self.config.include_paths,
        )

    async def _pull(self) -> None:
        await self._run(
            "git",
            "-C",
            str(self.config.local_checkout_path),
            "remote",
            "set-url",
            "origin",
            self._authenticated_repo_url(),
        )
        await self._run(
            "git",
            "-C",
            str(self.config.local_checkout_path),
            "pull",
            "--ff-only",
            "origin",
            self.config.branch,
        )

    def _authenticated_repo_url(self) -> str:
        if not self.config.github_token:
            return self.config.repo_url

        parts = urlsplit(self.config.repo_url)
        if parts.scheme != "https":
            return self.config.repo_url
        netloc = f"x-access-token:{self.config.github_token}@{parts.netloc}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    async def _run(self, *command: str) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                stderr.decode().strip() or stdout.decode().strip() or "Command failed."
            )
