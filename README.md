# Squire Discord Bot

Local-first Discord bot scaffold for a board game project.

This project uses:

- Python 3
- `discord.py` slash commands
- cogs/extensions
- SQLite for runtime state
- a local sparse checkout of a private GitHub repo for rules content

## Features

- Rules lookup from a private GitHub repo using a local built artifact
- Rulebook PDF publishing to Discord as the player-facing host for the private repo's latest compressed PDF
- Card lookup from a local JSON artifact built from the game repo card registry
- OpenAI-grounded rules answers that send the full local rulebook artifact on each query
- Manual rules sync and status commands
- Grounded topic-of-the-day and optional design-prompt scheduled posts
- Poll creation, voting, closing, and historical results in SQLite
- Optional first-join greeting in a configured channel plus a capability DM
- Health/status command

## Project Layout

```text
bot/
  main.py
  cogs/
    admin.py
    bot_status.py
    cards.py
    daily.py
    polls.py
    rulebook.py
    rules.py
    welcome.py
  models/
    cards.py
    daily.py
    polls.py
    rules.py
  services/
    build_cards_artifact.py
    build_rules_artifact.py
    cards.py
    content.py
    daily_llm.py
    daily_sources.py
    github_sync.py
    openai_client.py
    retrieval.py
    rulebook_publish.py
    rules_index.py
    rules_prompt.py
    scheduler.py
    topic_seeds.py
  storage/
    daily_repo.py
    db.py
    poll_repo.py
    state_repo.py
  utils/
    config.py
    logging.py
```

## Setup

1. Create and activate a Python 3.12 virtual environment.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in the required values.

3. Run the bot locally.

```bash
python -m bot.main
```

## Discord Bot Creation Notes

Create an application and bot in the Discord Developer Portal.

Required values:

- `DISCORD_BOT_TOKEN`
- `DISCORD_APPLICATION_ID`

Optional for faster command iteration during development:

- `DISCORD_GUILD_ID`

Recommended bot permissions:

- `Send Messages`
- `View Channels`
- `Use Slash Commands`
- `Read Message History`
- `Add Reactions`
- `Manage Messages` for removing invalid or replaced votes cleanly
- `Attach Files` for publishing the rulebook PDF
- `Manage Messages` in the rulebook channel if `RULEBOOK_DELETE_PREVIOUS=true`

Most features use default intents. The welcome feature requires the privileged `Server Members Intent` in the Discord Developer Portal because it listens for new server members.

Welcome configuration:

- `WELCOME_ENABLED=false`
- `WELCOME_CHANNEL_ID`
- `WELCOME_DM_ENABLED=true`

## GitHub Rules Repo Setup

The bot reads rules from a private GitHub repository, builds a combined local Markdown artifact, and answers rules questions from that local artifact.

Required environment variables:

- `GITHUB_TOKEN`: fine-grained GitHub PAT with read access to the private repo
- `GITHUB_RULES_REPO_URL=https://github.com/something`
- `GITHUB_RULES_BRANCH=master`
- `GITHUB_RULES_INCLUDE_PATHS=tools/rulebook/src,game/cards,game/common,assets/cards/rendered`
- `GITHUB_RULES_LOCAL_PATH=data/rules_repo`
- `GITHUB_RULES_BUILD_COMMAND=python -m bot.services.build_rules_artifact`
- `GITHUB_RULES_ARTIFACT_PATH=data/rules_repo/.bot_cache/manual.md`
- `CARDS_ARTIFACT_PATH=data/rules_repo/.bot_cache/cards.json`
- `RULEBOOK_CHANNEL_ID`
- `RULEBOOK_PDF_PATH=data/rules_repo/releases/rulebook/Rulebook_compressed.pdf`
- `RULEBOOK_AUTO_PUBLISH=true`
- `RULEBOOK_DELETE_PREVIOUS=true`
- `OPENAI_API_KEY`
- `OPENAI_MODEL=gpt-5`
- `OPENAI_TEMPERATURE=` optional, blank by default
- `RULES_USE_LLM=true`
- `RULES_LLM_TIMEOUT_SECONDS=30`

Behavior:

