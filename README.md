# Vampire Defenders Discord Bot

Local-first Discord bot scaffold for the Vampire Defenders board game project.

This project uses:

- Python 3.12
- `discord.py` slash commands
- cogs/extensions
- SQLite for runtime state
- a local sparse checkout of a private GitHub repo for rules content

## Features

- Rules lookup from a private GitHub repo using a local built artifact
- Manual rules sync and rebuild commands
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
    content.py
    github_sync.py
    retrieval.py
    rules_build.py
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

- `GITHUB_RULES_REPO_URL`: HTTPS clone URL for the private repo
- `GITHUB_RULES_BRANCH`: branch to sync from
- `GITHUB_RULES_LOCAL_PATH`: local checkout path
- `GITHUB_RULES_INCLUDE_PATHS`: comma-separated repo paths to sparse-checkout
- `GITHUB_TOKEN`: GitHub token with read access to the private repo

Optional build settings:

- `GITHUB_RULES_BUILD_COMMAND`: command to run inside the checkout after sync
- `GITHUB_RULES_ARTIFACT_PATH`: artifact path to index after build
- `RULES_INDEX_PATH`: local JSON index path used by retrieval

Behavior:

- if the repo does not exist locally, the bot performs a sparse clone
- if it exists, the bot updates it with a pull
- if `GITHUB_RULES_BUILD_COMMAND` is set, that command is used to produce the final artifact
- otherwise, the bot concatenates the configured sparse paths into one Markdown artifact

## Slash Commands

Rules:

- `/rules ask question:<text>`
- `/rules sources`

Daily:

- `/daily preview`
- `/daily post`

Polls:

- `/poll create question:<text> options:<comma-separated>`
- `/poll results id:<poll_id>`
- `/poll close id:<poll_id>`

Admin:

- `/admin sync-rules`
- `/admin rebuild-rules`

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

1. Set the GitHub repo environment variables.
2. Start the bot.
3. Run `/admin sync-rules`.
4. Run `/rules sources` to confirm the local artifact and revision are loaded.
5. Run `/rules ask question:...`.

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

## Notes

- This scaffold intentionally uses simple local retrieval first.
- `bot/services/retrieval.py` is structured so embeddings or vector search can replace the scorer later.
- `bot/services/content.py` isolates daily content generation so an LLM can be introduced later without changing the Discord command layer.
