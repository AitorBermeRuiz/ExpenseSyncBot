"""Ingest one parsed bank movement into the Gastos sheet.

Categorizes with the "Reglas" tab first (LLM only when no rule matches),
skips movements whose fingerprint is already in Gastos column F, and
appends everything else as one row.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from src.ingestion.parsers import ParsedTransaction
from src.models.schemas import ExpenseCategory
from src.services.sheets_client import SheetsClient

RULES_RANGE = "Reglas!A2:C"
FINGERPRINT_RANGE = "Gastos!F:F"
APPEND_RANGE = "Gastos!A:F"

Categorizer = Callable[[str], Awaitable[tuple[ExpenseCategory, str]]]

# shortcut: in-process lock, valid only with a single uvicorn worker; move to a shared lock if workers > 1
_lock = asyncio.Lock()


@dataclass(frozen=True)
class IngestResult:
    status: Literal["saved", "duplicate"]
    row: list[str]
    updated_range: str | None


def _match_rule(
    rules: list[list[str]], comercio: str
) -> tuple[ExpenseCategory, str] | None:
    """First rule in sheet order whose pattern is a case-insensitive substring of comercio."""
    for rule in rules:
        pattern = rule[0].strip() if rule else ""
        if not pattern or pattern.lower() not in comercio.lower():
            continue
        try:
            categoria = ExpenseCategory(rule[1].strip() if len(rule) > 1 else "")
        except ValueError:
            logger.warning(
                f"Skipping rule with invalid category for pattern '{pattern}'"
            )
            continue
        descripcion = rule[2].strip() if len(rule) > 2 else ""
        return categoria, descripcion or comercio
    return None


def _escape(value: str) -> str:
    """Stop USER_ENTERED from evaluating text cells as formulas."""
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


async def ingest(
    tx: ParsedTransaction, sheets: SheetsClient, categorize: Categorizer
) -> IngestResult:
    """Categorize and append tx unless its fingerprint is already in column F."""
    # The iOS shortcut fires twice per notification; check and append must not interleave.
    async with _lock:
        rules, fingerprints = await sheets.batch_get([RULES_RANGE, FINGERPRINT_RANGE])
        if any(cells and cells[0] == tx.fingerprint for cells in fingerprints):
            logger.info("Ingest status: duplicate")
            return IngestResult("duplicate", [], None)

        match = _match_rule(rules, tx.comercio)
        if match is None:
            try:
                match = await categorize(tx.comercio)
            except Exception as e:
                logger.warning(f"Categorizer failed ({type(e).__name__}), using Otros")
                match = (ExpenseCategory.OTROS, tx.comercio)
        categoria, descripcion = match

        row = [
            tx.fecha,
            tx.tipo.value,
            categoria.value,
            tx.importe,
            _escape(descripcion[:50]),
            _escape(tx.fingerprint),
        ]
        updated_range = await sheets.append(APPEND_RANGE, row)
        logger.info(
            f"Ingest status: saved, categoria: {categoria.value}, range: {updated_range}"
        )
        return IngestResult("saved", row, updated_range)


async def llm_categorize(comercio: str) -> tuple[ExpenseCategory, str]:
    """Default Categorizer backed by the categorizer agent."""
    from agents import Runner

    from src.expense_agents.orchestrator import create_categorizer_agent

    result = await Runner.run(create_categorizer_agent(), comercio)
    return result.final_output.categoria, result.final_output.descripcion
