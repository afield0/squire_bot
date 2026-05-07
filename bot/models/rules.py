from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class RulesChunk:
    chunk_id: str
    heading: str
    content: str
    source_ref: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResult:
    chunk: RulesChunk
    score: int


@dataclass(slots=True)
class RulesIndexMetadata:
    artifact_path: str
    revision: str
    built_at: str
    chunk_count: int
