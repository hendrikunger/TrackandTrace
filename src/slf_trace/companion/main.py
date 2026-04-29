import asyncio

from slf_trace.companion.runtime import (
    CompanionRuntime,
    config_from_settings,
    configure_logging,
)


async def async_main() -> None:
    configure_logging()
    runtime = CompanionRuntime(config_from_settings())
    await runtime.run_forever()


def run() -> None:
    asyncio.run(async_main())
