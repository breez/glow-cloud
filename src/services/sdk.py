import asyncio
import os

from breez_sdk_spark import (
    Network,
    SdkBuilder,
    Seed,
    default_config,
    default_postgres_storage_config,
    create_postgres_storage,
)

_sdk = None
_lock = asyncio.Lock()


def _get_network() -> Network:
    network = os.environ.get("NETWORK", "mainnet").lower()
    if network == "regtest":
        return Network.REGTEST
    return Network.MAINNET


async def get_sdk():
    global _sdk
    if _sdk is not None:
        return _sdk

    async with _lock:
        if _sdk is not None:
            return _sdk

        mnemonic = os.environ["MNEMONIC"]
        seed = Seed.MNEMONIC(mnemonic=mnemonic, passphrase=None)

        config = default_config(network=_get_network())
        config.api_key = os.environ["BREEZ_API_KEY"]

        pg_config = default_postgres_storage_config(
            connection_string=os.environ["DATABASE_URL"],
        )
        storage = await create_postgres_storage(config=pg_config)

        builder = SdkBuilder(config=config, seed=seed)
        await builder.with_storage(storage=storage)
        _sdk = await builder.build()
        return _sdk


async def disconnect_sdk() -> None:
    global _sdk
    if _sdk is not None:
        await _sdk.disconnect()
        _sdk = None


def is_sdk_initialized() -> bool:
    return _sdk is not None
