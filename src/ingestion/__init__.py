"""Deterministic ingestion of bank notifications."""

from src.ingestion.parsers import ParsedTransaction, parse_openbank

__all__ = ["ParsedTransaction", "parse_openbank"]
