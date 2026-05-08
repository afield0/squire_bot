from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class RulesChunk:
    chunk_id: str
    source_file: str
    heading: str
    content: str
    source_ref: str
    token_count: int

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResult:
    chunk: RulesChunk
    score: float


@dataclass(slots=True)
class RulesIndexMetadata:
    artifact_path: str
    revision: str
    built_at: str
    chunk_count: int


@dataclass(slots=True)
class RulesRepoStatus:
    repo_url: str
    branch: str
    local_path: str
    include_paths: list[str]
    repo_exists: bool
    is_git_repo: bool
    current_commit: str | None
    last_sync_at: str | None


@dataclass(slots=True)
class RuleCitation:
    source_file: str
    heading: str
    label: str


@dataclass(slots=True)
class LLMAnswer:
    answer: str
    citations: list[RuleCitation]
    grounded: bool
    status: str
    ambiguity_note: str | None = None
