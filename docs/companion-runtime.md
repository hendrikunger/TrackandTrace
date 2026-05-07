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
COMPANION_MEASUREMENT_AGGREGATION_TIMEOUT_SECONDS=300
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
- writes rotating companion logs to `COMPANION_LOG_PATH` when configured
- can submit diagnostics events to `/api/companion/events`

The companion should survive normal outage and configuration-failure conditions without process
exits. During startup it retries station config bootstrap until the API responds. After bootstrap,
heartbeat failures, measurement-request poll failures, startup heartbeat failures, and outbox send
failures are logged and retried instead of escaping the runtime loop. This prevents service restart
churn while the API VM is restarted or a network path drops.

Adapter configuration is also guarded. If station config or environment variables are invalid, the
runtime queues `adapter.configuration_failed`, sends degraded heartbeats, and keeps the outbox/API
polling loops alive instead of repeatedly restarting the companion.

Adapter tasks are supervised separately. If one TCP, SMB, scanner, serial, or repeating simulator
adapter raises unexpectedly, the runtime queues `adapter.failure` and restarts that adapter without
stopping other adapters or the companion process. One-shot simulator adapters are allowed to finish
once; the runtime stays alive and does not re-emit their measurement forever.

## Measurement Requests

Barcode scans create measurement requests in the central API. The companion polls those requests and
opens one active collection window per Rückmeldenummer.

Adapters without their own `rueckmeldenummer` only read while a collection window is active. When a
station has several assigned measurement types, the runtime waits until all expected types have been
emitted by the station adapters, then submits one combined measurement. For example, a station
assigned `breite` and `ueberstand` can receive one value from a TCP adapter and one value from an SMB
adapter and store them under the same Rückmeldenummer.

If the window reaches `COMPANION_MEASUREMENT_AGGREGATION_TIMEOUT_SECONDS` after at least one value
has arrived, the companion submits the values it has and queues a `measurement.partial` diagnostic
event listing the missing measurement types. If no value has arrived yet, the request stays open so
polling adapters such as SMB can keep waiting for the device file. A station with one expected
measurement type still behaves like the current simple stations: the first valid adapter value
completes the request immediately.

Log rotation is controlled by:

- `COMPANION_LOG_PATH` (default `logs/slf-trace-companion.log`)
- `COMPANION_LOG_MAX_BYTES` (default `5000000`)
- `COMPANION_LOG_BACKUP_COUNT` (default `5`)

## Outbox

The outbox is a SQLite database at `COMPANION_STATE_PATH`. It stores:

- endpoint
- JSON payload
- attempt count
- created timestamp
- last attempt timestamp

Adapter implementations should enqueue retryable events instead of dropping them when the network
or central API is unavailable.

Adapter implementations should still catch expected device failures locally and report degraded
health. The runtime supervisor is the final safety boundary for unexpected exceptions.
