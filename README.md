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
- Manual rules sync and status commands
- Topic-of-the-day and optional design-prompt scheduled posts
- Poll creation, voting, closing, and historical results in SQLite
- Health/status command

## Project Layout

```text
bot/
  main.py
  cogs/
    admin.py
    bot_status.py
    daily.py
    polls.py
    rules.py
  models/
    daily.py
    polls.py
    rules.py
  services/
    build_rules_artifact.py
    content.py
    github_sync.py
    retrieval.py
    rules_index.py
    scheduler.py
  storage/
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

This bot does not require privileged intents for the implemented features. The default intents are sufficient.

## GitHub Rules Repo Setup

The bot reads rules from a private GitHub repository, but answers from a local checkout and local index.

Required environment variables:

- `GITHUB_TOKEN`: fine-grained GitHub PAT with read access to the private repo
- `GITHUB_RULES_REPO_URL=https://github.com/something`
- `GITHUB_RULES_BRANCH=master`
- `GITHUB_RULES_INCLUDE_PATHS=tools/rulebook/src`
- `GITHUB_RULES_LOCAL_PATH=data/rules_repo`
- `GITHUB_RULES_BUILD_COMMAND=python -m bot.services.build_rules_artifact`
- `GITHUB_RULES_ARTIFACT_PATH=data/rules_repo/.bot_cache/manual.md`
- `RULES_INDEX_PATH=data/rules_index.json`

Behavior:

- if the repo does not exist locally, the bot performs a sparse clone
- if it exists, the bot updates it with a pull
- the bot only indexes Markdown under `tools/rulebook/src`
- the build step concatenates those files into one local artifact
- the retrieval layer answers only from the local built/indexed copy

## Slash Commands

Rules:

- `/rules ask question:<text>`
- `/rules sync`
- `/rules status`

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
- attempts to load any existing rules index

## Testing the Core Flows

### Rules sync

1. Create a fine-grained GitHub PAT with repository read access to `afield0/vampire-defenders-2`.
2. Set `GITHUB_TOKEN` and the rules environment variables from `.env.example`.
3. Start the bot.
4. Run `/rules sync`.
5. Run `/rules status` to confirm the commit hash, artifact path, and chunk count.
6. Run `/rules ask question:...`.

You can also run the artifact build locally:

```bash
python -m bot.services.build_rules_artifact
```

The bot writes lightweight rules metadata locally in SQLite:

- last successful sync time
- last artifact build time
- current commit hash
- current chunk count

### Rules Q&A behavior

- `/rules ask` uses only the built local Markdown corpus from `tools/rulebook/src`
- answers are based on keyword retrieval over indexed chunks
- responses include section/source citations where available
- low-confidence questions return an explicit not-found style response

### Daily posts

1. Set `TOPIC_OF_DAY_CHANNEL_ID`.
2. Optionally set `DESIGN_PROMPT_CHANNEL_ID` and `ENABLE_DESIGN_PROMPT=true`.
3. Start the bot.
4. Run `/daily preview`.
5. Run `/daily post`.
6. Leave the bot running to allow scheduled posting at the configured time.

The scheduler stores the last posted date in SQLite so it does not repost the same daily item after a restart.

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

## Notes

- This version intentionally uses simple local retrieval first.
- `bot/services/retrieval.py` is structured so embeddings or vector search can replace the scorer later.
- TODOs for card lookup and optional LLM synthesis should stay in the rules services, not in the Discord cog.
