# Live Events

Browser clients can subscribe to live station updates over WebSocket:

```text
ws://<server>/api/live/events
```

The first implementation uses an in-process event hub. It is enough for local development and a
single central server process. If the deployment later uses multiple worker processes, this should
move to a shared pub/sub backend.

Delivery is best-effort. A stale or failing browser connection is dropped from the hub and does not
fail the companion API request that produced the event.

## Event Shape

```json
{
  "type": "measurement.captured",
  "station_id": 1,
  "payload": {
    "measurement_id": 10
  }
}
```

## Published Events

- `station.heartbeat`
- `barcode.scan`
- `raw_payload.received`
- `measurement.captured`
