from __future__ import annotations

import json
import logging
import time

from bot.models.rules import LLMAnswer, RuleCitation
from bot.services.rules_prompt import (
    RULES_ANSWER_SCHEMA,
    RULES_SYSTEM_INSTRUCTION,
    build_rules_user_message,
)
from bot.utils.config import OpenAIConfig

LOGGER = logging.getLogger(__name__)

NOT_FOUND_MESSAGE = "I could not find a clear answer in the indexed rulebook."


class OpenAIRulesClient:
    def __init__(self, config: OpenAIConfig) -> None:
        self.config = config
        self._client = None
        self._client_error: str | None = None

        if not self.config.rules_use_llm:
            LOGGER.info("Rules LLM mode is disabled")
            return
        if not self.config.api_key:
            self._client_error = "OPENAI_API_KEY is not configured."
            LOGGER.warning("Rules LLM mode is enabled but OPENAI_API_KEY is missing")
            return

        try:
            from openai import OpenAI
        except ImportError:
            self._client_error = "The `openai` package is not installed."
            LOGGER.warning("Rules LLM mode is enabled but the openai package is not installed")
            return

        self._client = OpenAI(
            api_key=self.config.api_key,
            timeout=self.config.timeout_seconds,
        )
        LOGGER.info("Rules OpenAI client initialized model=%s", self.config.model)

    def enabled(self) -> bool:
        return self.config.rules_use_llm

    def available(self) -> bool:
        return self._client is not None

    def availability_error(self) -> str | None:
        return self._client_error

    def answer_rules_question(self, question: str, rulebook_text: str) -> LLMAnswer:
        if not self.config.rules_use_llm:
            raise RuntimeError("LLM mode is disabled.")
        if self._client is None:
            raise RuntimeError(self._client_error or "OpenAI client is unavailable.")

        started = time.perf_counter()
        LOGGER.info(
            "Sending full rulebook artifact to OpenAI model=%s chars=%s",
            self.config.model,
            len(rulebook_text),
        )

        try:
            request_kwargs = {
                "model": self.config.model,
                "instructions": RULES_SYSTEM_INSTRUCTION,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": build_rules_user_message(question, rulebook_text),
                            }
                        ],
                    }
                ],
                "tool_choice": "none",
                "max_output_tokens": 900,
                "store": False,
                "text": {
                    "format": RULES_ANSWER_SCHEMA,
                    "verbosity": "low",
                },
            }
            response = self._client.responses.create(**request_kwargs)
        except Exception:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            LOGGER.exception(
                "OpenAI rules call failed model=%s latency_ms=%s",
                self.config.model,
                latency_ms,
            )
            raise

        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        LOGGER.info(
            "OpenAI rules call completed model=%s latency_ms=%s",
            self.config.model,
            latency_ms,
        )

        raw_output = getattr(response, "output_text", "") or ""
        if not raw_output.strip():
            raise RuntimeError("OpenAI returned an empty response.")

        payload = json.loads(raw_output)
        citations = [
            RuleCitation(
                source_file=item.get("source_file", "").strip(),
                heading=item.get("heading", "").strip(),
                label=item.get("label", "").strip(),
            )
            for item in payload.get("citations", [])
        ]

        answer = str(payload.get("answer", "")).strip() or NOT_FOUND_MESSAGE
        status = str(payload.get("status", "not_found")).strip()
        ambiguity_note = payload.get("ambiguity_note")
        grounded = bool(payload.get("grounded", False))

        if status == "not_found":
            answer = NOT_FOUND_MESSAGE

        return LLMAnswer(
            answer=answer,
            citations=[citation for citation in citations if citation.label],
            grounded=grounded,
            status=status,
            ambiguity_note=ambiguity_note.strip() if isinstance(ambiguity_note, str) and ambiguity_note.strip() else None,
        )
