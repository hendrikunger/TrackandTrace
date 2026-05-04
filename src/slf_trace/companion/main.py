import asyncio

from slf_trace.companion.runtime import (
    CompanionRuntime,
    config_from_settings,
    configure_logging,
)


async def async_main() -> None:
    config = config_from_settings()
    configure_logging()
    runtime = CompanionRuntime(config)
    await runtime.run_forever()


def run() -> None:
    asyncio.run(async_main())
