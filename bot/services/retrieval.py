from __future__ import annotations

import json
import math
import re
from collections import Counter
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
                source_file=chunk["source_file"],
                heading=chunk["heading"],
                content=chunk["content"],
                source_ref=chunk["source_ref"],
                token_count=int(chunk.get("token_count", 0)),
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

    def search(self, question: str, limit: int = 3) -> list[RetrievalResult]:
        # TODO: swap this scorer for embeddings/vector retrieval without changing the cog API.
        query_counter = Counter(self._normalize(question))
        if not query_counter:
            return []

        results: list[RetrievalResult] = []
        for chunk in self.chunks:
            chunk_counter = Counter(
                self._normalize(f"{chunk.source_file}\n{chunk.heading}\n{chunk.content}")
            )
            overlap = sum(min(query_counter[token], chunk_counter[token]) for token in query_counter)
            if overlap <= 0:
                continue

            heading_tokens = set(self._normalize(chunk.heading))
            file_tokens = set(self._normalize(chunk.source_file))
            heading_bonus = sum(1.5 for token in query_counter if token in heading_tokens)
            file_bonus = sum(1.0 for token in query_counter if token in file_tokens)
            length_penalty = math.log(max(chunk.token_count, 1) + 1, 4)
            score = overlap + heading_bonus + file_bonus - (0.15 * length_penalty)
            results.append(RetrievalResult(chunk=chunk, score=score))

        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]

    def answer_question(self, question: str, limit: int = 3) -> str:
        results = self.search(question, limit=limit)
        if not results:
            return (
                "I could not find a clear match in the indexed rules.\n"
                "Run `/rules sync` after updating the rules repo, or try different terms."
            )

        best = results[0]
        if best.score < 1.5:
            return (
                "I did not find a confident answer in the indexed rules.\n"
                f"Best reference: [{best.chunk.source_ref}] {self._snippet(best.chunk.content)}"
            )

        # TODO: add optional LLM synthesis above retrieved snippets once a clean interface is chosen.
        secondary_results = results[1:]
        references = "\n".join(
            f"- [{result.chunk.source_ref}] {self._snippet(result.chunk.content)}"
            for result in secondary_results
        )
        if not references:
            return f"Best match: [{best.chunk.source_ref}] {self._snippet(best.chunk.content)}"
        return f"Best match: [{best.chunk.source_ref}] {self._snippet(best.chunk.content)}\nOther relevant references:\n{references}"

    @staticmethod
    def _normalize(text: str) -> list[str]:
        return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1]

    @staticmethod
    def _snippet(text: str, limit: int = 320) -> str:
        squashed = " ".join(text.split())
        return squashed if len(squashed) <= limit else f"{squashed[: limit - 3]}..."
