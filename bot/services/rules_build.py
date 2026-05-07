from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from bot.models.rules import RulesChunk, RulesIndexMetadata
from bot.utils.config import RulesSyncConfig


class RulesBuildService:
    def __init__(self, config: RulesSyncConfig) -> None:
        self.config = config

    async def build_artifact(self, revision: str) -> Path:
        checkout_root = self.config.local_checkout_path
        artifact_path = self._resolve_checkout_path(self.config.artifact_path)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        if self.config.build_command:
            process = await asyncio.create_subprocess_shell(
                self.config.build_command,
                cwd=str(checkout_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(
                    stderr.decode().strip() or stdout.decode().strip() or "Build command failed."
                )
            if not artifact_path.exists():
                raise RuntimeError(f"Expected rules artifact was not produced: {artifact_path}")
            return artifact_path

        artifact_text = self._concat_source_files(checkout_root)
        artifact_path.write_text(artifact_text, encoding="utf-8")
        return artifact_path

    async def build_index(self, artifact_path: Path, revision: str) -> Path:
        raw_text = artifact_path.read_text(encoding="utf-8")
        chunks = self._chunk_text(raw_text)
        self.config.rules_index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": RulesIndexMetadata(
                artifact_path=str(artifact_path),
                revision=revision,
                built_at=datetime.now(UTC).isoformat(),
                chunk_count=len(chunks),
            ).__dict__,
            "chunks": [chunk.to_dict() for chunk in chunks],
        }
        self.config.rules_index_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        return self.config.rules_index_path

    def _concat_source_files(self, checkout_root: Path) -> str:
        parts: list[str] = []
        for include_path in self.config.include_paths:
            target = checkout_root / include_path
            if target.is_file():
                parts.append(f"# {include_path}\n\n{target.read_text(encoding='utf-8')}")
                continue

            if target.is_dir():
                for file_path in sorted(path for path in target.rglob("*") if path.is_file()):
                    if file_path.suffix.lower() not in {".md", ".txt"}:
                        continue
                    relative = file_path.relative_to(checkout_root)
                    parts.append(f"# {relative.as_posix()}\n\n{file_path.read_text(encoding='utf-8')}")
        if not parts:
            raise RuntimeError("No rules source files were found in the configured include paths.")
        return "\n\n".join(parts)

    def _chunk_text(self, raw_text: str) -> list[RulesChunk]:
        chunks: list[RulesChunk] = []
        current_heading = "Introduction"
        current_lines: list[str] = []
        chunk_index = 1

        def flush() -> None:
            nonlocal chunk_index
            content = "\n".join(current_lines).strip()
            if not content:
                return
            chunks.append(
                RulesChunk(
                    chunk_id=f"chunk-{chunk_index}",
                    heading=current_heading,
                    content=content,
                    source_ref=current_heading,
                )
            )
            chunk_index += 1

        for line in raw_text.splitlines():
            if line.startswith("#"):
                flush()
                current_heading = line.lstrip("#").strip() or "Untitled"
                current_lines = []
                continue
            current_lines.append(line)

        flush()
        if not chunks and raw_text.strip():
            chunks.append(
                RulesChunk(
                    chunk_id="chunk-1",
                    heading="Document",
                    content=raw_text.strip(),
                    source_ref="Document",
                )
            )
        return chunks

    def _resolve_checkout_path(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.local_checkout_path / path
