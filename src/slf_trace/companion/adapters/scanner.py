import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from slf_trace.companion.adapters.base import (
    AdapterContext,
    AdapterState,
    AdapterStatus,
    BarcodeScanEvent,
    MeasurementAdapter,
)


@dataclass(frozen=True)
class TcpBarcodeScannerAdapterConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 9004
    allowed_peer_host: str | None = None
    name: str = "keyence-srx-scanner"
    source_type: str = "keyence_srx"
    encoding: str = "utf-8"
    reconnect_delay_seconds: float = 2.0
    heartbeat_timeout_seconds: float = 90.0
    heartbeat_check_interval_seconds: float = 5.0
    startup_command: str | None = "LON"
    shutdown_command: str | None = "LOFF"
    command_terminator: str = "\r"


class TcpBarcodeScannerAdapter(MeasurementAdapter):
    def __init__(self, config: TcpBarcodeScannerAdapterConfig) -> None:
        self.config = config
        self.name = config.name
        self._stop_event = asyncio.Event()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)
        self._server: asyncio.AbstractServer | None = None
        self._started_at: datetime | None = None
        self._last_heartbeat_at: datetime | None = None
        self._client_writers: list[asyncio.StreamWriter] = []
        self._working_mode_writers: set[asyncio.StreamWriter] = set()

    async def start(self, context: AdapterContext) -> None:
        self._stop_event.clear()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STARTING)
        self._started_at = datetime.now(UTC)

        while not self._stop_event.is_set():
            try:
                await self._run_server(context)
            except OSError as exc:
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.DEGRADED,
                    last_error=str(exc),
                )
            await self._sleep_until_retry()

        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def stop(self) -> None:
        self._stop_event.set()
        for writer in list(self._client_writers):
            await self._send_shutdown_command(writer)
            writer.close()
        if self._server is not None:
            self._server.close()

    def health(self) -> AdapterStatus:
        return self._status

    async def _run_server(self, context: AdapterContext) -> None:
        if context.emit_barcode_scan is None:
            raise RuntimeError("Barcode scanner adapters require emit_barcode_scan in context.")

        server = await asyncio.start_server(
            lambda reader, writer: self._handle_client(context, reader, writer),
            host=self.config.listen_host,
            port=self.config.listen_port,
        )
        self._server = server
        self._status = AdapterStatus(
            name=self.name,
            state=AdapterState.ONLINE,
            message=f"Listening on {self.config.listen_host}:{self.config.listen_port}",
        )

        watchdog_task = asyncio.create_task(self._heartbeat_watchdog())
        serve_task = asyncio.create_task(server.serve_forever())
        try:
            await self._stop_event.wait()
        finally:
            server.close()
            for writer in list(self._client_writers):
                writer.close()
            serve_task.cancel()
            watchdog_task.cancel()
            await self._await_cancelled(serve_task)
            await self._await_cancelled(watchdog_task)
            await server.wait_closed()
            self._server = None

    async def _handle_client(
        self,
        context: AdapterContext,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_host = peer[0] if isinstance(peer, tuple) and peer else None
        peer_port = peer[1] if isinstance(peer, tuple) and len(peer) > 1 else None
        self._client_writers.append(writer)

        try:
            if (
                self.config.allowed_peer_host is not None
                and peer_host != self.config.allowed_peer_host
            ):
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.DEGRADED,
                    message=(
                        f"Rejected scanner connection from {peer_host or 'unknown'};"
                        f" expected {self.config.allowed_peer_host}."
                    ),
                )
                return

            self._status = AdapterStatus(
                name=self.name,
                state=AdapterState.ONLINE,
                message=f"Scanner connected from {peer_host or 'unknown'}:{peer_port or '?'}",
                last_event_at=self._last_heartbeat_at,
            )
            await self._send_startup_command(writer)

            buffer = b""
            while not self._stop_event.is_set():
                chunk = await reader.read(4096)
                if not chunk:
                    break

                buffer += chunk
                frames, buffer = _extract_scanner_frames(buffer)
                for frame in frames:
                    content = frame.decode(self.config.encoding, errors="replace").strip()
                    if not content:
                        continue

                    if _is_heartbeat_message(content):
                        self._last_heartbeat_at = datetime.now(UTC)
                        self._status = AdapterStatus(
                            name=self.name,
                            state=AdapterState.ONLINE,
                            message="Scanner heartbeat received",
                            last_event_at=self._last_heartbeat_at,
                        )
                        continue

                    barcode = _extract_barcode(content)
                    if not barcode:
                        continue

                    await context.emit_barcode_scan(
                        BarcodeScanEvent(
                            station_id=context.station_id,
                            source_type=self.config.source_type,
                            rueckmeldenummer=barcode,
                            scanned_at=datetime.now(UTC),
                            raw_payload=content,
                        )
                    )
                    now = datetime.now(UTC)
                    self._status = AdapterStatus(
                        name=self.name,
                        state=AdapterState.ONLINE,
                        message=f"Barcode scan received: {barcode}",
                        last_event_at=now,
                    )
        finally:
            await self._send_shutdown_command(writer)
            if writer in self._client_writers:
                self._client_writers.remove(writer)
            writer.close()
            await writer.wait_closed()

    async def _heartbeat_watchdog(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self.config.heartbeat_check_interval_seconds)
            if self._started_at is None:
                continue

            reference_time = self._last_heartbeat_at or self._started_at
            if (
                datetime.now(UTC) - reference_time
            ).total_seconds() > self.config.heartbeat_timeout_seconds:
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.DEGRADED,
                    message="Scanner heartbeat overdue",
                    last_error="No scanner heartbeat received within the expected window.",
                    last_event_at=reference_time,
                )

    async def _sleep_until_retry(self) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self.config.reconnect_delay_seconds,
            )
        except TimeoutError:
            return

    async def _await_cancelled(self, task: asyncio.Task[Any]) -> None:
        try:
            await task
        except asyncio.CancelledError:
            return

    async def _send_startup_command(self, writer: asyncio.StreamWriter) -> None:
        if self.config.startup_command is None:
            return
        await self._write_command(writer, self.config.startup_command)
        self._working_mode_writers.add(writer)

    async def _send_shutdown_command(self, writer: asyncio.StreamWriter) -> None:
        if writer not in self._working_mode_writers:
            return
        self._working_mode_writers.discard(writer)
        if self.config.shutdown_command is None:
            return
        await self._write_command(writer, self.config.shutdown_command)

    async def _write_command(self, writer: asyncio.StreamWriter, command: str) -> None:
        payload = f"{command}{self.config.command_terminator}".encode(
            self.config.encoding,
            errors="replace",
        )
        try:
            writer.write(payload)
            await writer.drain()
        except (ConnectionError, OSError):
            return


def _is_heartbeat_message(content: str) -> bool:
    normalized = content.strip().lower()
    return normalized in {"hb", "heartbeat", "keepalive", "alive"} or normalized.startswith(
        ("hb ", "hb:", "hb=", "heartbeat ", "heartbeat:", "heartbeat=")
    )


def _extract_scanner_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    frames: list[bytes] = []
    remaining = buffer
    while remaining:
        delimiter_positions = [
            position
            for position in (remaining.find(b"\r"), remaining.find(b"\n"))
            if position >= 0
        ]
        if not delimiter_positions:
            return frames, remaining

        delimiter_position = min(delimiter_positions)
        frame = remaining[:delimiter_position]
        remaining = remaining[delimiter_position:]
        remaining = remaining.lstrip(b"\r\n")
        if frame:
            frames.append(frame)

    return frames, b""


def _extract_barcode(content: str) -> str:
    match = re.match(r"(?i)^(?:barcode|scan|code|data|value)\s*[:=]\s*(?P<barcode>.+)$", content)
    if match:
        return match.group("barcode").strip()
    return content.strip()
