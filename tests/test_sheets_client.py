import json

import httpx
import pytest

from src.services.sheets_client import SheetsClient, SheetsError


async def fake_token() -> str:
    return "tok"


def make_client(handler) -> SheetsClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SheetsClient("sheet-id", fake_token, http=http)


async def test_batch_get_returns_values_per_range_in_order():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "valueRanges": [
                    {"range": "Reglas!A1:B2", "values": [["amazon", "Compras"]]},
                    {"range": "Gastos!F:F"},
                ]
            },
        )

    result = await make_client(handler).batch_get(["Reglas!A:B", "Gastos!F:F"])

    assert result == [[["amazon", "Compras"]], []]
    request = seen[0]
    assert request.method == "GET"
    assert request.url.path == "/v4/spreadsheets/sheet-id/values:batchGet"
    assert request.url.params.get_list("ranges") == ["Reglas!A:B", "Gastos!F:F"]
    assert request.url.params["valueRenderOption"] == "FORMATTED_VALUE"
    assert request.headers["Authorization"] == "Bearer tok"


async def test_append_posts_row_and_returns_updated_range():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"updates": {"updatedRange": "Gastos!A42:F42"}})

    row = ["24/10/2026", "WWW.AMAZON", "-14,99", "Compras", "", "fp"]
    result = await make_client(handler).append("Gastos!A:F", row)

    assert result == "Gastos!A42:F42"
    request = seen[0]
    assert request.method == "POST"
    assert "Gastos%21A%3AF" in request.url.raw_path.decode()
    assert request.url.path.endswith(":append")
    assert request.url.params["valueInputOption"] == "USER_ENTERED"
    assert request.url.params["insertDataOption"] == "INSERT_ROWS"
    assert json.loads(request.content) == {"values": [row]}
    assert request.headers["Authorization"] == "Bearer tok"


async def test_http_error_raises_sheets_error_without_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": {"message": "The caller does not have permission"}}
        )

    with pytest.raises(SheetsError) as exc:
        await make_client(handler).append("Gastos!A:F", ["x"])

    message = str(exc.value)
    assert "403" in message
    assert "The caller does not have permission" in message
    assert "tok" not in message


async def test_transport_error_raises_sheets_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(SheetsError):
        await make_client(handler).batch_get(["Gastos!F:F"])
