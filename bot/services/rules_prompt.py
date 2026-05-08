from __future__ import annotations

RULES_SYSTEM_INSTRUCTION = """
You are a rules Q&A assistant for Vampire Defenders 2.

You must answer only from the supplied rulebook text.
Do not use outside knowledge, prior board game knowledge, or assumptions.
Do not invent missing rules.
If the rulebook text does not clearly answer the question, respond with exactly:
"I could not find a clear answer in the indexed rulebook."

If the rulebook appears ambiguous or internally unclear, say so plainly and explain the ambiguity.
Keep the answer concise and practical.
Include citations to the most relevant section headings and source filenames when possible.
Return JSON matching the provided schema.
""".strip()


RULES_ANSWER_SCHEMA: dict[str, object] = {
    "type": "json_schema",
    "name": "rules_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["answered", "ambiguous", "not_found"],
            },
            "grounded": {
                "type": "boolean",
            },
            "answer": {
                "type": "string",
            },
            "ambiguity_note": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ],
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_file": {"type": "string"},
                        "heading": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["source_file", "heading", "label"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["status", "grounded", "answer", "ambiguity_note", "citations"],
        "additionalProperties": False,
    },
}


def build_rules_user_message(question: str, rulebook_text: str) -> str:
    return "\n\n".join(
        [
            "User question:",
            question.strip(),
            "Rulebook text begins below. Use only this text as your source of truth.",
            "<rulebook>",
            rulebook_text,
            "</rulebook>",
        ]
    )
