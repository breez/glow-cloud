import asyncio
import logging
import os

from breez_sdk_spark import (
    Network,
    SdkBuilder,
    Seed,
    default_config,
    default_postgres_storage_config,
    init_logging,
)
from breez_sdk_spark.breez_sdk_spark import uniffi_set_event_loop

logger = logging.getLogger(__name__)

_sdk = None
_lock = asyncio.Lock()


class _SdkLogger:
    def log(self, entry):
        logger.info("SDK: %s", entry)


class _SdkEventListener:
    async def on_event(self, event):
        logger.info("SDK event: %s", event)


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
        pg_config.max_pool_size = 2

        loop = asyncio.get_running_loop()
        uniffi_set_event_loop(loop)

        try:
            init_logging(log_dir=None, app_logger=_SdkLogger(), log_filter=None)
        except Exception:
            pass  # may already be initialized

        builder = SdkBuilder(config=config, seed=seed)
        await builder.with_postgres_storage(config=pg_config)
        _sdk = await builder.build()
        await _sdk.add_event_listener(listener=_SdkEventListener())
        return _sdk


async def disconnect_sdk() -> None:
    global _sdk
    if _sdk is not None:
        try:
            await asyncio.wait_for(_sdk.disconnect(), timeout=5)
        except (asyncio.TimeoutError, Exception):
            pass  # disconnect may hang due to dead background tasks (#662)
        _sdk = None


def is_sdk_initialized() -> bool:
    return _sdk is not None
