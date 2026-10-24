from datetime import UTC, datetime

import pytest

from src.ingestion import ParsedTransaction, parse_openbank
from src.models.schemas import MovementType

RECEIVED = datetime(2026, 10, 24, 18, 20)


@pytest.mark.parametrize(
    ("text", "importe", "comercio", "hora"),
    [
        (
            "Openbank info: pago con tu tarjeta **7402 el 24/10 18:18 por 14,99 EUR en "
            "WWW.AMAZON +18002796620  LU.",
            "14,99",
            "WWW.AMAZON +18002796620 LU",
            "18:18",
        ),
        (
            "Openbank info: pago con tu tarjeta **7402 el 24/10 13:56 por 10,65 EUR en "
            "T175 VILLA DEL PRADO VILLA DEL PRA ES.",
            "10,65",
            "T175 VILLA DEL PRADO VILLA DEL PRA ES",
            "13:56",
        ),
        (
            "Openbank info: pago con tu tarjeta **7402 el 24/10 12:36 por 2,99 EUR en "
            "APPLE.COM/BILL CORK IE.",
            "2,99",
            "APPLE.COM/BILL CORK IE",
            "12:36",
        ),
    ],
)
def test_card_payment(text: str, importe: str, comercio: str, hora: str) -> None:
    assert parse_openbank(text, RECEIVED) == ParsedTransaction(
        fecha="24/10/2026",
        tipo=MovementType.GASTO,
        importe=importe,
        comercio=comercio,
        fingerprint=f"openbank | 24/10/2026 {hora} | {importe} | {comercio}",
    )


@pytest.mark.parametrize(
    ("text", "comercio"),
    [
        (
            "Has recibido un Bizum de 1,00  EUR de Julia Monica R.A. por Tontolaba",
            "Bizum de Julia Monica R.A. por Tontolaba",
        ),
        (
            "Has recibido un Bizum de 1,00  EUR de Julia Monica R.A. por Bizum de Julia monica",
            "Bizum de Julia Monica R.A. por Bizum de Julia monica",
        ),
    ],
)
def test_received_bizum(text: str, comercio: str) -> None:
    assert parse_openbank(text, datetime(2026, 10, 24, 18, 12, 37)) == ParsedTransaction(
        fecha="24/10/2026",
        tipo=MovementType.INGRESO,
        importe="1,00",
        comercio=comercio,
        fingerprint=f"openbank | 24/10/2026 18:12 | 1,00 | {comercio}",
    )


BIZUM = "Has recibido un Bizum de 1,00  EUR de Julia Monica R.A. por Tontolaba"


def test_bizum_same_minute_same_fingerprint() -> None:
    a = parse_openbank(BIZUM, datetime(2026, 10, 24, 18, 12, 5))
    b = parse_openbank(BIZUM, datetime(2026, 10, 24, 18, 12, 50))
    assert a is not None and b is not None
    assert a.fingerprint == b.fingerprint


def test_card_year_rollover() -> None:
    text = "Openbank info: pago con tu tarjeta **7402 el 31/12 23:59 por 5,00 EUR en BAR PEPE ES."
    parsed = parse_openbank(text, datetime(2027, 1, 1, 0, 1))
    assert parsed is not None
    assert parsed.fecha == "31/12/2026"
    assert parsed.fingerprint == "openbank | 31/12/2026 23:59 | 5,00 | BAR PEPE ES"


def test_aware_received_at_converted_to_madrid() -> None:
    parsed = parse_openbank(BIZUM, datetime(2026, 10, 24, 16, 12, tzinfo=UTC))
    assert parsed is not None
    assert parsed.fecha == "24/10/2026"
    assert parsed.fingerprint == "openbank | 24/10/2026 18:12 | 1,00 | Bizum de Julia Monica R.A. por Tontolaba"


def test_thousands_amount() -> None:
    text = "Openbank info: pago con tu tarjeta **7402 el 24/10 18:18 por 1.234,56 EUR en TIENDA ES."
    parsed = parse_openbank(text, RECEIVED)
    assert parsed is not None
    assert parsed.importe == "1234,56"
    assert parsed.fingerprint == "openbank | 24/10/2026 18:18 | 1234,56 | TIENDA ES"


@pytest.mark.parametrize(
    "text",
    ["Tu código de verificación es 123456", "", "Openbank info: tu tarjeta ha sido bloqueada"],
)
def test_unrelated_text_returns_none(text: str) -> None:
    assert parse_openbank(text, RECEIVED) is None
