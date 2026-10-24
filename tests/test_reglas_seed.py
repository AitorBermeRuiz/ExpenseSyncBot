import csv
from pathlib import Path

from src.models.schemas import ExpenseCategory

SEED = Path(__file__).parent.parent / "docs" / "reglas_seed.csv"


def test_seed_rows_have_pattern_and_valid_category() -> None:
    with SEED.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["Patrón", "Categoría", "Descripción"]
    for pattern, categoria, descripcion in rows[1:]:
        assert pattern.strip()
        ExpenseCategory(categoria)  # raises on typos such as a missing accent
        assert len(descripcion) <= 50
