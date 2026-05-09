from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bot.services.topic_seeds import TopicSeed


@dataclass(frozen=True, slots=True)
class SourceExcerpt:
    label: str
    text: str


@dataclass(frozen=True, slots=True)
class SourcePacket:
    excerpts: list[SourceExcerpt]

    @property
    def labels(self) -> list[str]:
        return [excerpt.label for excerpt in self.excerpts]

    @property
    def has_sources(self) -> bool:
        return bool(self.excerpts)


@dataclass(frozen=True, slots=True)
class RulebookSection:
    source_file: str
    heading: str
    text: str

    @property
    def label(self) -> str:
        if self.heading and self.heading != self.source_file:
            return f"{self.source_file} -> {self.heading}"
        return self.source_file


class DailySourceGatherer:
    def __init__(self, rulebook_artifact_path: Path, max_excerpts: int = 3) -> None:
        self.rulebook_artifact_path = rulebook_artifact_path
        self.max_excerpts = max(1, max_excerpts)

    def available_source_types(self) -> set[str]:
        available: set[str] = set()
        if self.rulebook_artifact_path.exists():
            available.add("rulebook")
            available.add("mixed")
        # TODO: Add card source availability when card data has a stable local artifact.
        # TODO: Add lore source availability when lore has a stable local artifact.
        return available

    async def gather(self, seed: TopicSeed) -> SourcePacket:
        if seed.source_type not in {"rulebook", "mixed"}:
            # TODO: Gather card and lore sources once those artifacts exist locally.
            return SourcePacket(excerpts=[])
        return self._gather_rulebook(seed)

    def _gather_rulebook(self, seed: TopicSeed) -> SourcePacket:
        if not self.rulebook_artifact_path.exists():
            return SourcePacket(excerpts=[])

        artifact_text = self.rulebook_artifact_path.read_text(encoding="utf-8")
        sections = self._parse_rulebook_sections(artifact_text)
        scored = sorted(
            (
                (self._score_section(section, seed), section)
                for section in sections
                if section.text.strip()
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        excerpts: list[SourceExcerpt] = []
        seen_labels: set[str] = set()
        for score, section in scored:
            if score <= 0 or section.label in seen_labels:
                continue
            excerpts.append(SourceExcerpt(label=section.label, text=self._clean_excerpt(section.text)))
            seen_labels.add(section.label)
            if len(excerpts) >= self.max_excerpts:
                break

        if not excerpts and sections:
            overview = next((section for section in sections if section.heading.lower() == "overview"), sections[0])
            excerpts.append(SourceExcerpt(label=overview.label, text=self._clean_excerpt(overview.text)))

        return SourcePacket(excerpts=excerpts)

    @staticmethod
    def _parse_rulebook_sections(text: str) -> list[RulebookSection]:
        sections: list[RulebookSection] = []
        source_file = "rulebook"
        heading = "rulebook"
        buffer: list[str] = []

        def flush() -> None:
            content = "\n".join(buffer).strip()
            if content:
                sections.append(RulebookSection(source_file=source_file, heading=heading, text=content))

        for raw_line in text.splitlines():
            file_match = re.match(r"^# File:\s+(.+?)\s*$", raw_line)
            heading_match = re.match(r"^(#{1,3})\s+(.+?)\s*$", raw_line)
            if file_match:
                flush()
                source_file = file_match.group(1).strip()
                heading = source_file
                buffer = []
                continue
            if heading_match and not raw_line.startswith("# File:"):
                flush()
                heading = heading_match.group(2).strip()
                buffer = []
                continue
            if raw_line.strip().startswith("<!-- source:"):
                continue
            buffer.append(raw_line)
        flush()
        return sections

    @staticmethod
    def _score_section(section: RulebookSection, seed: TopicSeed) -> int:
        haystack = f"{section.source_file}\n{section.heading}\n{section.text}".lower()
        score = 0
        for hint in seed.source_hints:
            needle = hint.lower()
            if needle in haystack:
                score += 5 if needle in section.heading.lower() else 3
            for token in re.findall(r"[a-z0-9]+", needle):
                if len(token) >= 4 and token in haystack:
                    score += 1
        for token in re.findall(r"[a-z0-9]+", f"{seed.category} {seed.intent}".lower()):
            if len(token) >= 5 and token in haystack:
                score += 1
        return score

    @staticmethod
    def _clean_excerpt(text: str, limit: int = 700) -> str:
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
            and not line.strip().startswith("\\begin")
            and not line.strip().startswith("\\end")
            and not line.strip().startswith("\\includegraphics")
            and not line.strip().startswith("\\clearpage")
            and not line.strip().startswith("\\hspace")
        ]
        excerpt = "\n".join(lines)
        excerpt = re.sub(r"\\shadowimage\[[^\]]+\]\{[^}]+\}", "", excerpt)
        excerpt = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", excerpt)
        excerpt = re.sub(r"\\[a-zA-Z]+", "", excerpt)
        excerpt = re.sub(r"\\\\\[[^\]]+\]", "", excerpt)
        excerpt = re.sub(r"\n{3,}", "\n\n", excerpt)
        excerpt = re.sub(r"[ \t]{2,}", " ", excerpt).strip()
        if len(excerpt) <= limit:
            return excerpt
        return excerpt[:limit].rsplit(" ", 1)[0].rstrip() + "..."
