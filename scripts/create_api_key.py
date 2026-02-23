import argparse
import asyncio
import hashlib
import os
import secrets
import base64

import asyncpg


async def main():
    parser = argparse.ArgumentParser(description="Create a glow-cloud API key")
    parser.add_argument("name", help="Name for this API key")
    parser.add_argument("--budget", type=int, help="Budget in sats per period")
    parser.add_argument(
        "--period",
        choices=["daily", "weekly", "monthly"],
        help="Budget period",
    )
    parser.add_argument("--max-amount", type=int, help="Max sats per transaction")
    parser.add_argument(
        "--permissions",
        nargs="+",
        default=["balance", "receive"],
        help="Permissions (default: balance receive)",
    )
    args = parser.parse_args()

    if args.budget and not args.period:
        parser.error("--period is required when --budget is set")

    raw_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            """
            INSERT INTO api_keys (key_hash, name, max_amount_sats, budget_sats, budget_period, permissions)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            key_hash,
            args.name,
            args.max_amount,
            args.budget,
            args.period,
            args.permissions,
        )
    finally:
        await conn.close()

    print(f"\nAPI key created: {args.name}")
    print(f"Key: {raw_key}")
    print(f"Permissions: {', '.join(args.permissions)}")
    if args.budget:
        print(f"Budget: {args.budget} sats / {args.period}")
    if args.max_amount:
        print(f"Max per tx: {args.max_amount} sats")
    print("\nSave this key — it cannot be retrieved again.")


if __name__ == "__main__":
    asyncio.run(main())
