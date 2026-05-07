from __future__ import annotations

import json
import re
from pathlib import Path

from bot.models.rules import RetrievalResult, RulesChunk, RulesIndexMetadata


class RulesRetrievalService:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        self.metadata: RulesIndexMetadata | None = None
        self.chunks: list[RulesChunk] = []

    async def load(self) -> None:
        if not self.index_path.exists():
            self.metadata = None
            self.chunks = []
            return

        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {})
        self.metadata = RulesIndexMetadata(
            artifact_path=metadata.get("artifact_path", ""),
            revision=metadata.get("revision", "unknown"),
            built_at=metadata.get("built_at", ""),
            chunk_count=int(metadata.get("chunk_count", 0)),
        )
        self.chunks = [
            RulesChunk(
                chunk_id=chunk["chunk_id"],
                heading=chunk["heading"],
                content=chunk["content"],
                source_ref=chunk["source_ref"],
            )
            for chunk in payload.get("chunks", [])
        ]

    def has_index(self) -> bool:
        return bool(self.chunks)

    def get_sources_summary(self) -> str:
        if not self.metadata:
            return "No rules index is currently loaded."
        return (
            f"Artifact: `{self.metadata.artifact_path}`\n"
            f"Revision: `{self.metadata.revision}`\n"
            f"Built: `{self.metadata.built_at}`\n"
            f"Chunks: `{self.metadata.chunk_count}`"
        )

    def answer_question(self, question: str, limit: int = 3) -> str:
        results = self.search(question, limit=limit)
        if not results:
            return (
                "I could not find a confident rules match in the local artifact.\n"
                "Try different keywords or sync/rebuild the rules index."
            )

        if results[0].score <= 0:
            return (
                "I am not confident in the answer from the current local rules artifact.\n"
                "Best available references:\n"
                f"{self._format_results(results)}"
            )

        # TODO: replace snippet-based response with vector retrieval + synthesis if needed later.
        return (
            "Best matching rules references:\n"
            f"{self._format_results(results)}"
        )

    def search(self, question: str, limit: int = 3) -> list[RetrievalResult]:
        query_terms = self._normalize(question)
        if not query_terms:
            return []

        results: list[RetrievalResult] = []
        for chunk in self.chunks:
            haystack_terms = self._normalize(f"{chunk.heading}\n{chunk.content}")
            overlap = len(query_terms.intersection(haystack_terms))
            if overlap <= 0:
                continue

            heading_bonus = sum(
                2 for term in query_terms if term in self._normalize(chunk.heading)
            )
            results.append(RetrievalResult(chunk=chunk, score=overlap + heading_bonus))

        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]

    def _format_results(self, results: list[RetrievalResult]) -> str:
        formatted: list[str] = []
        for result in results:
            snippet = self._snippet(result.chunk.content)
            formatted.append(
                f"- [{result.chunk.source_ref}] {snippet}"
            )
        return "\n".join(formatted)

    @staticmethod
    def _snippet(text: str, limit: int = 320) -> str:
        squashed = " ".join(text.split())
        return squashed if len(squashed) <= limit else f"{squashed[: limit - 3]}..."

    @staticmethod
    def _normalize(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 2
        }
