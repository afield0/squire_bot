from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
from dataclasses import dataclass

from bot.models.rules import RulesRepoStatus
from bot.utils.config import RulesSyncConfig

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CompletedCommand:
    stdout: str
    stderr: str


class GitHubRulesSyncService:
    def __init__(self, config: RulesSyncConfig) -> None:
        self.config = config

    async def ensure_repo_synced(self) -> str:
        self._validate_sync_prerequisites()
        self.config.local_checkout_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.config.local_checkout_path.exists():
            await self._clone_sparse()
        else:
            if not await self._is_git_repo():
                raise RuntimeError(
                    f"Local rules path exists but is not a git repository: {self.config.local_checkout_path}"
                )
            await self._run_git("remote", "set-url", "origin", self.config.repo_url)
            await self._update_sparse_settings()
            await self._run_git("fetch", "origin", self.config.branch)
            await self._run_git("checkout", self.config.branch)
            await self._run_git("pull", "--ff-only", "origin", self.config.branch)

        await self._ensure_include_paths_exist()
        commit = await self.get_current_commit()
        LOGGER.info("Rules repo synced at commit %s", commit)
        return commit

    async def get_current_commit(self) -> str:
        self._ensure_checkout_exists()
        result = await self._run_git("rev-parse", "HEAD")
        return result.stdout.strip()

    async def get_repo_status(self, last_sync_at: str | None = None) -> RulesRepoStatus:
        repo_exists = self.config.local_checkout_path.exists()
        is_git_repo = await self._is_git_repo() if repo_exists else False
        current_commit: str | None = None
        if is_git_repo:
            try:
                current_commit = await self.get_current_commit()
            except RuntimeError:
                current_commit = None

        return RulesRepoStatus(
            repo_url=self.config.repo_url,
            branch=self.config.branch,
            local_path=str(self.config.local_checkout_path),
            include_paths=self.config.include_paths,
            repo_exists=repo_exists,
            is_git_repo=is_git_repo,
            current_commit=current_commit,
            last_sync_at=last_sync_at,
        )

    async def _clone_sparse(self) -> None:
        LOGGER.info("Cloning rules repository into %s", self.config.local_checkout_path)
        await self._run_command(
            "git",
            "clone",
            "--filter=blob:none",
            "--sparse",
            "--branch",
            self.config.branch,
            self.config.repo_url,
            str(self.config.local_checkout_path),
        )
        await self._update_sparse_settings()

    async def _update_sparse_settings(self) -> None:
        await self._run_git("sparse-checkout", "set", "--no-cone", *self.config.include_paths)

    async def _ensure_include_paths_exist(self) -> None:
        missing_paths = [
            include_path
            for include_path in self.config.include_paths
            if not (self.config.local_checkout_path / include_path).exists()
        ]
        if missing_paths:
            joined = ", ".join(missing_paths)
            raise RuntimeError(f"Configured rules paths were not found after sync: {joined}")

    async def _is_git_repo(self) -> bool:
        if not self.config.local_checkout_path.exists():
            return False
        try:
            result = await self._run_command(
                "git",
                "-C",
                str(self.config.local_checkout_path),
                "rev-parse",
                "--is-inside-work-tree",
                check=False,
            )
        except RuntimeError:
            return False
        return result.stdout.strip() == "true"

    def _validate_sync_prerequisites(self) -> None:
        if shutil.which("git") is None:
            raise RuntimeError("Git is not installed or not available on PATH.")
        if not self.config.github_token:
            raise RuntimeError("GITHUB_TOKEN is required to sync the private rules repository.")
        if not self.config.repo_url:
            raise RuntimeError("GITHUB_RULES_REPO_URL is not configured.")
        if not self.config.include_paths:
            raise RuntimeError("GITHUB_RULES_INCLUDE_PATHS must include at least one path.")

    def _ensure_checkout_exists(self) -> None:
        if not self.config.local_checkout_path.exists():
            raise RuntimeError(
                f"Local rules repository does not exist yet: {self.config.local_checkout_path}"
            )

    async def _run_git(self, *args: str) -> CompletedCommand:
        self._ensure_checkout_exists()
        return await self._run_command(
            "git",
            "-C",
            str(self.config.local_checkout_path),
            *args,
        )

    async def _run_command(self, *command: str, check: bool = True) -> CompletedCommand:
        process = await asyncio.create_subprocess_exec(
            *command,
            env=self._command_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        completed = CompletedCommand(
            stdout=self._sanitize(stdout.decode().strip()),
            stderr=self._sanitize(stderr.decode().strip()),
        )
        if check and process.returncode != 0:
            message = completed.stderr or completed.stdout or "Command failed."
            raise RuntimeError(message)
        return completed

    def _sanitize(self, text: str) -> str:
        if not text:
            return text
        sanitized = text
        if self.config.github_token:
            sanitized = sanitized.replace(self.config.github_token, "[REDACTED]")
            sanitized = sanitized.replace(self._auth_header_value(), "AUTHORIZATION: basic [REDACTED]")
        return sanitized

    def _command_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.config.github_token:
            env["GIT_HTTP_EXTRA_HEADER"] = self._auth_header_value()
        return env

    def _auth_header_value(self) -> str:
        token_bytes = f"x-access-token:{self.config.github_token}".encode("utf-8")
        encoded = base64.b64encode(token_bytes).decode("ascii")
        return f"AUTHORIZATION: basic {encoded}"
