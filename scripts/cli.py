"""
glow-cloud CLI.

Usage: glow <command>

Commands:
  config set-url <url>       Save API URL
  config set-key <key>       Save API key
  config show                Show current config (key masked)
  health                     Check API health
  balance                    Show wallet balance
  receive                    Create a Lightning invoice
  send <destination>         Send a Lightning payment
  keys create <name>         Create a new API key (admin)
  keys list                  List all API keys (admin)
  keys revoke <key_id>       Revoke an API key (admin)
  setup                      Run the setup wizard
"""

import argparse
import json
import os
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CONFIG_DIR = os.path.expanduser("~/.config/glow-cloud")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config() -> dict:
    """Load config from file, overlay env vars and CLI flags."""
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
    # Env vars override file
    if os.environ.get("GLOW_CLOUD_URL"):
        config["url"] = os.environ["GLOW_CLOUD_URL"]
    if os.environ.get("GLOW_CLOUD_KEY"):
        config["key"] = os.environ["GLOW_CLOUD_KEY"]
    return config


def save_config(data: dict) -> None:
    """Write config to file with 0o600 permissions."""
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def api_request(config: dict, method: str, path: str, body: dict | None = None) -> dict:
    """Make an API request. Returns parsed JSON or exits on error."""
    url = config.get("url")
    if not url:
        print("Error: No API URL configured.")
        print("Run: glow config set-url <url>")
        sys.exit(1)

    key = config.get("key")
    full_url = f"{url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = Request(full_url, data=data, method=method)
    if key:
        req.add_header("X-API-Key", key)
    if data:
        req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        err_body = e.read().decode(errors="replace")
        try:
            detail = json.loads(err_body).get("detail", err_body)
        except (json.JSONDecodeError, AttributeError):
            detail = err_body.split("\n")[0].strip()
        if e.code == 401:
            print("Error: Invalid API key.")
        else:
            print(f"Error: HTTP {e.code} — {detail}")
        sys.exit(1)
    except URLError as e:
        print(f"Error: Could not reach {url} ({e.reason})")
        sys.exit(1)


def cmd_config(args, config: dict) -> None:
    action = args.config_action
    if not action:
        print("Usage: glow config {set-url,set-key,show}")
        sys.exit(1)
    if action == "set-url":
        config["url"] = args.value
        save_config(config)
        print(f"URL saved: {args.value}")
    elif action == "set-key":
        config["key"] = args.value
        save_config(config)
        print("API key saved.")
    elif action == "show":
        url = config.get("url", "(not set)")
        key = config.get("key", "")
        masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("(set)" if key else "(not set)")
        print(f"URL: {url}")
        print(f"Key: {masked}")
        print(f"Config: {CONFIG_PATH}")


def cmd_health(args, config: dict) -> None:
    data = api_request(config, "GET", "/health")
    sdk = "ready" if data.get("sdk_initialized") else "not initialized"
    print(f"{data.get('status', 'ok')} (sdk: {sdk})")


def cmd_balance(args, config: dict) -> None:
    data = api_request(config, "GET", "/balance")
    balance = data["balance_sats"]
    print(f"Balance: {balance:,} sats")
    pending_in = data.get("pending_incoming_sats", 0)
    pending_out = data.get("pending_outgoing_sats", 0)
    if pending_in:
        print(f"  pending incoming: {pending_in:,} sats")
    if pending_out:
        print(f"  pending outgoing: {pending_out:,} sats")


