from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path

from slf_trace.config import Settings, get_settings


def configure_process_logging(
    log_path: str | None,
    *,
    max_bytes: int,
    backup_count: int,
) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_path:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        )

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def configure_api_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_process_logging(
        settings.api_log_path,
        max_bytes=settings.server_log_max_bytes,
        backup_count=settings.server_log_backup_count,
    )


def run_with_rotating_output_log(
    command: Sequence[str],
    *,
    log_path: str | None,
    max_bytes: int,
    backup_count: int,
) -> int:
    logger = logging.getLogger("slf_trace.process")
    configure_process_logging(log_path, max_bytes=max_bytes, backup_count=backup_count)
    logger.info("Starting process: %s", subprocess.list2cmdline(list(command)))

    process = subprocess.Popen(  # noqa: S603 - command is built from local executable paths.
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        clean_line = line.rstrip()
        if clean_line:
            logger.info("%s", clean_line)
            print(clean_line, flush=True)

    return_code = process.wait()
    logger.info("Process exited with code %s", return_code)
    return return_code
