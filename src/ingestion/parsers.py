"""Deterministic parsers for bank push-notification texts (no LLM)."""

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from src.models.schemas import MovementType

MADRID = ZoneInfo("Europe/Madrid")
_AMOUNT = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"
_CARD = re.compile(
    rf"^Openbank info: pago con tu tarjeta \*\*\d{{4}} el (\d{{2}})/(\d{{2}}) (\d{{2}}:\d{{2}}) "
    rf"por {_AMOUNT} EUR en (.+)$"
)
_BIZUM = re.compile(rf"^Has recibido un Bizum de {_AMOUNT} EUR de (.+?) por (.+)$")


@dataclass(frozen=True)
class ParsedTransaction:
    fecha: str  # DD/MM/YYYY
    tipo: MovementType
    importe: str  # Spanish decimal comma, no thousands separator
    comercio: str
    fingerprint: str


def _fingerprint(fecha: str, hora: str, importe: str, comercio: str) -> str:
    return f"openbank | {fecha} {hora} | {importe} | {comercio}"


def parse_openbank(raw_text: str, received_at: datetime) -> ParsedTransaction | None:
    """Parse an Openbank card payment or received Bizum; None for any other text."""
    text = " ".join(raw_text.split()).removesuffix(".")
    received = (
        received_at.replace(tzinfo=MADRID)
        if received_at.tzinfo is None
        else received_at.astimezone(MADRID)
    )

    if m := _CARD.match(text):
        day, month, hora, amount, comercio = m.groups()
        year = received.year
        if (int(month), int(day)) > (received.month, received.day):
            year -= 1
        fecha = f"{day}/{month}/{year}"
        importe = amount.replace(".", "")
        return ParsedTransaction(
            fecha, MovementType.GASTO, importe, comercio, _fingerprint(fecha, hora, importe, comercio)
        )

    if m := _BIZUM.match(text):
        amount, sender, concept = m.groups()
        fecha = received.strftime("%d/%m/%Y")
        importe = amount.replace(".", "")
        comercio = f"Bizum de {sender} por {concept}"
        # shortcut: no time in Bizum text, so two runs straddling a minute boundary produce different fingerprints; acceptable until a sample with time exists
        hora = received.strftime("%H:%M")
        return ParsedTransaction(
            fecha, MovementType.INGRESO, importe, comercio, _fingerprint(fecha, hora, importe, comercio)
        )

    return None
