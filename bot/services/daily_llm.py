from __future__ import annotations

import json
import logging
import time

from bot.models.daily import DailyPost
from bot.services.daily_sources import SourcePacket
from bot.services.openai_client import OpenAIRulesClient
from bot.services.topic_seeds import TopicSeed
from bot.utils.config import OpenAIConfig

LOGGER = logging.getLogger(__name__)

DAILY_MAX_OUTPUT_TOKENS = 800

DAILY_POST_SCHEMA = {
    "type": "json_schema",
    "name": "daily_post",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "body", "source_labels"],
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "source_labels": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
    "strict": True,
}

DAILY_SYSTEM_INSTRUCTION = """
You write short Discord posts for a board game community.
Use only the supplied source excerpts.
Do not invent rules, lore, card effects, quantities, names, or strategy claims.
If the sources are thin, write a modest discussion prompt grounded in exactly what is supplied.
Return only structured JSON with title, body, and source_labels.
Keep the body under about 120 words.
""".strip()


class DailyLLMComposer:
    _extract_payload = OpenAIRulesClient._extract_payload
    _extract_from_parsed_content = OpenAIRulesClient._extract_from_parsed_content
    _extract_from_content_text = OpenAIRulesClient._extract_from_content_text
    _has_value = staticmethod(OpenAIRulesClient._has_value)
    _get_value = staticmethod(OpenAIRulesClient._get_value)
    _extract_incomplete_reason = classmethod(OpenAIRulesClient._extract_incomplete_reason.__func__)
    _usage_summary = classmethod(OpenAIRulesClient._usage_summary.__func__)
    _coerce_structured_payload = staticmethod(OpenAIRulesClient._coerce_structured_payload)
    _parse_json_text = staticmethod(OpenAIRulesClient._parse_json_text)
    _to_plain_data = staticmethod(OpenAIRulesClient._to_plain_data)
    _safe_response_dump = staticmethod(OpenAIRulesClient._safe_response_dump)

    def __init__(self, config: OpenAIConfig, enabled: bool) -> None:
        self.config = config
        self.enabled = enabled
        self._client = None
        self._client_error: str | None = None

        if not self.enabled:
            LOGGER.info("Daily LLM mode is disabled")
            return
        if not self.config.api_key:
            self._client_error = "OPENAI_API_KEY is not configured."
            LOGGER.warning("Daily LLM mode is enabled but OPENAI_API_KEY is missing")
            return

        try:
            from openai import OpenAI
        except ImportError:
            self._client_error = "The `openai` package is not installed."
            LOGGER.warning("Daily LLM mode is enabled but the openai package is not installed")
            return

        self._client = OpenAI(api_key=self.config.api_key, timeout=self.config.timeout_seconds)

    def available(self) -> bool:
        return self.enabled and self._client is not None

    def availability_error(self) -> str | None:
        return self._client_error

    def compose(self, seed: TopicSeed, sources: SourcePacket) -> DailyPost:
        if not self.enabled:
            raise RuntimeError("Daily LLM mode is disabled.")
        if self._client is None:
            raise RuntimeError(self._client_error or "OpenAI client is unavailable.")

        started = time.perf_counter()
        try:
            request_kwargs = {
                "model": self.config.model,
                "instructions": DAILY_SYSTEM_INSTRUCTION,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": self._build_user_message(seed, sources),
                            }
                        ],
                    }
                ],
                "tool_choice": "none",
                "max_output_tokens": DAILY_MAX_OUTPUT_TOKENS,
                "store": False,
                "text": {
                    "format": DAILY_POST_SCHEMA,
                    "verbosity": "low",
                },
            }
            if self.config.model == "gpt-5" or self.config.model.startswith("gpt-5-"):
                request_kwargs["reasoning"] = {"effort": "minimal"}
            response = self._client.responses.create(**request_kwargs)
        except Exception:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            LOGGER.exception("OpenAI daily call failed model=%s latency_ms=%s", self.config.model, latency_ms)
            raise

        payload, payload_source = OpenAIRulesClient._extract_payload(self, response)
        LOGGER.info("OpenAI daily structured response parsed from %s", payload_source)
        title = str(payload.get("title", "")).strip() or "Vampire Defenders Topic of the Day"
        body = str(payload.get("body", "")).strip()
        source_labels = [
            str(label).strip()
            for label in payload.get("source_labels", [])
            if str(label).strip() in set(sources.labels)
        ]
        if not body:
            raise RuntimeError("OpenAI daily response did not include a body.")
        return DailyPost(
            title=title,
            body=body,
            category=seed.category,
            source_labels=source_labels or sources.labels,
            seed_id=seed.id,
        )

    def fallback_post(self, seed: TopicSeed, sources: SourcePacket) -> DailyPost:
        if sources.excerpts:
            first = sources.excerpts[0]
            body = "\n".join(
                [
                    f"{seed.intent}",
                    "",
                    self._excerpt_to_prompt(first.text),
                ]
            )
        else:
            body = seed.intent
        return DailyPost(
            title="Vampire Defenders Topic of the Day",
            body=body,
            category=seed.category,
            source_labels=sources.labels,
            seed_id=seed.id,
        )

    @staticmethod
    def _build_user_message(seed: TopicSeed, sources: SourcePacket) -> str:
        source_blocks = []
        for index, excerpt in enumerate(sources.excerpts, start=1):
            source_blocks.append(
                "\n".join(
                    [
                        f"[source {index}] {excerpt.label}",
                        excerpt.text,
                    ]
                )
            )
        return "\n\n".join(
            [
                f"Seed id: {seed.id}",
                f"Category: {seed.category}",
                f"Intent: {seed.intent}",
                "Source excerpts:",
                "\n\n".join(source_blocks) if source_blocks else "(none)",
                f"Allowed source labels: {json.dumps(sources.labels)}",
            ]
        )

    @staticmethod
    def _excerpt_to_prompt(excerpt: str) -> str:
        compact = " ".join(line.strip("- ") for line in excerpt.splitlines() if line.strip())
        if len(compact) > 220:
            compact = compact[:220].rsplit(" ", 1)[0].rstrip() + "..."
        return f"Source note: {compact}\nWhat decision or teach moment does this create at the table?"
