from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bot.models.cards import CardSearchResult, NormalizedCard
from bot.services.cards import CardRepository
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
    def __init__(
        self,
        rulebook_artifact_path: Path,
        cards_artifact_path: Path | None = None,
        max_excerpts: int = 3,
    ) -> None:
        if isinstance(cards_artifact_path, int):
            max_excerpts = cards_artifact_path
            cards_artifact_path = None
        self.rulebook_artifact_path = rulebook_artifact_path
        self.card_repository = CardRepository(cards_artifact_path or rulebook_artifact_path.with_name("cards.json"))
        self.max_excerpts = max(1, max_excerpts)

    def available_source_types(self) -> set[str]:
        available: set[str] = set()
        if self.rulebook_artifact_path.exists():
            available.add("rulebook")
            available.add("mixed")
        if self.card_repository.exists():
            available.add("cards")
            available.add("mixed")
        # TODO: Add lore source availability when lore has a stable local artifact.
        return available

    async def gather(self, seed: TopicSeed) -> SourcePacket:
        excerpts: list[SourceExcerpt] = []
        if seed.source_type in {"cards", "mixed"}:
            excerpts.extend(self._gather_cards(seed).excerpts)
        if len(excerpts) < self.max_excerpts and seed.source_type in {"rulebook", "mixed"}:
            excerpts.extend(self._gather_rulebook(seed).excerpts)
        return SourcePacket(excerpts=excerpts[: self.max_excerpts])

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

    def _gather_cards(self, seed: TopicSeed) -> SourcePacket:
        if not self.card_repository.exists():
            return SourcePacket(excerpts=[])

        try:
            cards = self.card_repository.load()
        except Exception:
            return SourcePacket(excerpts=[])

        results: list[CardSearchResult] = []
        for hint in seed.source_hints:
            results.extend(self.card_repository.search_cards(hint, limit=self.max_excerpts))

        if not results:
            results = self._search_cards_by_seed_text(cards, seed)

        selected: list[NormalizedCard] = []
        seen_ids: set[str] = set()
        for result in sorted(results, key=lambda item: (-item.score, item.card.name.lower())):
            if result.card.id in seen_ids:
                continue
            selected.append(result.card)
            seen_ids.add(result.card.id)
            if len(selected) >= self.max_excerpts:
                break

        if not selected and cards:
            preferred_type = self._infer_card_type(seed)
            typed_cards = [card for card in cards if card.card_type == preferred_type] if preferred_type else []
            selected.append((typed_cards or cards)[0])

        return SourcePacket(
            excerpts=[
                SourceExcerpt(label=f"Card: {card.name}", text=card.render_excerpt())
                for card in selected[: self.max_excerpts]
            ]
        )

    def _search_cards_by_seed_text(self, cards: list[NormalizedCard], seed: TopicSeed) -> list[CardSearchResult]:
        query = " ".join([seed.category, seed.intent, *seed.source_hints]).lower()
        results: list[CardSearchResult] = []
        preferred_type = self._infer_card_type(seed)
        for card in cards:
            score = 0.0
            haystack = f"{card.name} {card.id} {card.card_type} {card.render_excerpt()}".lower()
            if preferred_type and card.card_type == preferred_type:
                score += 0.3
            for token in re.findall(r"[a-z0-9]+", query):
                if len(token) >= 4 and token in haystack:
                    score += 0.1
            if score > 0:
                results.append(CardSearchResult(card=card, score=score, reason="seed text"))
        return results

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
    def _infer_card_type(seed: TopicSeed) -> str | None:
        text = f"{seed.category} {seed.intent} {' '.join(seed.source_hints)}".lower()
        type_aliases = {
            "attacker": "attacker",
            "defender": "defender",
            "battle": "battle",
            "location": "location",
            "castle": "castle_improvement",
            "improvement": "castle_improvement",
            "objective": "objective",
        }
        for token, card_type in type_aliases.items():
            if token in text:
                return card_type
        return None

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
