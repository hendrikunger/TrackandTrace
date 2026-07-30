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
- `measurement_type_codes`: fallback/manual measurement allowlist for `measurement_capture`
  stations when enabled adapters do not declare their own `measurement_type`.

Initial workflow identifiers:

- `measurement_capture`
- `label_printing`
- `laser_marking`

## Measurement Stations

Breite and Fertig stations should use `workflow_type="measurement_capture"`. The visible kiosk title
can be set explicitly with `workflow_title`, so multiple stations of the same workflow can show
operator-friendly names without relying on station name heuristics.

Measurement capture stations continue to use:

- `adapter_config` for SMB, serial, TCP, or scanner integration. Enabled adapter
  `measurement_type` fields normally define the effective measurement assignment.
- `measurement_type_codes` only as the fallback/manual allowlist when no enabled adapter declares a
  measurement type.

The companion only starts the measurement-request loop and measurement/scanner adapters when
`workflow_type="measurement_capture"`. This keeps the current measuring behavior unchanged while
making the workflow type the first runtime switch for future processes.

## Laser Marking Stations

Non-measurement workflows do not need fake measurement types. For example:

```json
{
  "name": "LASER-01",
  "workflow_type": "laser_marking",
  "workflow_title": "Laser markieren",
  "workflow_config": {
    "laser_output": {
      "path": "/mnt/laser-share",
      "filename_template": "{rueckmeldenummer}.txt",
      "encoding": "utf-8"
    }
  },
  "measurement_type_codes": []
}
```

The kiosk can resolve this station from `/kiosk?station_id=<id>` or `STATION_ID` and render the
workflow title even when no measurement types are assigned.

Laser marking stations can use the Keyence scanner fields. After a scan, the kiosk and companion
load the latest stored measurement value for each measurement type on the scanned part. The
companion writes a text file with alternating measurement type and value lines in stable
measurement type code order, then overwrites an existing file with the same name.

## Label Printing Stations

Label printing stations also do not need fake measurement types. They use the scanner to select the
part and an explicit kiosk print request to prevent accidental duplicate labels.

```json
{
  "name": "LABEL-01",
  "workflow_type": "label_printing",
  "workflow_title": "Etikett drucken",
  "workflow_config": {
    "label_printing": {
      "template_dir": "C:\\SLF\\TrackTrace\\labels",
      "selected_template": "SLF_81x36_.prn",
      "encoding": "cp1252",
      "print_backend": "win32print",
      "printer_name": "Vario III 107/12",
      "tcp_host": "",
      "tcp_port": 9100,
      "require_confirmation": false,
      "replacements": [
        {
          "measurement_type": "breite",
          "search": "BM[15]-283",
          "replace": "BM[15]{{value}}",
          "value_format": "comma",
          "missing_value_behavior": "block"
        }
      ]
    }
  },
  "adapter_config": [],
  "measurement_type_codes": []
}
```

The admin UI has dedicated fields for the template directory, selected `.prn` file, encoding,
printer backend, Windows printer name, raw TCP fallback, confirmation mode, and replacement rules.
The station heartbeat reports available `.prn` files from the configured template directory so the
admin can select a template without editing JSON.

Replacement rules search literal text in the printer file and replace it with configured text.
Replacement text can use these tokens:

- `{{value}}`: the selected measurement value using the rule's configured format
- `{{value_comma}}`: decimal comma format
- `{{value_dot}}`: decimal dot format
- `{{value_raw}}`: database decimal string
- `{{unit}}`: measurement unit
- `{{rueckmeldenummer}}`: scanned part id

Missing measurement values default to `Drucken blockieren`. A rule can instead use
`Warnen, Drucken erlauben`; then the kiosk warns the operator and allows a manual print anyway,
using one blank space for the missing value.

## Migration Path

Existing stations are migrated with `workflow_type="measurement_capture"` and empty workflow
configuration. After migration:

1. Assign `workflow_title` for existing stations such as `Breite messen` and `Fertig messen`.
2. Keep measurement assignments on enabled adapter `measurement_type` fields where possible.
3. Add dedicated UI fields for process-specific settings instead of requiring manual JSON edits.
4. Keep hardware connection settings in `adapter_config`.
5. For label or laser stations, set `workflow_type` accordingly and leave measurement types empty.
