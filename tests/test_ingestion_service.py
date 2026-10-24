import asyncio
from datetime import datetime

from src.ingestion import ParsedTransaction, ingest, parse_openbank
from src.models.schemas import ExpenseCategory

RECEIVED = datetime(2026, 10, 24, 18, 20)
AMAZON = "Openbank info: pago con tu tarjeta **7402 el 24/10 18:18 por 14,99 EUR en WWW.AMAZON +18002796620  LU."
BIZUM = "Has recibido un Bizum de 1,00  EUR de Julia Monica R.A. por Tontolaba"
AMAZON_FP = "openbank | 24/10/2026 18:18 | 14,99 | WWW.AMAZON +18002796620 LU"


def tx(text: str = AMAZON) -> ParsedTransaction:
    parsed = parse_openbank(text, RECEIVED)
    assert parsed is not None
    return parsed


class FakeSheets:
    def __init__(
        self,
        rules: list[list[str]] | None = None,
        fingerprints: list[str] | None = None,
    ):
        self.rules = rules or []
        self.fingerprints = [[fp] for fp in fingerprints or []]
        self.appends: list[tuple[str, list[str]]] = []
        self.gets: list[list[str]] = []

    async def batch_get(self, ranges: list[str]) -> list[list[list[str]]]:
        self.gets.append(ranges)
        await asyncio.sleep(0)
        return [self.rules, list(self.fingerprints)]

    async def append(self, range_: str, row: list[str]) -> str:
        self.appends.append((range_, row))
        self.fingerprints.append([row[5]])
        return f"Gastos!A{len(self.appends) + 1}:F{len(self.appends) + 1}"


class FakeCategorizer:
    def __init__(
        self,
        result=(ExpenseCategory.SUSCRIPCIONES, "Desde LLM"),
        error: Exception | None = None,
    ):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    async def __call__(self, comercio: str) -> tuple[ExpenseCategory, str]:
        self.calls.append(comercio)
        if self.error:
            raise self.error
        return self.result


async def test_rule_match_skips_llm_and_appends_exact_row():
    sheets = FakeSheets(rules=[["AMAZON", "Otros", "Amazon - compra online"]])
    categorize = FakeCategorizer()

    result = await ingest(tx(), sheets, categorize)  # type: ignore[arg-type]

    row = ["24/10/2026", "Gasto", "Otros", "14,99", "Amazon - compra online", AMAZON_FP]
    assert result.status == "saved"
    assert result.row == row
    assert result.updated_range == "Gastos!A2:F2"
    assert sheets.gets == [["Reglas!A2:C", "Gastos!F:F"]]
    assert sheets.appends == [("Gastos!A:F", row)]
    assert categorize.calls == []


async def test_rule_without_description_uses_comercio():
    sheets = FakeSheets(rules=[["amazon", "Ocio"]])

    result = await ingest(tx(), sheets, FakeCategorizer())  # type: ignore[arg-type]

    assert result.row[2:5] == ["Ocio", "14,99", "WWW.AMAZON +18002796620 LU"]


async def test_rules_are_case_insensitive_and_first_match_wins():
    sheets = FakeSheets(
        rules=[
            ["", "Ocio", "vacía"],
            ["nada", "Ocio", "no"],
            ["www.amazon", "Ropa", "primera"],
            ["AMAZON", "Hogar", "segunda"],
        ]
    )

    result = await ingest(tx(), sheets, FakeCategorizer())  # type: ignore[arg-type]

    assert result.row[2] == "Ropa"
    assert result.row[4] == "primera"


async def test_rule_with_invalid_category_is_skipped():
    sheets = FakeSheets(
        rules=[["AMAZON", "alimentacion", "mala"], ["AMAZON", "Alimentación", "buena"]]
    )

    result = await ingest(tx(), sheets, FakeCategorizer())  # type: ignore[arg-type]

    assert result.row[2] == "Alimentación"
    assert result.row[4] == "buena"


async def test_invalid_only_rule_falls_back_to_llm():
    sheets = FakeSheets(rules=[["AMAZON", "Compras"]])
    categorize = FakeCategorizer()

    result = await ingest(tx(), sheets, categorize)  # type: ignore[arg-type]

    assert categorize.calls == ["WWW.AMAZON +18002796620 LU"]
    assert result.row[2] == "Suscripciones"


async def test_no_rule_calls_categorizer_once():
    sheets = FakeSheets(rules=[["MERCADONA", "Alimentación"]])
    categorize = FakeCategorizer()

    result = await ingest(tx(), sheets, categorize)  # type: ignore[arg-type]

    assert categorize.calls == ["WWW.AMAZON +18002796620 LU"]
    assert result.status == "saved"
    assert result.row[2] == "Suscripciones"
    assert result.row[4] == "Desde LLM"
    assert len(sheets.appends) == 1


async def test_categorizer_error_falls_back_to_otros():
    sheets = FakeSheets()

    result = await ingest(tx(), sheets, FakeCategorizer(error=RuntimeError("boom")))  # type: ignore[arg-type]

    assert result.status == "saved"
    assert result.row[2] == "Otros"
    assert result.row[4] == "WWW.AMAZON +18002796620 LU"
    assert len(sheets.appends) == 1


async def test_duplicate_fingerprint_is_not_appended():
    sheets = FakeSheets(
        rules=[["AMAZON", "Otros"]], fingerprints=["Fingerprint", AMAZON_FP]
    )
    categorize = FakeCategorizer()

    result = await ingest(tx(), sheets, categorize)  # type: ignore[arg-type]

    assert result.status == "duplicate"
    assert result.row == []
    assert result.updated_range is None
    assert sheets.appends == []
    assert categorize.calls == []


async def test_concurrent_same_transaction_is_written_once():
    sheets = FakeSheets()

    results = await asyncio.gather(
        ingest(tx(), sheets, FakeCategorizer()),  # type: ignore[arg-type]
        ingest(tx(), sheets, FakeCategorizer()),  # type: ignore[arg-type]
    )

    assert len(sheets.appends) == 1
    assert sorted(r.status for r in results) == ["duplicate", "saved"]


async def test_text_cells_are_escaped_and_description_truncated():
    sheets = FakeSheets()

    result = await ingest(
        tx(), sheets, FakeCategorizer(result=(ExpenseCategory.OCIO, '=HYPERLINK("x")'))
    )  # type: ignore[arg-type]
    assert result.row[4] == '\'=HYPERLINK("x")'

    long = await ingest(
        tx(BIZUM),
        FakeSheets(),
        FakeCategorizer(result=(ExpenseCategory.OCIO, "x" * 80)),
    )  # type: ignore[arg-type]
    assert long.row[4] == "x" * 50


async def test_bizum_is_recorded_as_income():
    sheets = FakeSheets(rules=[["bizum de", "Otros", "Bizum recibido"]])

    result = await ingest(tx(BIZUM), sheets, FakeCategorizer())  # type: ignore[arg-type]

    assert result.status == "saved"
    assert result.row[:5] == [
        "24/10/2026",
        "Ingreso",
        "Otros",
        "1,00",
        "Bizum recibido",
    ]
    assert result.row[5].startswith("openbank | 24/10/2026 18:20 | 1,00 | Bizum de")
