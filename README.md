# Measuring Station Dashboard Platform

Central browser-based dashboard and measurement capture platform for production measuring stations.

## Goal

The system captures barcode scans and measurement results for individual physical parts, stores them centrally, and gives operators a station UI that can run unattended in kiosk mode.

## Core Decisions

- Python-first stack.
- FastAPI owns APIs, ingestion, validation, WebSockets, auth, and business logic.
- Panel/HoloViz provides the operator, supervisor, and admin UI.
- PostgreSQL is the central database.
- Every measuring station runs a Python companion app.
- Browsers are used for UI only, not as the universal hardware interface layer.
- Windows 11 and Ubuntu 24.04 LTS stations boot into kiosk mode.

## Domain Model

- `rueckmeldenummer` identifies one individual physical part.
- A station represents the physical measuring workplace and its attached measuring machine.
- Measurement fields use ASCII names in code and German labels in the UI:

| Code / DB field | UI label |
| --- | --- |
| `aussenring` | Außenring |
| `innenring` | Innenring |
| `breite` | Breite |
| `ueberstand` | Überstand |

## Development Status

This repository is currently in project setup. See `docs/architecture.md` for the implementation plan.
