from __future__ import annotations

from dataclasses import asdict
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from bot.models.rules import RulesChunk, RulesIndexMetadata
from bot.utils.config import RulesSyncConfig


class RulesIndexService:
    def __init__(self, config: RulesSyncConfig) -> None:
        self.config = config

    def build_index(self, revision: str) -> Path:
        artifact_path = self._resolve_artifact_path()
        if not artifact_path.exists():
            raise RuntimeError(f"Rules artifact does not exist: {artifact_path}")

        raw_text = artifact_path.read_text(encoding="utf-8")
        chunks = self._chunk_markdown(raw_text)
        self.config.rules_index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": asdict(
                RulesIndexMetadata(
                    artifact_path=str(artifact_path),
                    revision=revision,
                    built_at=datetime.now(UTC).isoformat(),
                    chunk_count=len(chunks),
                )
            ),
            "chunks": [chunk.to_dict() for chunk in chunks],
        }
        self.config.rules_index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self.config.rules_index_path

    def _chunk_markdown(self, raw_text: str) -> list[RulesChunk]:
        file_sections = [section.strip() for section in raw_text.split("\n\n---\n\n") if section.strip()]
        chunks: list[RulesChunk] = []
        chunk_index = 1

        for file_section in file_sections:
            source_file, content_lines = self._parse_file_section(file_section)
            heading = source_file
            buffer: list[str] = []

            def flush() -> None:
                nonlocal chunk_index, buffer
                content = "\n".join(buffer).strip()
                if not content:
                    buffer = []
                    return
                for piece in self._split_oversized_chunk(content):
                    token_count = len(self._tokenize(f"{heading}\n{piece}\n{source_file}"))
                    source_ref = f"{source_file} -> {heading}" if heading != source_file else source_file
                    chunks.append(
                        RulesChunk(
                            chunk_id=f"chunk-{chunk_index}",
                            source_file=source_file,
                            heading=heading,
                            content=piece,
                            source_ref=source_ref,
                            token_count=token_count,
                        )
                    )
                    chunk_index += 1
                buffer = []

            for line in content_lines:
                if line.startswith("#"):
                    flush()
                    heading = line.lstrip("#").strip() or source_file
                    continue
                buffer.append(line)

            flush()

        if not chunks and raw_text.strip():
            token_count = len(self._tokenize(raw_text))
            chunks.append(
                RulesChunk(
                    chunk_id="chunk-1",
                    source_file="manual.md",
                    heading="Document",
                    content=raw_text.strip(),
                    source_ref="manual.md -> Document",
                    token_count=token_count,
                )
            )
        return chunks

    def _parse_file_section(self, file_section: str) -> tuple[str, list[str]]:
        lines = file_section.splitlines()
        source_file = "unknown.md"
        content_lines: list[str] = []

        for line in lines:
            if line.startswith("# File: "):
                source_file = line.removeprefix("# File: ").strip()
                continue
            if line.startswith("<!-- source:"):
                continue
            content_lines.append(line)
        return source_file, content_lines

    def _split_oversized_chunk(self, content: str, max_chars: int = 1800) -> list[str]:
        if len(content) <= max_chars:
            return [content]

        paragraphs = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
        if not paragraphs:
            return [content[i : i + max_chars] for i in range(0, len(content), max_chars)]

        pieces: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                pieces.append(current)
            if len(paragraph) <= max_chars:
                current = paragraph
            else:
                pieces.extend(
                    paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)
                )
                current = ""
        if current:
            pieces.append(current)
        return pieces

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _resolve_artifact_path(self) -> Path:
        return self.config.artifact_path
