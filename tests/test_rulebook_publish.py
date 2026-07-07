from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path

discord_module = types.ModuleType("discord")
discord_module.File = object
discord_module.Forbidden = RuntimeError
discord_module.HTTPException = RuntimeError
discord_module.NotFound = RuntimeError
discord_module.abc = types.SimpleNamespace(Messageable=object)
commands_module = types.ModuleType("discord.ext.commands")
commands_module.Bot = object
discord_ext_module = types.ModuleType("discord.ext")
discord_ext_module.commands = commands_module
dotenv_module = types.ModuleType("dotenv")
dotenv_module.load_dotenv = lambda: None
sys.modules.setdefault("discord", discord_module)
sys.modules.setdefault("discord.ext", discord_ext_module)
sys.modules.setdefault("discord.ext.commands", commands_module)
sys.modules.setdefault("dotenv", dotenv_module)

from bot.services.rulebook_publish import RulebookPublishService, RulebookPublishState
from bot.utils.config import RulebookPublishConfig


class RecordingRulebookPublishService(RulebookPublishService):
    def __init__(self, config: RulebookPublishConfig, state_commit: str | None) -> None:
        super().__init__(config=config, state_repo=None, bot=None)  # type: ignore[arg-type]
        self.state_commit = state_commit
        self.published_commit: str | None = None

    async def get_state(self) -> RulebookPublishState:
        return RulebookPublishState(
            commit=self.state_commit,
            message_id=None,
            channel_id=None,
            published_at=None,
        )

    async def publish(self, commit: str) -> str:  # type: ignore[override]
        self.published_commit = commit
        return commit


def _service(root_path: Path, state_commit: str | None) -> RecordingRulebookPublishService:
    pdf_path = root_path / "rules_repo" / "tools" / "rulebook" / "Rulebook_compressed.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF")
    pdf_path.with_name("Rulebook_compressed.metadata.json").write_text(
        '{"build_commit":"metadata-build-commit"}',
        encoding="utf-8",
    )
    return RecordingRulebookPublishService(
        RulebookPublishConfig(
            channel_id=123,
            pdf_path=pdf_path,
            auto_publish=True,
            delete_previous=True,
        ),
        state_commit=state_commit,
    )


class RulebookPublishTests(unittest.TestCase):
    def test_auto_publish_uses_checkout_commit_not_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(Path(tmp_dir), state_commit="metadata-build-commit")

            result = asyncio.run(service.maybe_publish_for_commit("checkout-head-commit"))

        self.assertEqual(result, "checkout-head-commit")
        self.assertEqual(service.published_commit, "checkout-head-commit")

    def test_auto_publish_skips_when_checkout_commit_was_published(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = _service(Path(tmp_dir), state_commit="checkout-head-commit")

            result = asyncio.run(service.maybe_publish_for_commit("checkout-head-commit"))

        self.assertIsNone(result)
        self.assertIsNone(service.published_commit)


if __name__ == "__main__":
    unittest.main()
