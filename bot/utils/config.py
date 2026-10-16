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
    cards_artifact_path: Path
    rules_index_path: Path
    github_token: str | None


@dataclass(slots=True)
class OpenAIConfig:
    api_key: str | None
    model: str
    temperature: float | None
    timeout_seconds: float
    rules_use_llm: bool


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
    use_llm: bool
    max_source_excerpts: int
    topic_mode: str
    weekly_mode: bool
    topic_seeds_path: Path


@dataclass(slots=True)
class RulebookPublishConfig:
    channel_id: int | None
    pdf_path: Path
    auto_publish: bool
    delete_previous: bool


@dataclass(slots=True)
class WelcomeConfig:
    enabled: bool
    channel_id: int | None
    dm_enabled: bool


@dataclass(slots=True)
class AppConfig:
    discord_bot_token: str
    discord_application_id: int
    discord_guild_id: int | None
    log_level: str
    sqlite_path: Path
    paths: PathConfig
    rules_sync: RulesSyncConfig
    openai: OpenAIConfig
    daily: DailyConfig
    rulebook: RulebookPublishConfig
    welcome: WelcomeConfig


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


def _get_optional_float(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name)
    return float(value) if value and value.strip() else default


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
            for path in os.getenv(
                "GITHUB_RULES_INCLUDE_PATHS",
                "tools/rulebook/src,vampire_defenders/cards,vampire_defenders/common,assets/cards/rendered",
            ).split(",")
            if path.strip()
        ],
        build_command=os.getenv("GITHUB_RULES_BUILD_COMMAND", "python -m bot.services.build_rules_artifact")
        or None,
        artifact_path=_resolve_path(
            os.getenv("GITHUB_RULES_ARTIFACT_PATH", "data/rules_repo/.bot_cache/manual.md"),
            base_path=project_root,
        ),
        cards_artifact_path=_resolve_path(
            os.getenv("CARDS_ARTIFACT_PATH", "data/rules_repo/.bot_cache/cards.json"),
            base_path=project_root,
        ),
        rules_index_path=_resolve_path(
            os.getenv("RULES_INDEX_PATH", "data/rules_index.json"),
            base_path=project_root,
        ),
        github_token=os.getenv("GITHUB_TOKEN") or None,
    )


def _load_openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        api_key=os.getenv("OPENAI_API_KEY") or None,
        model=os.getenv("OPENAI_MODEL", "gpt-5").strip() or "gpt-5",
        temperature=_get_optional_float("OPENAI_TEMPERATURE"),
        timeout_seconds=_get_optional_float("RULES_LLM_TIMEOUT_SECONDS", 30.0),
        rules_use_llm=_get_bool("RULES_USE_LLM", default=False),
    )


def _with_rulebook_pdf_include(
    rules_sync: RulesSyncConfig,
    rulebook: RulebookPublishConfig,
) -> RulesSyncConfig:
    try:
        relative_pdf_path = rulebook.pdf_path.relative_to(rules_sync.local_checkout_path)
    except ValueError:
        return rules_sync

    include_paths = [
        relative_pdf_path.as_posix(),
        rulebook.pdf_path.with_name(f"{rulebook.pdf_path.stem}.metadata.json")
        .relative_to(rules_sync.local_checkout_path)
        .as_posix(),
    ]
    missing_include_paths = [
        include_path
        for include_path in include_paths
        if not any(_sparse_path_covers(existing, include_path) for existing in rules_sync.include_paths)
    ]
    if not missing_include_paths:
        return rules_sync

    return RulesSyncConfig(
        repo_url=rules_sync.repo_url,
        branch=rules_sync.branch,
        local_checkout_path=rules_sync.local_checkout_path,
        include_paths=[*rules_sync.include_paths, *missing_include_paths],
        build_command=rules_sync.build_command,
        artifact_path=rules_sync.artifact_path,
        cards_artifact_path=rules_sync.cards_artifact_path,
        rules_index_path=rules_sync.rules_index_path,
        github_token=rules_sync.github_token,
    )


def _sparse_path_covers(existing: str, target: str) -> bool:
    normalized = existing.strip().strip("/")
    if normalized == target:
        return True
    return target.startswith(f"{normalized}/")


def load_rules_sync_config() -> RulesSyncConfig:
    load_dotenv()
    return _load_rules_sync_config()


def load_config() -> AppConfig:
    load_dotenv()

    project_root = Path(__file__).resolve().parents[2]
    rules_sync = _load_rules_sync_config()
    openai = _load_openai_config()

    daily = DailyConfig(
        timezone_name=os.getenv("DAILY_TIMEZONE", "America/New_York"),
        topic_channel_id=_get_optional_int("TOPIC_OF_DAY_CHANNEL_ID"),
        design_prompt_channel_id=_get_optional_int("DESIGN_PROMPT_CHANNEL_ID"),
        post_hour=int(os.getenv("DAILY_POST_HOUR", "9")),
        post_minute=int(os.getenv("DAILY_POST_MINUTE", "0")),
        enable_design_prompt=_get_bool("ENABLE_DESIGN_PROMPT", default=False),
        use_llm=_get_bool("DAILY_USE_LLM", default=False),
        max_source_excerpts=int(os.getenv("DAILY_MAX_SOURCE_EXCERPTS", "3")),
        topic_mode=os.getenv("DAILY_TOPIC_MODE", "daily").strip() or "daily",
        weekly_mode=_get_bool("DAILY_WEEKLY_MODE", default=False),
        topic_seeds_path=_resolve_path(
            os.getenv("DAILY_TOPIC_SEEDS_PATH", "data/topic_seeds.json"),
            base_path=project_root,
        ),
    )

    rulebook = RulebookPublishConfig(
        channel_id=_get_optional_int("RULEBOOK_CHANNEL_ID"),
        pdf_path=_resolve_path(
            os.getenv(
                "RULEBOOK_PDF_PATH",
                "data/rules_repo/releases/rulebook/Vampire_Defenders_Rulebook_compressed.pdf",
            ),
            base_path=project_root,
        ),
        auto_publish=_get_bool("RULEBOOK_AUTO_PUBLISH", default=True),
        delete_previous=_get_bool("RULEBOOK_DELETE_PREVIOUS", default=True),
    )
    rules_sync = _with_rulebook_pdf_include(rules_sync, rulebook)
    welcome = WelcomeConfig(
        enabled=_get_bool("WELCOME_ENABLED", default=False),
        channel_id=_get_optional_int("WELCOME_CHANNEL_ID"),
        dm_enabled=_get_bool("WELCOME_DM_ENABLED", default=True),
    )

    return AppConfig(
        discord_bot_token=_get_required("DISCORD_BOT_TOKEN"),
        discord_application_id=int(_get_required("DISCORD_APPLICATION_ID")),
        discord_guild_id=_get_optional_int("DISCORD_GUILD_ID"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        sqlite_path=_resolve_path(os.getenv("SQLITE_PATH", "data/bot.db"), base_path=project_root),
        paths=PathConfig(project_root=project_root),
        rules_sync=rules_sync,
        openai=openai,
        daily=daily,
        rulebook=rulebook,
        welcome=welcome,
    )
