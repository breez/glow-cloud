"""
glow-cloud setup wizard.

Run: glow setup

Installs dependencies automatically, then walks through:
  1. Mnemonic — generate new or use existing
  2. Breez API key — request or enter existing
  3. Supabase database — provision or enter existing URL
  4. Network selection
  5. Run SQL migrations
  6. Create first API key
  7. Deploy to Vercel (installs Node.js + Vercel CLI if needed)
"""

import argparse
import asyncio
import base64
import getpass
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from urllib.parse import quote as urlquote, urlencode
from urllib.request import Request, urlopen

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)


def ensure_dependencies():
    """Install uv (if needed), sync deps, and re-exec under uv run."""
    # If already running inside uv's venv, deps are available
    if os.environ.get("VIRTUAL_ENV"):
        return

    # Install uv if not available
    if not shutil.which("uv"):
        print("  Installing uv package manager...", end=" ", flush=True)
        result = subprocess.run(
            ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("failed.")
            print("  Install uv manually: https://docs.astral.sh/uv/getting-started/installation/")
            sys.exit(1)
        # Add to PATH for this session
        uv_bin = os.path.expanduser("~/.local/bin")
        os.environ["PATH"] = f"{uv_bin}:{os.environ['PATH']}"
        print("done.")

    # Install project dependencies
    print("  Installing dependencies...", end=" ", flush=True)
    result = subprocess.run(
        ["uv", "sync"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("failed.")
        print(f"  {result.stderr.strip()}")
        sys.exit(1)
    print("done.")
    print()

    # Re-exec this script under uv run so imports resolve from the venv
    os.execvp("uv", ["uv", "run", "--project", PROJECT_DIR, "python", *sys.argv])


# Install deps and re-exec if needed
ensure_dependencies()

import asyncpg  # noqa: E402

BREEZ_API_KEY_URL = "https://breez.technology/contact/apikey"
SUPABASE_API = "https://api.supabase.com/v1"
ENV_PATH = os.path.join(PROJECT_DIR, ".env")
SQL_PATH = os.path.join(PROJECT_DIR, "sql", "001_init.sql")


def _supabase_request(
    method: str, path: str, token: str, body: dict | None = None
) -> dict | list | None:
    """Make a request to the Supabase Management API."""
    from urllib.error import HTTPError

    url = f"{SUPABASE_API}{path}"
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "glow-cloud/0.1")
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except HTTPError as e:
        body_text = e.read().decode(errors="replace")
        print(f"failed. (HTTP {e.code})")
        if e.code == 403:
            print("  Token was rejected. Check that:")
            print("    - You copied the full token (starts with 'sbp_')")
            print("    - No extra spaces or quotes were included")
            print("    - The token hasn't been revoked")
        else:
            print(f"  Response: {body_text[:200]}")
        return None


def provision_supabase(token: str) -> str | None:
    """Create a Supabase project and return the DATABASE_URL."""
    # Get organizations
    print("  Fetching organizations...", end=" ", flush=True)
    orgs = _supabase_request("GET", "/organizations", token)
    if not orgs:
        print("failed. No organizations found.")
        return None
    print("done.")

    if len(orgs) == 1:
        org = orgs[0]
        print(f"  Using org: {org['name']}")
    else:
        print("  Available organizations:")
        for i, org in enumerate(orgs):
            print(f"    {i + 1}. {org['name']}")
        choice = int(input("  Select org number: ").strip()) - 1
        org = orgs[choice]

    # Generate DB password
    db_pass = base64.urlsafe_b64encode(secrets.token_bytes(24)).decode().rstrip("=")

    # Pick region
    print()
    print("  Region groups: 1) Americas  2) Europe/Africa  3) Asia-Pacific")
    region_choice = input("  Select region [1]: ").strip() or "1"
    region_code = {"1": "americas", "2": "emea", "3": "apac"}.get(region_choice, "americas")

    # Create project
    print()
    print("  Creating Supabase project...", end=" ", flush=True)
    project = _supabase_request("POST", "/projects", token, {
        "name": "glow-cloud",
        "organization_slug": org["id"],
        "db_pass": db_pass,
        "region_selection": {"type": "smartGroup", "code": region_code},
    })
    if not project or "ref" not in project:
        print("failed.")
        print(f"  Response: {project}")
        return None
    ref = project["ref"]
    region = project["region"]
    print(f"done. (ref: {ref})")

    # Poll for health
    print("  Waiting for project to be ready", end="", flush=True)
    for _ in range(60):
        time.sleep(5)
        print(".", end="", flush=True)
        try:
            health = _supabase_request("GET", f"/projects/{ref}/health?services=db&services=pooler", token)
            if health and all(
                s.get("status") == "ACTIVE_HEALTHY" for s in health
            ):
                break
        except Exception:
            pass
    else:
        print(" timed out.")
        print("  Project created but may still be provisioning.")
        print(f"  Check: https://supabase.com/dashboard/project/{ref}")

    print(" ready.")

    # Get pooler connection string from API (hostname varies per project)
    print("  Fetching pooler config...", end=" ", flush=True)
    pooler_config = _supabase_request("GET", f"/projects/{ref}/config/database/pooler", token)
    if pooler_config and len(pooler_config) > 0:
        pc = pooler_config[0]
        database_url = (
            f"postgresql://{pc['db_user']}:{urlquote(db_pass)}"
            f"@{pc['db_host']}:{pc['db_port']}/{pc['db_name']}"
        )
        print("done.")
    else:
        # Fallback: construct from known pattern
        database_url = (
            f"postgresql://postgres.{ref}:{urlquote(db_pass)}"
            f"@aws-0-{region}.pooler.supabase.com:6543/postgres"
        )
        print("failed, using fallback.")

    print(f"  Database URL constructed (pooler).")
    return database_url


async def request_breez_api_key(fullname: str, email: str, company: str) -> bool:
    """Request a Breez API key via their contact endpoint."""
    try:
        data = urlencode({
            "fullname": fullname,
            "company": company,
            "email": email,
            "message": "API key request for glow-cloud deployment",
        }).encode()
        req = Request(BREEZ_API_KEY_URL, data=data)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def generate_mnemonic() -> str:
    """Generate a 12-word BIP39 mnemonic using python-mnemonic (Trezor)."""
    from mnemonic import Mnemonic

    m = Mnemonic("english")
    return m.generate(strength=128)  # 128 bits = 12 words, OS CSPRNG


async def run_migrations(database_url: str) -> bool:
    """Run SQL migrations against the database."""
    with open(SQL_PATH) as f:
        sql = f.read()

    try:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute(sql)
            return True
        finally:
            await conn.close()
    except Exception as e:
        print(f"\n  Error running migrations: {e}")
        return False


async def create_api_key(
    database_url: str, name: str, permissions: list[str]
) -> str | None:
    """Create an API key and return the plaintext key."""
    raw_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    try:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute(
                """
                INSERT INTO api_keys (key_hash, name, permissions)
                VALUES ($1, $2, $3)
                """,
                key_hash,
                name,
                permissions,
            )
            return raw_key
        finally:
            await conn.close()
    except Exception as e:
        print(f"\n  Error creating API key: {e}")
        return None


def prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt for input with optional default. Uses getpass for secrets."""
    get_input = getpass.getpass if secret else input
    if default:
        result = get_input(f"  {label} [{default}]: ").strip()
        return result or default
    while True:
        result = get_input(f"  {label}: ").strip()
        if result:
            return result
        print("  (required)")


def save_env(env: dict) -> None:
    """Write env dict to .env file atomically with 0o600 permissions."""
    content = "".join(f'{k}="{v}"\n' for k, v in env.items())
    fd = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)


def save_cli_config(url: str, api_key: str) -> None:
    """Save URL and API key to CLI config so `glow` commands work immediately."""
    config_dir = os.path.expanduser("~/.config/glow-cloud")
    config_path = os.path.join(config_dir, "config.json")
    os.makedirs(config_dir, mode=0o700, exist_ok=True)
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    if url:
        config["url"] = url
    if api_key:
        config["key"] = api_key
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


async def main():
    parser = argparse.ArgumentParser(description="glow-cloud setup wizard")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts, use env vars or defaults",
    )
    args = parser.parse_args()

    print()
    print("  ⚡ glow-cloud setup")
    print("  ───────────────────")
    print()

    # Load existing .env values
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k] = v.strip('"')

    from mnemonic import Mnemonic
    import re

    m = Mnemonic("english")

    # Step 1: Mnemonic
    print("  1. Wallet mnemonic")
    print()
    existing_mnemonic = env.get("MNEMONIC", "")

    if existing_mnemonic and m.check(existing_mnemonic):
        mnemonic = existing_mnemonic
        print("  Using existing mnemonic from .env.")
    else:
        existing = input("  Do you have an existing mnemonic? [y/N]: ").strip().lower()
        if existing == "y":
            while True:
                mnemonic = prompt("Enter mnemonic (12 or 24 words)", secret=True)
                if m.check(mnemonic):
                    print("  Mnemonic valid.")
                    break
                print("  Invalid mnemonic. Check spelling and word count.")
        else:
            print("  Generating new 12-word mnemonic...\n")
            mnemonic = generate_mnemonic()
            words = mnemonic.split()
            for i in range(0, len(words), 4):
                row = "  ".join(f"{i+j+1:2}. {words[i+j]:<12}" for j in range(4) if i + j < len(words))
                print(f"  {row}")
            print(f"\n  WRITE THIS DOWN and store it safely.")
            print(f"  This is your wallet backup.\n")
            input("  Press Enter to continue...")
            print("\033[2J\033[3J\033[H", end="", flush=True)
            print("  (Mnemonic cleared from screen. Ensure you saved it.)")

    env["MNEMONIC"] = mnemonic
    save_env(env)
    print()

    # Step 2: Breez API key
    print("  2. Breez API key")
    print()
    existing_breez = env.get("BREEZ_API_KEY", "")

    if existing_breez and not existing_breez.startswith("PENDING"):
        breez_api_key = existing_breez
        print("  Using existing Breez API key from .env.")
    else:
        has_breez_key = input("  Do you have a Breez API key? [y/N]: ").strip().lower()
        if has_breez_key == "y":
            breez_api_key = prompt("Breez API key")
        else:
            print()
            print("  We'll request one for you. Breez will email it to you.")
            print()
            fullname = prompt("Your name")
            while True:
                email = prompt("Your email")
                if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    break
                print("  Invalid email address.")
            company = prompt("Company/project name", "glow-cloud")
            print()
            print("  Requesting Breez API key...", end=" ")
            if await request_breez_api_key(fullname, email, company):
                print("done.")
                print(f"  Check {email} for your API key (may take a few hours).")
            else:
                print("failed.")
                print("  Request manually at: https://breez.technology/request-api-key/")
            print()
            print("  Once you receive the key, enter it here (or re-run setup later).")
            breez_api_key = input("  Breez API key (or press Enter to skip): ").strip()
            if not breez_api_key:
                breez_api_key = "PENDING — replace with key from Breez email"

    env["BREEZ_API_KEY"] = breez_api_key
    save_env(env)
    print()

    # Step 3: Database (Supabase)
    print("  3. Supabase database")
    print()
    existing_db = env.get("DATABASE_URL", "")

    if existing_db and existing_db.startswith("postgres"):
        database_url = existing_db
        print("  Using existing database URL from .env.")
    else:
        has_db = input("  Do you already have a database URL? [y/N]: ").strip().lower()
        if has_db == "y":
            database_url = prompt("Database URL")
        else:
            print()
            print("  We can create a Supabase project for you automatically.")
            print("  You need a Supabase access token:")
            print("    1. Sign up / log in at https://supabase.com")
            print("    2. Go to https://supabase.com/dashboard/account/tokens")
            print("    3. Create a token and paste it here")
            print()
            supabase_token = prompt("Supabase access token")
            if not supabase_token.startswith("sbp_"):
                print("  Warning: Supabase tokens usually start with 'sbp_'.")
            print()
            database_url = provision_supabase(supabase_token)
            del supabase_token
            if not database_url:
                print("  Automatic setup failed. Enter the URL manually.")
                print("  Find it in: Supabase Dashboard → Settings → Database → Connection string")
                print()
                database_url = prompt("Database URL")

    env["DATABASE_URL"] = database_url
    save_env(env)
    print()

    # Step 4: Network
    print("  4. Network")
    network = env.get("NETWORK") or prompt("Network (mainnet/regtest)", "mainnet")
    if network:
        print(f"  Network: {network}")

    env["NETWORK"] = network
    save_env(env)
    print()

    # Step 5: Run migrations
    print("  5. Run migrations")
    print()
    print("  Running database migrations...", end=" ")
    if await run_migrations(database_url):
        print("done.")
    else:
        print("failed. Run manually: psql $DATABASE_URL -f sql/001_init.sql")
        return
    print()

    # Step 6: Create first API key
    print("  6. Create API key")
    print()
    print("  Creating API key...", end=" ")
    key = await create_api_key(database_url, "default", ["balance", "receive", "send", "admin"])
    if key:
        print("done.")
        print()
        print(f"  API key: {key}")
        print()
        print(f"  Save this — it cannot be retrieved again.")
        print()
        print(f"  This is an admin key — no budget limits, full permissions.")
        print(f"  To create scoped keys for apps/services:")
        print(f"    glow keys create myapp --permissions balance receive --budget 10000 --period daily")
        print(f"    glow keys list")
    else:
        print("failed. Create one manually: glow keys create default")
    print()

    # Step 7: Deploy
    print("  7. Deploy to Vercel")
    print()
    deploy = input("  Deploy to Vercel now? [Y/n]: ").strip().lower()
    if deploy != "n":
        # Install Node.js if needed (via nvm)
        if not shutil.which("npm"):
            print("  Installing Node.js...", end=" ", flush=True)
            nvm_dir = os.path.expanduser("~/.nvm")
            if not os.path.exists(os.path.join(nvm_dir, "nvm.sh")):
                result = subprocess.run(
                    ["sh", "-c", "curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    print("failed.")
                    print("  Install Node.js manually: https://nodejs.org")
                    return
            # Install latest LTS and get its bin path
            nvm_run = f'export NVM_DIR="{nvm_dir}" && . "$NVM_DIR/nvm.sh" && nvm install --lts && nvm which current'
            result = subprocess.run(
                ["bash", "-c", nvm_run], capture_output=True, text=True,
            )
            if result.returncode != 0:
                print("failed.")
                print(f"  {result.stderr.strip()}")
                print("  Install Node.js manually: https://nodejs.org")
                return
            node_bin = os.path.dirname(result.stdout.strip().split("\n")[-1])
            os.environ["PATH"] = f"{node_bin}:{os.environ['PATH']}"
            print("done.")

        # Install Vercel CLI if needed
        if not shutil.which("vercel"):
            print("  Installing Vercel CLI...", end=" ", flush=True)
            result = subprocess.run(
                ["npm", "i", "-g", "vercel"], capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"failed. {result.stderr.strip()}")
                return
            print("done.")

        # Log in to Vercel if needed
        result = subprocess.run(
            ["vercel", "whoami"], capture_output=True, text=True
        )
        if result.returncode != 0:
            print("  Logging in to Vercel...\n")
            subprocess.run(["vercel", "login"])
            print()

        # Link project (auto-creates on Vercel if needed)
        print("  Linking project...\n")
        subprocess.run(["vercel", "link"], cwd=PROJECT_DIR)
        print()

        # Push env vars to Vercel (remove first to handle re-runs)
        print("  Setting environment variables...", end=" ", flush=True)
        for var in ["MNEMONIC", "BREEZ_API_KEY", "DATABASE_URL", "NETWORK"]:
            val = env.get(var, "")
            if val and not val.startswith("PENDING"):
                subprocess.run(
                    ["vercel", "env", "rm", var, "production", "-y"],
                    capture_output=True, text=True, cwd=PROJECT_DIR,
                )
                subprocess.run(
                    ["vercel", "env", "add", var, "production"],
                    input=val, capture_output=True, text=True, cwd=PROJECT_DIR,
                )
        print("done.")
        print()

        # Deploy to production
        print("  Deploying to production...\n")
        result = subprocess.run(
            ["vercel", "deploy", "--prod"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            url = result.stdout.strip().split("\n")[-1]
            print(f"  Deployed to: {url}")
            print()
            # Save CLI config so `glow` commands work immediately
            if key:
                save_cli_config(url, key)
            print("  Testing health endpoint...", end=" ", flush=True)
            # Give it a moment for cold start
            time.sleep(3)
            glow_bin = os.path.join(PROJECT_DIR, ".venv", "bin", "glow")
            test_result = subprocess.run(
                [glow_bin, "health"],
                capture_output=True,
                text=True,
            )
            if test_result.returncode == 0:
                print("done.")
                print(f"  {test_result.stdout.strip()}")
            else:
                print("failed.")
                print(f"  {test_result.stderr.strip()}")
            print()
            print("  Try it out:")
            print(f"    glow balance")
            print(f"    glow receive --amount 1000")
        else:
            print("  Deploy failed.")
            print(f"  {result.stderr.strip()}")
            print("  Try manually: vercel deploy --prod")
    else:
        print("  Skipping deploy. To deploy later:")
        print("    glow setup")
        print()
        print("  Or run locally:")
        print("    uv run uvicorn src.index:app --reload")
        if key:
            save_cli_config("http://localhost:8000", key)
            print()
            print("  Test it:")
            print("    glow health")

    print()
    print("  ✓ Setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
