from __future__ import annotations

import logging
from pathlib import Path

from bot.utils.config import RulesSyncConfig, load_rules_sync_config

LOGGER = logging.getLogger(__name__)


class RulesArtifactBuilder:
    def __init__(self, config: RulesSyncConfig) -> None:
        self.config = config

    def build(self) -> Path:
        markdown_files = self._discover_markdown_files()
        if not markdown_files:
            raise RuntimeError(
                "No markdown files were found under the configured rules source paths."
            )

        artifact_path = self.artifact_path()
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        sections: list[str] = []
        for file_path in markdown_files:
            relative_path = file_path.relative_to(self.config.local_checkout_path).as_posix()
            sections.append(
                "\n".join(
                    [
                        f"# File: {relative_path}",
                        "",
                        f"<!-- source: {relative_path} -->",
                        "",
                        file_path.read_text(encoding="utf-8").rstrip(),
                    ]
                ).strip()
            )

        artifact_path.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
        LOGGER.info("Built rules artifact at %s", artifact_path)
        return artifact_path

    def artifact_path(self) -> Path:
        return self.config.artifact_path

    def _discover_markdown_files(self) -> list[Path]:
        markdown_files: list[Path] = []
        for include_path in self.config.include_paths:
            target = self.config.local_checkout_path / include_path
            if not target.exists():
                continue
            if target.is_file() and target.suffix.lower() == ".md":
                markdown_files.append(target)
                continue
            if target.is_dir():
                markdown_files.extend(path for path in target.rglob("*.md") if path.is_file())

        return sorted(markdown_files, key=lambda path: (path.name.lower(), path.as_posix().lower()))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    config = load_rules_sync_config()
    artifact_path = RulesArtifactBuilder(config).build()
    print(artifact_path)


if __name__ == "__main__":
    main()
