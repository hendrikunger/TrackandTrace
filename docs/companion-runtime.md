# Companion Runtime

The station companion is the local process that runs beside each measuring station.

## Configuration

Set these values in `.env` or the service environment:

```env
STATION_ID=1
SERVER_URL=http://localhost:8000
COMPANION_STATE_PATH=companion_state.sqlite3
COMPANION_HEARTBEAT_INTERVAL_SECONDS=10
COMPANION_OUTBOX_RETRY_INTERVAL_SECONDS=2
```

## Run

```bash
mamba activate slf_trace
slf-trace-companion
```

The runtime:

- fetches station config from `/api/companion/stations/{station_id}/config`
- builds configured station adapters from the returned `adapters` list
- sends heartbeats to `/api/companion/heartbeats`
- stores retryable outgoing events in a local SQLite outbox
- retries outbox events until the central API accepts them
- logs startup, heartbeat, outbox success, and outbox failure events

## Outbox

The outbox is a SQLite database at `COMPANION_STATE_PATH`. It stores:

- endpoint
- JSON payload
- attempt count
- created timestamp
- last attempt timestamp

Adapter implementations should enqueue retryable events instead of dropping them when the network
or central API is unavailable.
