import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OutboxEvent:
    id: int
    endpoint: str
    payload: dict[str, Any]
    attempts: int


class Outbox:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists outbox_events (
                    id integer primary key autoincrement,
                    endpoint text not null,
                    payload text not null,
                    attempts integer not null default 0,
                    created_at text not null default current_timestamp,
                    last_attempt_at text
                )
                """
            )

    def enqueue(self, endpoint: str, payload: dict[str, Any]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "insert into outbox_events (endpoint, payload) values (?, ?)",
                (endpoint, json.dumps(payload, sort_keys=True)),
            )
            return int(cursor.lastrowid)

    def pending(self, limit: int = 50) -> list[OutboxEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select id, endpoint, payload, attempts
                from outbox_events
                order by id
                limit ?
                """,
                (limit,),
            ).fetchall()

        return [
            OutboxEvent(
                id=int(row["id"]),
                endpoint=str(row["endpoint"]),
                payload=json.loads(str(row["payload"])),
                attempts=int(row["attempts"]),
            )
            for row in rows
        ]

    def mark_attempt(self, event_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update outbox_events
                set attempts = attempts + 1,
                    last_attempt_at = current_timestamp
                where id = ?
                """,
                (event_id,),
            )

    def delete(self, event_id: int) -> None:
        with self._connect() as connection:
            connection.execute("delete from outbox_events where id = ?", (event_id,))

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("select count(*) as count from outbox_events").fetchone()
        return int(row["count"])

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