def print_qr(text: str) -> None:
    """Print a QR code to the terminal using Unicode block characters."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        # Use Unicode half-blocks: two rows per line
        rows = len(matrix)
        for r in range(0, rows, 2):
            line = ""
            for c in range(len(matrix[0])):
                top = matrix[r][c]
                bottom = matrix[r + 1][c] if r + 1 < rows else False
                if top and bottom:
                    line += "\u2588"      # full block (both dark)
                elif top:
                    line += "\u2580"      # upper half block
                elif bottom:
                    line += "\u2584"      # lower half block
                else:
                    line += " "           # both light
            print(line)
    except ImportError:
        pass  # qrcode not installed, skip


def cmd_receive(args, config: dict) -> None:
    body = {}
    if args.amount is not None:
        body["amount_sats"] = args.amount
    if args.description is not None:
        body["description"] = args.description
    data = api_request(config, "POST", "/receive", body)
    invoice = data["payment_request"]
    print_qr(invoice.upper())
    print(invoice)
    fee = data.get("fee_sats")
    if fee:
        print(f"  fee: {fee:,} sats")


def cmd_setup(args, config: dict) -> None:
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup.py")
    sys.exit(subprocess.call([sys.executable, script]))


def cmd_keys(args, config: dict) -> None:
    action = args.keys_action
    if not action:
        print("Usage: glow keys {create,list,revoke}")
        sys.exit(1)

    if action == "create":
        body = {"name": args.name}
        if args.permissions:
            body["permissions"] = args.permissions
        if args.budget is not None:
            body["budget_sats"] = args.budget
        if args.period is not None:
            body["budget_period"] = args.period
        if args.max_amount is not None:
            body["max_amount_sats"] = args.max_amount
        data = api_request(config, "POST", "/keys", body)
        print(f"\nAPI key created: {data['name']}")
        print(f"Key: {data['key']}")
        print(f"ID:  {data['id']}")
        print(f"Permissions: {', '.join(data['permissions'])}")
        if data.get("budget_sats"):
            print(f"Budget: {data['budget_sats']:,} sats / {data['budget_period']}")
        if data.get("max_amount_sats"):
            print(f"Max per tx: {data['max_amount_sats']:,} sats")
        print("\nSave this key — it cannot be retrieved again.")

    elif action == "list":
        data = api_request(config, "GET", "/keys")
        if not data:
            print("No active keys.")
            return
        # Column widths
        name_w = max(len(k["name"]) for k in data)
        name_w = max(name_w, 4)
        print(f"{'NAME':<{name_w}}  {'PERMISSIONS':<28}  {'BUDGET':<20}  {'CREATED'}")
        print(f"{'-' * name_w}  {'-' * 28}  {'-' * 20}  {'-' * 10}")
        for k in data:
            perms = ", ".join(k["permissions"])
            budget = f"{k['budget_sats']:,}/{k['budget_period']}" if k.get("budget_sats") else "-"
            created = k["created_at"][:10]
            print(f"{k['name']:<{name_w}}  {perms:<28}  {budget:<20}  {created}")

    elif action == "revoke":
        api_request(config, "DELETE", f"/keys/{args.key_id}")
        print("Key revoked.")


def cmd_sync(args, config: dict) -> None:
    data = api_request(config, "POST", "/sync")
    print(f"Synced. Balance: {data['balance_sats']:,} sats")


def cmd_send(args, config: dict) -> None:
    body = {"destination": args.destination}
    if args.amount is not None:
        body["amount_sats"] = args.amount
    data = api_request(config, "POST", "/send", body)
    amount = data.get("amount_sats", 0)
    status = data.get("status", "unknown")
    print(f"Sent {amount:,} sats (status: {status})")


def main():
    parser = argparse.ArgumentParser(prog="glow", description="glow-cloud CLI")
    parser.add_argument("--url", help="API URL (overrides config)")
    parser.add_argument("--key", help="API key (overrides config)")
    sub = parser.add_subparsers(dest="command")

    # config
    cfg = sub.add_parser("config", help="Manage CLI config")
    cfg_sub = cfg.add_subparsers(dest="config_action")
    set_url = cfg_sub.add_parser("set-url", help="Save API URL")
    set_url.add_argument("value", help="API URL")
    set_key = cfg_sub.add_parser("set-key", help="Save API key")
    set_key.add_argument("value", help="API key")
    cfg_sub.add_parser("show", help="Show current config")

    # health
    sub.add_parser("health", help="Check API health")

    # balance
    sub.add_parser("balance", help="Show wallet balance")

    # receive
    recv = sub.add_parser("receive", help="Create a Lightning invoice")
    recv.add_argument("--amount", type=int, help="Amount in sats")
    recv.add_argument("--description", help="Invoice description")

    # setup
    sub.add_parser("setup", help="Run the setup wizard")

    # keys
    keys_p = sub.add_parser("keys", help="Manage API keys (admin)")
    keys_sub = keys_p.add_subparsers(dest="keys_action")
    keys_create = keys_sub.add_parser("create", help="Create a new API key")
    keys_create.add_argument("name", help="Name for the key")
    keys_create.add_argument("--permissions", nargs="+", default=None, help="Permissions (default: balance receive)")
    keys_create.add_argument("--budget", type=int, help="Budget in sats per period")
    keys_create.add_argument("--period", choices=["daily", "weekly", "monthly"], help="Budget period")
    keys_create.add_argument("--max-amount", type=int, help="Max sats per transaction")
    keys_sub.add_parser("list", help="List all API keys")
    keys_revoke = keys_sub.add_parser("revoke", help="Revoke an API key")
    keys_revoke.add_argument("key_id", help="ID of the key to revoke")

    # sync
    sub.add_parser("sync", help="Force SDK reconnect and sync (admin)")

    # send
    s = sub.add_parser("send", help="Send a Lightning payment")
    s.add_argument("destination", help="BOLT11 invoice or Lightning address")
    s.add_argument("--amount", type=int, help="Amount in sats")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = load_config()
    # CLI flags override everything
    if args.url:
        config["url"] = args.url
    if args.key:
        config["key"] = args.key

    commands = {
        "config": cmd_config,
        "setup": cmd_setup,
        "health": cmd_health,
        "balance": cmd_balance,
        "receive": cmd_receive,
        "keys": cmd_keys,
        "sync": cmd_sync,
        "send": cmd_send,
    }
    commands[args.command](args, config)


if __name__ == "__main__":
    main()
