# Deployment Kit

This folder contains the offline deployment scaffolding for packed environment releases.

Build on online build machines:

- Windows: `deploy/scripts/build-packed-env.ps1`
- Ubuntu 24.04: `deploy/scripts/build-packed-env.sh`

Install on offline production machines:

- Windows API/database server: `deploy/install-server.ps1`
- Linux API server: `deploy/install-server.sh`
- Windows 11 station companion: `deploy/install-panel.ps1`
- Ubuntu 24.04 station companion: `deploy/install-panel.sh`

Read `docs/deployment.md` before using these scripts. The scripts are intentionally conservative:
they unpack versioned releases and point `current` at the selected release, so rollback can switch
back to the previous release directory.

Production machines still need role-specific `.env` values edited after first install.

## Hybrid Update Policy

- Online test server: use `deploy/update-test-server.sh` against the git checkout on
  `api.home.io`.
- Offline production: use versioned release bundles from `deploy/scripts/build-packed-env.ps1` or
  `deploy/scripts/build-packed-env.sh`, then install with the role-specific install script.

The test-server updater is intentionally not a production rollback system. Production releases keep
their previous release directories and use the `current` link for rollback.
