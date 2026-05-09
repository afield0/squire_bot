from __future__ import annotations

import json
import random
import re
from difflib import SequenceMatcher
from pathlib import Path

from bot.models.cards import CardSearchResult, NormalizedCard


class CardRepository:
    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path
        self._cards: list[NormalizedCard] | None = None
        self._raw_by_id: dict[str, NormalizedCard] = {}
        self._raw_by_name: dict[str, NormalizedCard] = {}
        self._by_id: dict[str, NormalizedCard] = {}
        self._by_name: dict[str, NormalizedCard] = {}

    def load(self, force: bool = False) -> list[NormalizedCard]:
        if self._cards is not None and not force:
            return self._cards
        if not self.artifact_path.exists():
            raise RuntimeError(f"No local cards artifact is available at {self.artifact_path}. Run `/rules sync` first.")

        payload = json.loads(self.artifact_path.read_text(encoding="utf-8"))
        raw_cards = payload.get("cards", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_cards, list):
            raise RuntimeError("Cards artifact must contain a JSON array or an object with a `cards` array.")

        cards = [NormalizedCard.from_dict(item) for item in raw_cards if isinstance(item, dict)]
        self._cards = cards
        self._raw_by_id = {card.id.lower(): card for card in cards}
        self._raw_by_name = {card.name.lower(): card for card in cards}
        self._by_id = {self._normalize(card.id): card for card in cards}
        self._by_name = {self._normalize(card.name): card for card in cards}
        return cards

    def exists(self) -> bool:
        return self.artifact_path.exists()

    def get_card_by_id(self, card_id: str) -> NormalizedCard | None:
        self.load()
        return self._by_id.get(self._normalize(card_id))

    def find_best_card_match(self, query: str) -> CardSearchResult | None:
        results = self.search_cards(query, limit=1)
        return results[0] if results else None

    def search_cards(self, query: str, limit: int = 10) -> list[CardSearchResult]:
        cards = self.load()
        raw_query = query.strip().lower()
        normalized_query = self._normalize(query)
        if not normalized_query:
            return []

        exact_id = self._raw_by_id.get(raw_query)
        if exact_id:
            return [CardSearchResult(card=exact_id, score=1.0, reason="exact id")]

        exact_name = self._raw_by_name.get(raw_query)
        if exact_name:
            return [CardSearchResult(card=exact_name, score=1.0, reason="exact name")]

        normalized_name = self._by_name.get(normalized_query)
        if normalized_name:
            return [CardSearchResult(card=normalized_name, score=0.98, reason="normalized name")]

        normalized_id = self._by_id.get(normalized_query)
        if normalized_id:
            return [CardSearchResult(card=normalized_id, score=0.98, reason="normalized id")]

        results: list[CardSearchResult] = []
        query_tokens = set(normalized_query.split())
        for card in cards:
            name_key = self._normalize(card.name)
            id_key = self._normalize(card.id)
            searchable = f"{name_key} {id_key} {card.card_type}"
            score = 0.0
            reason = "fuzzy name"
            if normalized_query in name_key:
                score = 0.92
                reason = "partial name"
            elif normalized_query in id_key:
                score = 0.88
                reason = "partial id"
            else:
                name_score = SequenceMatcher(None, normalized_query, name_key).ratio()
                id_score = SequenceMatcher(None, normalized_query, id_key).ratio() * 0.95
                token_score = self._token_score(query_tokens, set(searchable.split()))
                score = max(name_score, id_score, token_score)
            if score >= 0.35:
                results.append(CardSearchResult(card=card, score=score, reason=reason))

        return sorted(results, key=lambda result: (-result.score, result.card.name.lower()))[:limit]

    def list_cards_by_type(self, card_type: str) -> list[NormalizedCard]:
        normalized_type = self._normalize_type(card_type)
        return sorted(
            [card for card in self.load() if self._normalize_type(card.card_type) == normalized_type],
            key=lambda card: card.name.lower(),
        )

    def random_card(self, card_type: str | None = None) -> NormalizedCard | None:
        cards = self.list_cards_by_type(card_type) if card_type else self.load()
        if not cards:
            return None
        return random.choice(cards)

    def image_path_for(self, card: NormalizedCard) -> Path | None:
        raw_path = card.fields.get("image_path")
        if not raw_path:
            return None
        path = Path(str(raw_path))
        return path if path.exists() else None

    @staticmethod
    def _token_score(query_tokens: set[str], candidate_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        matches = query_tokens & candidate_tokens
        if not matches:
            return 0.0
        return 0.45 + (0.35 * (len(matches) / len(query_tokens)))

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    @classmethod
    def _normalize_type(cls, value: str) -> str:
        return cls._normalize(value).replace(" ", "_")
