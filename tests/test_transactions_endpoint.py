import pytest
from fastapi.testclient import TestClient

from src.core.configs import settings
from src.main import app, get_categorizer, get_sheets_client
from src.models.schemas import ExpenseCategory
from src.services.sheets_client import SheetsError

AMAZON = "Openbank info: pago con tu tarjeta **7402 el 24/10 18:18 por 14,99 EUR en WWW.AMAZON +18002796620  LU."
AMAZON_FP = "openbank | 24/10/2026 18:18 | 14,99 | WWW.AMAZON +18002796620 LU"
BIZUM = "Has recibido un Bizum de 1,00  EUR de Julia Monica R.A. por Tontolaba"
RECEIVED = "2026-10-24T18:20:00+02:00"
AUTH = {"X-Api-Token": "secret"}


class FakeSheets:
    def __init__(
        self, fingerprints: list[str] | None = None, error: Exception | None = None
    ):
        self.fingerprints = [[fp] for fp in fingerprints or []]
        self.error = error
        self.gets: list[list[str]] = []
        self.rows: list[list[str]] = []

    async def batch_get(self, ranges: list[str]) -> list[list[list[str]]]:
        self.gets.append(ranges)
        return [[], self.fingerprints]

    async def append(self, range_: str, row: list[str]) -> str:
        if self.error:
            raise self.error
        self.rows.append(row)
        return "Gastos!A42:F42"


async def fake_categorizer(comercio: str) -> tuple[ExpenseCategory, str]:
    return ExpenseCategory.OTROS, "Amazon - compra"


@pytest.fixture
def sheets(monkeypatch):
    monkeypatch.setattr(settings.ingest, "api_token", "secret")
    fake = FakeSheets()
    app.dependency_overrides[get_sheets_client] = lambda: fake
    app.dependency_overrides[get_categorizer] = lambda: fake_categorizer
    yield fake
    app.dependency_overrides.clear()


client = TestClient(app)


def post(body: dict, headers: dict | None = AUTH):
    return client.post("/transactions", json=body, headers=headers or {})


def test_amazon_card_payment_is_saved(sheets):
    r = post({"source": "openbank", "raw_text": AMAZON, "received_at": RECEIVED})

    assert r.status_code == 200
    assert r.json() == {
        "status": "saved",
        "data": {
            "fecha": "24/10/2026",
            "tipo": "Gasto",
            "categoria": "Otros",
            "importe": "14,99",
            "descripcion": "Amazon - compra",
        },
        "sheet_range": "Gastos!A42:F42",
    }
    assert len(sheets.rows) == 1
    assert sheets.rows[0][-1] == AMAZON_FP


def test_received_bizum_is_saved_as_income(sheets):
    r = post({"source": "openbank", "raw_text": BIZUM, "received_at": RECEIVED})

    assert r.status_code == 200
    assert r.json()["status"] == "saved"
    assert r.json()["data"]["tipo"] == "Ingreso"
    assert r.json()["data"]["importe"] == "1,00"
    assert len(sheets.rows) == 1


def test_duplicate_fingerprint_is_not_appended(sheets):
    sheets.fingerprints = [[AMAZON_FP]]

    r = post({"source": "openbank", "raw_text": AMAZON, "received_at": RECEIVED})

    assert r.status_code == 200
    assert r.json() == {"status": "duplicate", "data": None, "sheet_range": None}
    assert sheets.rows == []


def test_unrecognized_text_is_ignored_without_sheets_calls(sheets):
    r = post({"source": "openbank", "raw_text": "Tu código de verificación es 123456"})

    assert r.status_code == 200
    assert r.json() == {"status": "ignored", "data": None, "sheet_range": None}
    assert sheets.gets == [] and sheets.rows == []


@pytest.mark.parametrize("headers", [None, {"X-Api-Token": "wrong"}])
def test_missing_or_wrong_token_is_rejected(sheets, headers):
    r = post(
        {"source": "openbank", "raw_text": AMAZON, "received_at": RECEIVED}, headers
    )

    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid token"}
    assert sheets.gets == [] and sheets.rows == []


def test_unset_token_fails_closed(sheets, monkeypatch):
    monkeypatch.setattr(settings.ingest, "api_token", None)

    r = post({"source": "openbank", "raw_text": AMAZON, "received_at": RECEIVED})

    assert r.status_code == 503
    assert r.json() == {"detail": "Ingestion not configured"}
    assert sheets.gets == [] and sheets.rows == []


@pytest.mark.parametrize(
    "body",
    [
        {"source": "caixabank", "raw_text": AMAZON},
        {"source": "openbank", "raw_text": ""},
        {"source": "openbank", "raw_text": "x" * 2001},
        {"source": "openbank", "raw_text": AMAZON, "extra": 1},
    ],
)
def test_invalid_body_is_rejected(sheets, body):
    r = post(body)

    assert r.status_code == 422
    assert sheets.gets == [] and sheets.rows == []


def test_sheets_error_returns_502(sheets):
    sheets.error = SheetsError("Sheets API error 500: boom")

    r = post({"source": "openbank", "raw_text": AMAZON, "received_at": RECEIVED})

    assert r.status_code == 502
    assert r.json() == {"detail": "Sheets write failed"}


def test_unconfigured_sheets_returns_503(monkeypatch):
    monkeypatch.setattr(settings.ingest, "api_token", "secret")
    monkeypatch.setattr(settings.ingest, "spreadsheet_id", None)
    get_sheets_client.cache_clear()

    r = post({"source": "openbank", "raw_text": AMAZON, "received_at": RECEIVED})

    assert r.status_code == 503
    assert r.json() == {"detail": "Ingestion not configured"}


def test_health_still_works():
    r = client.get("/health")

    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
