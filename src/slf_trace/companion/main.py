import asyncio
import logging
import signal
import sys
from collections.abc import Callable

from slf_trace.companion.runtime import (
    CompanionRuntime,
    config_from_settings,
    configure_logging,
)

logger = logging.getLogger(__name__)
_WINDOWS_CTRL_HANDLER: object | None = None


def install_stop_handlers(stop: Callable[[], None]) -> None:
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        loop.call_soon_threadsafe(stop)

    signals = [signal.SIGINT, signal.SIGTERM]
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signals.append(sigbreak)

    for sig in signals:
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            try:
                signal.signal(sig, lambda _signum, _frame: request_stop())
            except (OSError, ValueError):
                logger.debug("Could not install companion stop handler", extra={"signal": sig})

    if sys.platform == "win32":
        install_windows_console_handler(request_stop)


def install_windows_console_handler(request_stop: Callable[[], None]) -> None:
    global _WINDOWS_CTRL_HANDLER

    try:
        import ctypes
    except ImportError:
        return

    handled_events = {0, 1, 2, 5, 6}  # CTRL_C/BREAK/CLOSE/LOGOFF/SHUTDOWN

    def handler(ctrl_type: int) -> int:
        if ctrl_type in handled_events:
            request_stop()
            return 1
        return 0

    try:
        handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        _WINDOWS_CTRL_HANDLER = handler_type(handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_WINDOWS_CTRL_HANDLER, True)
    except Exception:  # noqa: BLE001 - ctypes failures vary by Windows host.
        logger.debug("Could not install Windows console stop handler", exc_info=True)


async def async_main() -> None:
    config = config_from_settings()
    configure_logging()
    runtime = CompanionRuntime(config)
    stop_event = asyncio.Event()
    install_stop_handlers(stop_event.set)

    runtime_task = asyncio.create_task(runtime.run_forever())
    stop_task = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {runtime_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stop_task in done:
        logger.info("Companion stop requested; shutting down adapters")
        await runtime.stop_adapters()
        await runtime.stop_scanner_runtime()
        runtime_task.cancel()

    try:
        await runtime_task
    except asyncio.CancelledError:
        return


def run() -> None:
    asyncio.run(async_main())
