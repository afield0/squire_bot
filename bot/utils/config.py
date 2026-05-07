from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class RulesSyncConfig:
    repo_url: str
    branch: str
    local_checkout_path: Path
    include_paths: list[str]
    build_command: str | None
    artifact_path: Path
    rules_index_path: Path
    github_token: str | None


@dataclass(slots=True)
class PathConfig:
    project_root: Path


@dataclass(slots=True)
class DailyConfig:
    timezone_name: str
    topic_channel_id: int | None
    design_prompt_channel_id: int | None
    post_hour: int
    post_minute: int
    enable_design_prompt: bool


@dataclass(slots=True)
class AppConfig:
    discord_bot_token: str
    discord_application_id: int
    discord_guild_id: int | None
    log_level: str
    sqlite_path: Path
    paths: PathConfig
    rules_sync: RulesSyncConfig
    daily: DailyConfig


def _get_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value else None


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_path(value: str, base_path: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or base_path is None:
        return path
    return (base_path / path).resolve()


def _load_rules_sync_config() -> RulesSyncConfig:
    project_root = Path(__file__).resolve().parents[2]
    return RulesSyncConfig(
        repo_url=os.getenv("GITHUB_RULES_REPO_URL", "").strip(),
        branch=os.getenv("GITHUB_RULES_BRANCH", "master").strip(),
        local_checkout_path=_resolve_path(
            os.getenv("GITHUB_RULES_LOCAL_PATH", "data/rules_repo"),
            base_path=project_root,
        ),
        include_paths=[
            path.strip()
            for path in os.getenv("GITHUB_RULES_INCLUDE_PATHS", "tools/rulebook/src").split(",")
            if path.strip()
        ],
        build_command=os.getenv("GITHUB_RULES_BUILD_COMMAND", "python -m bot.services.build_rules_artifact")
        or None,
        artifact_path=_resolve_path(
            os.getenv("GITHUB_RULES_ARTIFACT_PATH", "data/rules_repo/.bot_cache/manual.md"),
            base_path=project_root,
        ),
        rules_index_path=_resolve_path(
            os.getenv("RULES_INDEX_PATH", "data/rules_index.json"),
            base_path=project_root,
        ),
        github_token=os.getenv("GITHUB_TOKEN") or None,
    )


def load_rules_sync_config() -> RulesSyncConfig:
    load_dotenv()
    return _load_rules_sync_config()


def load_config() -> AppConfig:
    load_dotenv()

    project_root = Path(__file__).resolve().parents[2]
    rules_sync = _load_rules_sync_config()

    daily = DailyConfig(
        timezone_name=os.getenv("DAILY_TIMEZONE", "America/New_York"),
        topic_channel_id=_get_optional_int("TOPIC_OF_DAY_CHANNEL_ID"),
        design_prompt_channel_id=_get_optional_int("DESIGN_PROMPT_CHANNEL_ID"),
        post_hour=int(os.getenv("DAILY_POST_HOUR", "9")),
        post_minute=int(os.getenv("DAILY_POST_MINUTE", "0")),
        enable_design_prompt=_get_bool("ENABLE_DESIGN_PROMPT", default=False),
    )

    return AppConfig(
        discord_bot_token=_get_required("DISCORD_BOT_TOKEN"),
        discord_application_id=int(_get_required("DISCORD_APPLICATION_ID")),
        discord_guild_id=_get_optional_int("DISCORD_GUILD_ID"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        sqlite_path=_resolve_path(os.getenv("SQLITE_PATH", "data/bot.db"), base_path=project_root),
        paths=PathConfig(project_root=project_root),
        rules_sync=rules_sync,
        daily=daily,
    )
