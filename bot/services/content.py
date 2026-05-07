from __future__ import annotations

from datetime import date

from bot.models.daily import DailyPost


class DailyContentService:
    def build_topic_of_day(self, today: date) -> DailyPost:
        prompts = [
            "Which monster pressure point feels most interesting to defend against right now?",
            "What player decision in the current ruleset creates the most tension?",
            "Which card or action could use a cleaner teach moment for new players?",
            "What late-game state currently feels most exciting at the table?",
            "Which defensive tool feels underused and why?",
            "What rule causes the most playtest pause or clarification request?",
            "Which turn choice creates the strongest risk-reward tradeoff?",
        ]
        topic = prompts[today.toordinal() % len(prompts)]
        return DailyPost(
            title="Vampire Defenders Topic of the Day",
            body=topic,
        )

    def build_design_prompt(self, today: date) -> DailyPost:
        prompts = [
            "Design one small rule tweak that increases player cooperation without reducing tension.",
            "Pitch a new enemy behavior that changes how players value positioning.",
            "Draft a playtest question that would expose balance problems in the midgame.",
            "Invent a new card concept that helps recovery after a bad round.",
            "Propose one scenario modifier that makes the opening turns less scripted.",
        ]
        prompt = prompts[today.toordinal() % len(prompts)]
        return DailyPost(
            title="Vampire Defenders Daily Design Prompt",
            body=prompt,
        )
