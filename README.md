# glow-cloud

Your own Lightning wallet in the cloud: always-on and free. Deploy to Vercel + Supabase (both have generous free tiers) and get a personal Lightning API you can hit from anywhere at any time, without running infrastructure yourself.

Built on the [Breez SDK - Spark](https://github.com/nickhntv/breez-sdk-spark).

## Quick Start

```bash
git clone https://github.com/kingonly/glow-cloud.git && cd glow-cloud
uv sync
source .venv/bin/activate
glow setup
```

The setup wizard walks you through generating a wallet mnemonic, getting a Breez API key, provisioning a Supabase database, and deploying to Vercel.

**Windows:** Open PowerShell as admin, run `wsl --install`, and restart your PC. Then open a terminal, type `wsl`, and run the commands above.

## What It Does

glow-cloud gives you a personal Lightning API. Once deployed, you can:

- **Receive** Lightning payments via BOLT11 invoices
- **Send** payments to invoices or Lightning addresses
- **Check balance** and pending transactions
- **Manage API keys** with granular permissions and spending budgets

## CLI

The `glow` command is installed automatically by `uv sync`.

```bash
glow health                                        # check API status
glow balance                                       # show wallet balance
glow receive --amount 1000 --description "tip"     # create an invoice
glow send <invoice>                                # pay an invoice
glow keys create myapp --permissions balance receive --budget 10000 --period daily
glow keys list
glow keys revoke <key_id>
```

Config is stored in `~/.config/glow-cloud/config.json` and auto-populated after deploy. You can also use `--url`/`--key` flags or `GLOW_CLOUD_URL`/`GLOW_CLOUD_KEY` env vars.

## Stack

- **Python 3.12+** / FastAPI
- **Breez SDK** for Lightning
- **Supabase** PostgreSQL for SDK persistence and app tables
- **Vercel** for deployment

## API Keys

Keys have permissions (`balance`, `receive`, `send`, `admin`) and optional spending budgets (`--budget 10000 --period daily`). Keys are shown once at creation and stored as SHA-256 hashes.

Admin keys can create and revoke other keys but cannot create other admin keys.

## Environment Variables

See `.env.example`. Required: `MNEMONIC`, `BREEZ_API_KEY`, `DATABASE_URL`, `NETWORK`.

## Running Locally

```bash
uv run uvicorn src.index:app --reload
```