- if the repo does not exist locally, the bot performs a sparse clone
- if it exists, the bot updates it with a pull
- the sparse checkout includes the rulebook source, card definitions, common code, and rendered card images under `assets/cards/rendered`
- the build step concatenates those files into one local artifact at `data/rules_repo/.bot_cache/manual.md`
- the card build imports the card registry from the local checkout and writes normalized card data to `data/rules_repo/.bot_cache/cards.json`
- rulebook PDF publishing uploads the local compressed PDF from the private repo checkout to Discord as an attachment; Discord is the player-facing host, not GitHub
- if `RULEBOOK_PDF_PATH` is under `GITHUB_RULES_LOCAL_PATH`, the bot automatically adds that PDF path and its metadata path to the sparse checkout paths
- `/rules ask` sends the entire local artifact plus the user question to OpenAI on each call
- the prompt tells the model to answer only from the supplied rulebook text and to say when the answer is unclear or missing
- fallback is user-friendly and does not use local chunk retrieval as the main answer path

### GitHub PAT

Create a fine-grained personal access token on GitHub with read-only repository access to the private rules repository, then set it in `GITHUB_TOKEN`.

The bot does not log the token and sanitizes Git command output before surfacing failures.

## OpenAI Rules Answering

The rules bot uses only one LLM backend right now: OpenAI.

With the current Responses API integration for `gpt-5`, the bot does not send `temperature` on the API call. `OPENAI_TEMPERATURE` may be left blank in `.env` and is treated as `None`.

For each `/rules ask` request:

- the bot loads the full local `manual.md` artifact
- the bot sends the entire artifact and the user question to OpenAI
- the model is instructed to answer only from that supplied rulebook text
- the response should include short citations by filename and heading where possible

If OpenAI is unavailable, misconfigured, or times out, the bot does not crash. It returns a user-facing fallback message and logs the failure cleanly.

## Slash Commands

Rules:

- `/rules ask question:<text>`
- `/rules sync`
- `/rules status`
- `/rules debug question:<text>`

Cards:

- `/card search query:<text>` returns the matching card image
- `/card show query:<text>` returns the matching card image plus card details
- `/card random type:<optional>`

Rulebook:

- `/rulebook post`
- `/rulebook latest`
- `/rulebook status`

Daily:

- `/daily preview`
- `/daily post`

Polls:

- `/poll create question:<text> options:<comma-separated>`
- `/poll results id:<poll_id>`
- `/poll close id:<poll_id>`

Bot:

- `/bot status`

## Running Locally

```bash
python -m bot.main
```

On startup the bot:

- loads configuration from `.env`
- initializes SQLite schema
- loads cogs
- syncs slash commands
- initializes the OpenAI rules client if enabled

### Welcome messages

Set `WELCOME_ENABLED=true` and `WELCOME_CHANNEL_ID` to the general/welcome channel id to greet new server members. The bot posts a short channel greeting and, when `WELCOME_DM_ENABLED=true`, sends the member a private message listing useful commands:

- `/rulebook latest`
- `/rules ask`
- `/card show`, `/card search`, `/card random`
- `/bot status`

The bot stores `welcome_greeted:<guild_id>:<member_id>` in SQLite after a successful greeting or DM so it does not repeat the same first-join message for that member.

## Testing the Core Flows

### Rules sync

1. Create a fine-grained GitHub PAT with repository read access to the private rules repository.
2. Set `GITHUB_TOKEN`, `OPENAI_API_KEY`, and the rules environment variables from `.env.example`.
3. Start the bot.
4. Run `/rules sync`.
5. Run `/rules status` to confirm the commit hash, artifact path, artifact size, and model.
6. Run `/rules ask question:...`.
7. Optionally run `/rules debug question:...` to inspect artifact load size, model use, and latency.

You can also run the artifact build locally:

```bash
python -m bot.services.build_rules_artifact
python -m bot.services.build_cards_artifact
```

The bot writes lightweight rules metadata locally in SQLite:

- last successful sync time
- last artifact build time
- current commit hash

### Rulebook PDF publishing

The bot can publish the private game's latest compressed rulebook PDF into a Discord channel without making the private rules repository public.

Set:

- `RULEBOOK_CHANNEL_ID` to the Discord channel that should host the PDF attachment
- `RULEBOOK_PDF_PATH=data/rules_repo/releases/rulebook/Rulebook_compressed.pdf`
- `RULEBOOK_AUTO_PUBLISH=true` to publish after a successful sync/build when the synced commit changes
- `RULEBOOK_DELETE_PREVIOUS=true` to delete the previously published rulebook message after the new upload succeeds

Commands:

- `/rulebook post` publishes the current local PDF immediately; admin only
- `/rulebook latest` shows the latest known published commit, time, and message link when available
- `/rulebook status` shows channel, PDF path, file size, current synced commit, latest published state, and auto-publish settings; admin only

State is stored in SQLite with these keys:

