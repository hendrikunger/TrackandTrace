from typing import Any
from urllib.parse import quote

import httpx


class CompanionClient:
    def __init__(
        self,
        server_url: str,
        *,
        station_id: int | None = None,
        station_token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.station_id = station_id
        self.station_token = station_token
        self.timeout_seconds = timeout_seconds

    async def fetch_station_config(self, station_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/companion/stations/{station_id}/config")

    async def fetch_measurement_request(
        self,
        station_id: int,
        after_id: int,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/companion/stations/{station_id}/measurement-request?after_id={after_id}",
        )

    async def fetch_label_print_request(
        self,
        station_id: int,
        after_id: int,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/companion/stations/{station_id}/label-print-request?after_id={after_id}",
        )

    async def fetch_part_measurement_values(
        self,
        station_id: int,
        rueckmeldenummer: str,
    ) -> dict[str, Any]:
        encoded_rueckmeldenummer = quote(rueckmeldenummer, safe="")
        return await self._request(
            "GET",
            f"/api/companion/stations/{station_id}/parts/"
            f"{encoded_rueckmeldenummer}/measurement-values",
        )

    async def post_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/companion/heartbeats", json=payload)

    async def post_event(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", endpoint, json=payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.server_url,
            timeout=self.timeout_seconds,
        ) as client:
            response = await client.request(
                method,
                path,
                json=json,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    def _headers(self) -> dict[str, str]:
        if self.station_id is None or not self.station_token:
            return {}
        return {
            "X-Station-ID": str(self.station_id),
            "X-Station-Token": self.station_token,
        }
