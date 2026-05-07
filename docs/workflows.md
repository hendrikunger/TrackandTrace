# Station Workflows

Station workflow configuration describes what the kiosk should do for a station. It is separate from
device integration.

## Fields

- `workflow_type`: stable identifier for the station process.
- `workflow_title`: optional station-specific title shown in the kiosk.
- `workflow_config`: JSON object reserved for UI/process behavior. It is shown as read-only
  information in the admin UI; process-specific settings should get dedicated UI fields before
  operators or admins need to change them.
- `adapter_config`: hardware and companion adapter behavior only.
- `measurement_type_codes`: measurement allowlist for `measurement_capture` stations.

Initial workflow identifiers:

- `measurement_capture`
- `label_printing`
- `laser_marking`

## Measurement Stations

Breite and Fertig stations should use `workflow_type="measurement_capture"`. The visible kiosk title
can be set explicitly with `workflow_title`, so multiple stations of the same workflow can show
operator-friendly names without relying on station name heuristics.

Measurement capture stations continue to use:

- `measurement_type_codes` for allowed measurement values.
- `adapter_config` for SMB, serial, TCP, or scanner integration.

The companion only starts the measurement-request loop and measurement/scanner adapters when
`workflow_type="measurement_capture"`. This keeps the current measuring behavior unchanged while
making the workflow type the first runtime switch for future processes.

## Non-Measurement Stations

Non-measurement workflows do not need fake measurement types. For example:

```json
{
  "name": "LASER-01",
  "workflow_type": "laser_marking",
  "workflow_title": "Laser markieren",
  "workflow_config": {
    "requires_operator_ack": true
  },
  "measurement_type_codes": []
}
```

The kiosk can resolve this station from `/kiosk?station_id=<id>` or `STATION_ID` and render the
workflow title even when no measurement types are assigned.

The companion currently treats non-measurement workflows as no-op station runtimes. It still sends
heartbeats, but it does not run measurement adapters or poll for measurement requests until a
workflow-specific runtime is implemented.

## Migration Path

Existing stations are migrated with `workflow_type="measurement_capture"` and empty workflow
configuration. After migration:

1. Assign `workflow_title` for existing stations such as `Breite messen` and `Fertig messen`.
2. Keep measurement assignments for measuring stations.
3. Add dedicated UI fields for process-specific settings instead of requiring manual JSON edits.
4. Keep hardware connection settings in `adapter_config`.
5. For label or laser stations, set `workflow_type` accordingly and leave measurement types empty.
