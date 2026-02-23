# glow-cloud

Self-deployable Bitcoin/Lightning payment API wrapping the Breez Spark SDK.

## Stack

- Python 3.12+ / FastAPI
- Breez Spark SDK (`breez-sdk-spark`) with PostgreSQL persistence
- asyncpg for app tables (API keys, budget)
- Deployed to Vercel + Supabase

## Project Structure

- `src/index.py` — FastAPI app entry point
- `src/routes/` — Route handlers (health, balance, receive, send)
- `src/middleware/auth.py` — API key auth + permission checks
- `src/services/sdk.py` — Breez Spark SDK singleton
- `src/services/db.py` — asyncpg connection pool
- `src/services/budget.py` — Budget enforcement
- `src/types.py` — Pydantic models
- `src/routes/keys.py` — Key management API (admin-only)
- `sql/001_init.sql` — Database schema
- `scripts/create_api_key.py` — API key generation
- `scripts/cli.py` — CLI (`glow` command) for interacting with deployed API

## Quick Start

```bash
git clone <repo> && cd glow-cloud
uv sync
source .venv/bin/activate
glow setup
```

**Windows:** Open PowerShell as admin, run `wsl --install`, and restart your PC. Then open a terminal, type `wsl`, and run the commands above.

## Running Locally

```bash
uv run uvicorn src.index:app --reload
```

## Environment Variables

See `.env.example`. Required: `MNEMONIC`, `BREEZ_API_KEY`, `DATABASE_URL`.

## API Keys

Generate with: `glow keys create <name> [--budget 10000 --period weekly]`

Or remotely via an admin key:
```bash
glow keys create myapp --permissions balance receive --budget 10000 --period daily
glow keys list
glow keys revoke <key_id>
```

Keys are shown once at creation and stored as SHA-256 hashes.

## CLI

`glow <command>` — interact with a deployed glow-cloud instance. Installed automatically by `uv sync`.

Config stored in `~/.config/glow-cloud/config.json` (auto-populated by `setup.py` after deploy). Can also use `--url`/`--key` flags or `GLOW_CLOUD_URL`/`GLOW_CLOUD_KEY` env vars.

```bash
glow config set-url <url>                          # save API URL
glow config set-key <key>                          # save API key
glow config show                                   # show config (key masked)
glow setup                                         # run setup wizard
glow health                                        # GET /health
glow balance                                       # GET /balance
glow receive [--amount 1000] [--description "tip"] # POST /receive
glow send <invoice> [--amount 1000]                # POST /send
glow keys create <name> [--permissions ...] [--budget N --period daily] # POST /keys (admin)
glow keys list                                     # GET /keys (admin)
glow keys revoke <key_id>                          # DELETE /keys/{id} (admin)
```

## Conventions

- All SDK calls are async
- Budget checks happen between prepare and send
- API key permissions: `balance`, `receive`, `send`, `admin`
- `admin` keys can manage other keys via `/keys` API; cannot create other admin keys (privilege escalation prevention)
- Only the setup wizard / DB script can create admin keys