- `rulebook_last_published_commit`
- `rulebook_last_published_message_id`
- `rulebook_last_published_at`
- `rulebook_last_published_channel_id`

Auto-publish uses the existing private repo sync flow. After `/rules sync`, and during the lightweight periodic sync check when enabled, the bot compares the current synced commit to the last published commit and only uploads a new PDF when the commit changed.

The compressed PDF should already exist in the private repo at `releases/rulebook/Rulebook_compressed.pdf`. The bot fetches that file through the private sparse checkout and then republishes it as a Discord attachment.

If the rulebook PDF is built and then committed, build metadata may be written next to the PDF so the bot can report when and from what source the PDF was produced:

```json
{
  "build_commit": "full git sha used to build the PDF",
  "built_at": "2026-05-09T14:30:00Z"
}
```

For the default PDF path, the metadata file should be:

`data/rules_repo/releases/rulebook/Rulebook_compressed.metadata.json`

In the private repo, that corresponds to:

`releases/rulebook/Rulebook_compressed.metadata.json`

The bot publishes and deduplicates using the synced checkout commit. The rulebook post reads the Git commit message for that checkout commit and includes it with the PDF.

### Rules Q&A behavior

- `/rules ask` uses only the built local Markdown corpus from `tools/rulebook/src`
- the entire combined rulebook artifact is sent to OpenAI for each question
- the prompt forbids outside knowledge and requires the model to stay grounded in the supplied rulebook text
- responses include a short `Sources:` section when citations are available
- if the answer is ambiguous, the bot says so clearly
- if the answer is not clearly present, the bot returns: `I could not find a clear answer in the indexed rulebook.`
- if `RULES_USE_LLM=false`, the bot responds that LLM mode is disabled
- if OpenAI fails, the bot returns a fallback message instead of crashing

### Daily posts

1. Set `TOPIC_OF_DAY_CHANNEL_ID`.
2. Optionally set `DESIGN_PROMPT_CHANNEL_ID` and `ENABLE_DESIGN_PROMPT=true`.
3. Start the bot.
4. Run `/daily preview`.
5. Run `/daily post`.
6. Leave the bot running to allow scheduled posting at the configured time.

The scheduler stores the last posted date in SQLite so it does not repost the same daily item after a restart.

Daily topic posts are generated from a local, grounded topic-seed pipeline:

- seed definitions live in `data/topic_seeds.json`
- each seed has `id`, `category`, `source_type`, `intent`, `weight`, `cooldown_days`, and `source_hints`
- the source gatherer supports `rulebook`, `cards`, and `mixed` seeds when the matching local artifacts exist
- card source gathering reads `CARDS_ARTIFACT_PATH` and produces compact source labels such as `Card: Bell Tower`
- the gatherer finds small excerpts using `source_hints` and includes their labels in the rendered Discord post
- lore source gathering is intentionally left as a TODO until a local lore artifact exists

Daily LLM composition is controlled separately from rules Q&A:

- `DAILY_USE_LLM=true` enables OpenAI composition for daily topics
- `DAILY_MAX_SOURCE_EXCERPTS=3` caps the excerpt packet sent to the model
- `DAILY_TOPIC_SEEDS_PATH=data/topic_seeds.json` points at the seed catalog
- `DAILY_TOPIC_MODE=daily` and `DAILY_WEEKLY_MODE=false` are reserved for future mode changes

When daily LLM composition is disabled, unavailable, or fails, the bot uses a template fallback from the selected seed and gathered excerpts. The fallback still includes source labels and does not call out to GitHub or any external runtime state.

The bot records successful topic posts in SQLite in `daily_posts` with the seed id, category, posted timestamp, source labels, channel id, and Discord message id. Seed selection checks that history and applies each seed's `cooldown_days`; if every seed is cooling down, it falls back to the weighted catalog instead of failing the scheduled post.

### Polls

1. Run `/poll create question:... options:option a,option b,option c`
2. Vote by reacting to the poll message with the matching emoji
3. Inspect totals with `/poll results`
4. Close the poll with `/poll close`

Polls and votes are stored in SQLite and remain available across restarts.

## Security Notes

- `.env` stays local and should never be committed.
- The bot never uses GitHub as a database for runtime state.
- The sync service sanitizes token-bearing command output before surfacing errors.
- The bot never logs `OPENAI_API_KEY`.
- The bot does not log the full prompt body unless you add your own debug logging.

## Notes

- This version intentionally keeps the rules architecture simple and readable.
- The primary answer path does not use local chunk retrieval or semantic search.
- TODOs for chunk retrieval and lore lookup should stay in services, not in Discord cogs.
