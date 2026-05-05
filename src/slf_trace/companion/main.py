import asyncio
import signal

from slf_trace.companion.runtime import (
    CompanionRuntime,
    config_from_settings,
    configure_logging,
)


async def async_main() -> None:
    config = config_from_settings()
    configure_logging()
    runtime = CompanionRuntime(config)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    runtime_task = asyncio.create_task(runtime.run_forever())
    stop_task = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {runtime_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stop_task in done:
        await runtime.stop_adapters()
        runtime_task.cancel()

    try:
        await runtime_task
    except asyncio.CancelledError:
        return


def run() -> None:
    asyncio.run(async_main())
