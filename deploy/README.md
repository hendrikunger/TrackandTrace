# Deployment Kit

This folder contains the offline deployment scaffolding for packed environment releases.

Build on online build machines:

- Windows: `deploy/scripts/build-packed-env.ps1`
- Ubuntu 24.04: `deploy/scripts/build-packed-env.sh`

Install on offline production machines:

- Windows API/database server: `deploy/install-server.ps1`
- Linux API server: `deploy/install-server.sh`
- Windows 11 panel station: `deploy/install-panel.ps1`
- Ubuntu 24.04 panel station: `deploy/install-panel.sh`

Read `docs/deployment.md` before using these scripts. The scripts are intentionally conservative:
they unpack versioned releases and point `current` at the selected release, so rollback can switch
back to the previous release directory.

Production machines still need role-specific `.env` values edited after first install.
