"""Async Google Sheets API v4 client.

Talks to the Sheets REST API directly with httpx, replacing the C# MCP
server for the real-time capture flow. Rows are written with append, so
the API picks the next free row and nothing is overwritten.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

TokenProvider = Callable[[], Awaitable[str]]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"


class SheetsError(Exception):
    """Raised when a Sheets API call fails."""


def service_account_token_provider(key_file: str) -> TokenProvider:
    """Build a token provider backed by a service-account key file."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        key_file, scopes=SCOPES
    )

    async def get_token() -> str:
        if not creds.valid:
            await asyncio.to_thread(creds.refresh, Request())
        return str(creds.token)

    return get_token


class SheetsClient:
    """Minimal client for reading ranges and appending rows to one spreadsheet."""

    def __init__(
        self,
        spreadsheet_id: str,
        token_provider: TokenProvider,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = f"{BASE_URL}/{spreadsheet_id}"
        self._token_provider = token_provider
        self._http = http or httpx.AsyncClient(timeout=15.0)

    async def batch_get(self, ranges: list[str]) -> list[list[list[str]]]:
        """Read several ranges; returns their values in the requested order."""
        data = await self._request(
            "GET",
            "/values:batchGet",
            params=[("ranges", r) for r in ranges]
            + [("valueRenderOption", "FORMATTED_VALUE")],
        )
        return [vr.get("values", []) for vr in data.get("valueRanges", [])]

    async def append(self, range_: str, row: list[str]) -> str:
        """Append one row after the table in range_; returns the updated range."""
        data = await self._request(
            "POST",
            f"/values/{quote(range_, safe='')}:append",
            params={
                "valueInputOption": "USER_ENTERED",
                "insertDataOption": "INSERT_ROWS",
            },
            json={"values": [row]},
        )
        return str(data["updates"]["updatedRange"])

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send an authenticated request; no retries, append is not idempotent."""
        headers = {"Authorization": f"Bearer {await self._token_provider()}"}
        try:
            response = await self._http.request(
                method, self._base_url + path, headers=headers, **kwargs
            )
        except httpx.HTTPError as e:
            raise SheetsError(f"Sheets request failed: {type(e).__name__}: {e}") from e
        if not response.is_success:
            try:
                message = response.json()["error"]["message"]
            except Exception:
                message = response.text[:200]
            raise SheetsError(f"Sheets API error {response.status_code}: {message}")
        result: dict[str, Any] = response.json()
        return result
