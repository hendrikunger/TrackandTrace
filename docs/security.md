# Security Model

Human user authorization is handled outside this app by Windows/domain login,
kiosk lockdown, firewall rules, and deployment policy. SLF Track and Trace only
adds machine/API controls that protect station submissions.

## Station Companion Tokens

Production deployments should set:

```env
COMPANION_AUTH_REQUIRED=true
```

Each station then needs a local token:

```env
STATION_ID=3
SERVER_URL=http://api.home.io:8000
STATION_TOKEN=<generated-token>
```

The companion sends:

```http
X-Station-ID: 3
X-Station-Token: <generated-token>
```

The API checks that the header station id matches the request station id and
that the token matches the station token hash stored centrally. The raw token is
not returned by companion config endpoints and should not be stored in source
control.

## Token Generation and Rotation

In the admin Stations page, select a station and use **Generate new station
token**. The raw token is shown once as `STATION_TOKEN=...`; copy it into the
station service environment file immediately. After refresh, only the configured
state remains visible.

Rotating a token invalidates the old station token. Update the station
environment and restart the companion service after rotation.

## Secret Storage

- Keep `.env` and service environment files out of git.
- Limit service environment file permissions to administrators and the service
  account.
- Store SMB credentials on the station as environment variables such as
  `SMB_USER` and `SMB_PASSWORD`.
- Keep station adapter JSON/database config to environment variable names, not
  raw SMB secrets.

## Admin UI Access

The app does not implement per-user roles. Admin/supervisor access must be
restricted by deployment:

- bind admin UI/API only to the intended interface or reverse proxy;
- restrict access with firewall/network rules;
- use Windows/domain login or a protected reverse proxy where required;
- prevent kiosk panels from reaching `/app` through browser lockdown or network
  policy.

## TLS

For isolated production cells, plain HTTP may be acceptable if the network is
physically/logically trusted. If traffic crosses a shared company LAN, deploy
the API/UI behind HTTPS or a TLS-terminating reverse proxy and document the
certificate source and renewal process.
