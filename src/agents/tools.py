"""Internal Python tools for the orchestrator agent.

These tools are implemented as Python functions and called directly
by the orchestrator during receipt processing.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from loguru import logger
from openai import AsyncOpenAI

from src.agents.prompts import CATEGORIZER_SYSTEM_PROMPT
from src.models.schemas import (
    CategorizedExpense,
    CategorizationToolResponse,
    ExpenseCategory,
    ValidationResult,
    ValidationToolResponse,
)


async def categorize_receipt(
    client: AsyncOpenAI,
    model: str,
    text: str,
    feedback: str | None = None,
) -> CategorizationToolResponse:
    """Extract and categorize expense data from receipt email text.

    Uses an LLM to parse raw email content (potentially with HTML noise)
    and extract structured expense information.

    Args:
        client: OpenAI-compatible async client
        model: Model name to use
        text: Raw email body text
        feedback: Optional feedback from previous validation failure

    Returns:
        CategorizationToolResponse with expense data or error
    """
    logger.info("Categorizing receipt text")

    # Build the user message
    user_content = f"Analiza el siguiente email de recibo y extrae los datos del gasto:\n\n{text}"

    if feedback:
        user_content += f"\n\n---\nFEEDBACK DE CORRECCIÓN:\n{feedback}\n\nPor favor, corrige los datos basándote en este feedback."
        logger.debug(f"Including feedback for correction: {feedback[:100]}...")

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CATEGORIZER_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,  # Low temperature for consistent extraction
            max_tokens=500,
        )

        content = response.choices[0].message.content
        if not content:
            return CategorizationToolResponse(
                success=False,
                error="Empty response from categorization model",
            )

        # Parse JSON response
        # Handle potential markdown code blocks
        content = content.strip()
        if content.startswith("```"):
            # Remove markdown code block
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            content = content.strip()

        data = json.loads(content)

        # Check for error response from LLM
        if "error" in data:
            return CategorizationToolResponse(
                success=False,
                error=data["error"],
            )

        # Parse and validate the extracted data
        try:
            # Parse date
            fecha_str = data.get("fecha", "")
            if isinstance(fecha_str, str):
                fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            else:
                fecha = fecha_str

            # Parse amount
            importe = Decimal(str(data["importe"]))

            # Validate category
            categoria_str = data.get("categoria", "otros").lower()
            try:
                categoria = ExpenseCategory(categoria_str)
            except ValueError:
                categoria = ExpenseCategory.OTROS
                logger.warning(f"Unknown category '{categoria_str}', defaulting to 'otros'")

            expense = CategorizedExpense(
                comercio=data["comercio"],
                importe=importe,
                moneda=data.get("moneda", "EUR"),
                fecha=fecha,
                categoria=categoria,
                descripcion=data.get("descripcion"),
            )

            logger.info(f"Successfully categorized: {expense.comercio} - {expense.importe} {expense.moneda}")
            return CategorizationToolResponse(success=True, expense=expense)

        except (KeyError, ValueError, InvalidOperation) as e:
            error_msg = f"Error parsing categorization response: {e}"
            logger.error(error_msg)
            return CategorizationToolResponse(success=False, error=error_msg)

    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON in categorization response: {e}"
        logger.error(error_msg)
        return CategorizationToolResponse(success=False, error=error_msg)

    except Exception as e:
        error_msg = f"Categorization failed: {e}"
        logger.exception(error_msg)
        return CategorizationToolResponse(success=False, error=error_msg)


def validate_expense(expense: CategorizedExpense) -> ValidationToolResponse:
    """Validate categorized expense data against business rules.

    Performs validation checks including:
    - Amount reasonableness
    - Date validity (not future, not too old)
    - Required fields presence
    - Category consistency

    Args:
        expense: The categorized expense to validate

    Returns:
        ValidationToolResponse with validation result
    """
    logger.info(f"Validating expense: {expense.comercio}")

    warnings: list[str] = []
    errors: list[str] = []

    # --- Amount Validation ---
    if expense.importe <= 0:
        errors.append("El importe debe ser mayor que cero")
    elif expense.importe > Decimal("10000"):
        warnings.append(f"Importe muy alto ({expense.importe}), verificar manualmente")
    elif expense.importe < Decimal("0.01"):
        errors.append("El importe es demasiado pequeño")

    # --- Date Validation ---
    today = date.today()

    if expense.fecha > today:
        errors.append(f"La fecha ({expense.fecha}) no puede ser futura")

    # Check if date is too old (more than 1 year)
    one_year_ago = today - timedelta(days=365)
    if expense.fecha < one_year_ago:
        warnings.append(f"La fecha ({expense.fecha}) es de hace más de un año")

    # Check if date is very recent but in the future by a day (timezone issues)
    if expense.fecha == today + timedelta(days=1):
        warnings.append("La fecha es mañana, posible problema de zona horaria")

    # --- Merchant Validation ---
    if not expense.comercio or len(expense.comercio.strip()) < 2:
        errors.append("El nombre del comercio es demasiado corto o está vacío")

    if len(expense.comercio) > 100:
        warnings.append("El nombre del comercio es muy largo, podría contener ruido")

    # Check for suspicious patterns (HTML remnants)
    suspicious_patterns = ["<", ">", "href=", "class=", "style="]
    for pattern in suspicious_patterns:
        if pattern in expense.comercio:
            errors.append(f"El nombre del comercio contiene HTML ({pattern})")
            break

    # --- Currency Validation ---
    valid_currencies = ["EUR", "USD", "GBP", "CHF", "MXN", "ARS", "COP"]
    if expense.moneda not in valid_currencies:
        warnings.append(f"Moneda no común: {expense.moneda}")

    # --- Category-Amount Consistency ---
    # Some basic heuristics
    if expense.categoria == ExpenseCategory.SUSCRIPCIONES and expense.importe > Decimal("100"):
        warnings.append("Importe alto para una suscripción, verificar categoría")

    if expense.categoria == ExpenseCategory.TRANSPORTE and expense.importe > Decimal("500"):
        warnings.append("Importe muy alto para transporte regular, verificar categoría")

    # --- Build Result ---
    is_valid = len(errors) == 0

    if errors:
        error_message = "; ".join(errors)
        logger.warning(f"Validation failed: {error_message}")
    else:
        error_message = None
        if warnings:
            logger.info(f"Validation passed with warnings: {warnings}")
        else:
            logger.info("Validation passed")

    return ValidationToolResponse(
        result=ValidationResult(
            is_valid=is_valid,
            error_message=error_message,
            warnings=warnings,
        )
    )


def validate_expense_from_dict(data: dict) -> ValidationToolResponse:
    """Validate expense from dictionary data (for tool calling).

    Args:
        data: Dictionary with expense fields

    Returns:
        ValidationToolResponse with validation result
    """
    try:
        # Parse date if string
        fecha = data.get("fecha")
        if isinstance(fecha, str):
            fecha = datetime.strptime(fecha, "%Y-%m-%d").date()

        # Parse amount
        importe = Decimal(str(data["importe"]))

        # Parse category
        categoria_str = data.get("categoria", "otros").lower()
        try:
            categoria = ExpenseCategory(categoria_str)
        except ValueError:
            categoria = ExpenseCategory.OTROS

        expense = CategorizedExpense(
            comercio=data["comercio"],
            importe=importe,
            moneda=data.get("moneda", "EUR"),
            fecha=fecha,
            categoria=categoria,
            descripcion=data.get("descripcion"),
        )

        return validate_expense(expense)

    except Exception as e:
        logger.error(f"Error parsing expense data for validation: {e}")
        return ValidationToolResponse(
            result=ValidationResult(
                is_valid=False,
                error_message=f"Error parsing expense data: {e}",
            )
        )
