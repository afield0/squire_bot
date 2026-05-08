from __future__ import annotations

import json
import logging
import time
from typing import Any

from bot.models.rules import LLMAnswer, RuleCitation
from bot.services.rules_prompt import (
    RULES_ANSWER_SCHEMA,
    RULES_SYSTEM_INSTRUCTION,
    build_rules_user_message,
)
from bot.utils.config import OpenAIConfig

LOGGER = logging.getLogger(__name__)

DEBUG_DUMP_LIMIT = 2000
RULES_MAX_OUTPUT_TOKENS = 4096
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
                "max_output_tokens": RULES_MAX_OUTPUT_TOKENS,
                "store": False,
                "text": {
                    "format": RULES_ANSWER_SCHEMA,
                    "verbosity": "low",
                },
            }
            if self.config.model == "gpt-5" or self.config.model.startswith("gpt-5-"):
                request_kwargs["reasoning"] = {"effort": "minimal"}
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

        payload, payload_source = self._extract_payload(response)
        LOGGER.info("OpenAI structured response parsed from %s", payload_source)
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

    def _extract_payload(self, response: Any) -> tuple[dict[str, Any], str]:
        has_output_text_attr = self._has_value(response, "output_text")
        raw_output_text = self._get_value(response, "output_text")
        has_output_attr = self._has_value(response, "output")
        output_items = list(self._get_value(response, "output", []) or [])
        response_status = self._get_value(response, "status")
        incomplete_reason = self._extract_incomplete_reason(response)
        usage_summary = self._usage_summary(response)
        output_item_types = [self._get_value(item, "type", "unknown") for item in output_items]
        parsed_content_count = 0
        content_text_count = 0

        for item_index, item in enumerate(output_items):
            item_content = list(self._get_value(item, "content", []) or [])
            for content in item_content:
                content_parsed = self._get_value(content, "parsed")
                if content_parsed is not None:
                    parsed_content_count += 1

                content_text = self._get_value(content, "text")
                if isinstance(content_text, str) and content_text.strip():
                    content_text_count += 1

        LOGGER.info(
            "OpenAI response shape status=%s incomplete_reason=%s output_text_attr=%s output_text_empty=%s output_attr=%s output_count=%s output_item_types=%s parsed_content_count=%s content_text_count=%s usage=%s",
            response_status,
            incomplete_reason,
            has_output_text_attr,
            not bool(isinstance(raw_output_text, str) and raw_output_text.strip()),
            has_output_attr,
            len(output_items),
            output_item_types,
            parsed_content_count,
            content_text_count,
            usage_summary,
        )
        LOGGER.debug("OpenAI response dump (trimmed): %s", self._safe_response_dump(response))

        if response_status == "incomplete":
            raise RuntimeError(
                "OpenAI returned an incomplete response"
                f"{f' ({incomplete_reason})' if incomplete_reason else ''}. "
                f"Output item types: {output_item_types}. Usage: {usage_summary}"
            )

        payload = self._extract_from_parsed_content(output_items)
        if payload is not None:
            return payload

        payload = self._extract_from_content_text(output_items)
        if payload is not None:
            return payload

        if isinstance(raw_output_text, str) and raw_output_text.strip():
            parsed_output_text = self._parse_json_text(raw_output_text)
            if parsed_output_text is not None:
                return parsed_output_text, "response.output_text"
            raise RuntimeError("OpenAI returned non-empty output_text, but it was not valid JSON.")

        if has_output_text_attr:
            raise RuntimeError(
                "OpenAI returned empty output_text and no structured payload was found in response.output content. "
                f"Response status={response_status}, incomplete_reason={incomplete_reason}, "
                f"output_item_types={output_item_types}, usage={usage_summary}."
            )

        raise RuntimeError(
            "OpenAI returned a 200 response, but no structured payload was found. "
            f"Response status={response_status}, incomplete_reason={incomplete_reason}, "
            f"output_items={len(output_items)}, output_item_types={output_item_types}, "
            f"parsed_content_count={parsed_content_count}, content_text_count={content_text_count}, usage={usage_summary}."
        )

    def _extract_from_parsed_content(self, output_items: list[Any]) -> tuple[dict[str, Any], str] | None:
        for item_index, item in enumerate(output_items):
            item_content = list(self._get_value(item, "content", []) or [])
            for content_index, content in enumerate(item_content):
                content_path = f"response.output[{item_index}].content[{content_index}].parsed"
                payload = self._coerce_structured_payload(self._get_value(content, "parsed"))
                if payload is not None:
                    LOGGER.info(
                        "OpenAI structured payload found at %s keys=%s",
                        content_path,
                        sorted(payload.keys()),
                    )
                    return payload, content_path
        return None

    def _extract_from_content_text(self, output_items: list[Any]) -> tuple[dict[str, Any], str] | None:
        for item_index, item in enumerate(output_items):
            item_content = list(self._get_value(item, "content", []) or [])
            for content_index, content in enumerate(item_content):
                content_path = f"response.output[{item_index}].content[{content_index}].text"
                content_text = self._get_value(content, "text")
                if not isinstance(content_text, str) or not content_text.strip():
                    continue
                payload = self._parse_json_text(content_text)
                if payload is not None:
                    LOGGER.info(
                        "OpenAI structured JSON text found at %s keys=%s",
                        content_path,
                        sorted(payload.keys()),
                    )
                    return payload, content_path
        return None

    @staticmethod
    def _has_value(container: Any, key: str) -> bool:
        if isinstance(container, dict):
            return key in container
        return hasattr(container, key)

    @staticmethod
    def _get_value(container: Any, key: str, default: Any = None) -> Any:
        if isinstance(container, dict):
            return container.get(key, default)
        return getattr(container, key, default)

    @classmethod
    def _extract_incomplete_reason(cls, response: Any) -> str | None:
        incomplete_details = cls._get_value(response, "incomplete_details")
        reason = cls._get_value(incomplete_details, "reason")
        return str(reason) if reason else None

    @classmethod
    def _usage_summary(cls, response: Any) -> dict[str, Any]:
        usage = cls._to_plain_data(cls._get_value(response, "usage")) or {}
        if not isinstance(usage, dict):
            return {}
        output_details = usage.get("output_tokens_details")
        if not isinstance(output_details, dict):
            output_details = {}
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": output_details.get("reasoning_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }

    @staticmethod
    def _coerce_structured_payload(candidate: Any) -> dict[str, Any] | None:
        plain = OpenAIRulesClient._to_plain_data(candidate)
        if isinstance(plain, dict):
            return plain
        return None

    @staticmethod
    def _parse_json_text(candidate: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _to_plain_data(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [OpenAIRulesClient._to_plain_data(item) for item in value]
        if isinstance(value, dict):
            return {key: OpenAIRulesClient._to_plain_data(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            return OpenAIRulesClient._to_plain_data(dumped)
        return value

    @staticmethod
    def _safe_response_dump(response: Any) -> str:
        dump = None
        if hasattr(response, "model_dump_json"):
            try:
                dump = response.model_dump_json(indent=2)
            except TypeError:
                dump = response.model_dump_json()
        if dump is None:
            dump = repr(response)
        if len(dump) <= DEBUG_DUMP_LIMIT:
            return dump
        return dump[: DEBUG_DUMP_LIMIT - 3] + "..."
