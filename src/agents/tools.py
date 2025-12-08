"""Function tools for the expense processing agents.

These are utility tools that complement the agent-based tools created via .as_tool()
in orchestrator.py. They provide validation and MCP persistence functionality.

Tools:
- validate_expense: Validates categorized expense data using Gemini + business rules
- write_range: Write data to Google Sheets via MCP
- get_ranges: Read data from Google Sheets via MCP
"""

import json
import re
from datetime import date, datetime, timedelta

from agents import function_tool
from loguru import logger

from src.agents.prompts import get_validator_prompt
from src.core.configs import settings
from src.core.llm_manager import llm_manager
from src.services.mcp_client import mcp_client


# --- Validation Tool (uses Gemini with business rules) ---
@function_tool
async def validate_expense(
    fecha: str,
    tipo: str,
    categoria: str,
    importe: str,
    descripcion: str,
) -> str:
    """Validate categorized expense data using business rules and an AI validator.

    This tool uses Gemini to verify if the categorization is correct based on
    business rules. If the categorization is wrong, it provides corrections.

    Args:
        fecha: Transaction date in DD/MM/YYYY format
        tipo: Movement type ("Gasto" or "Ingreso")
        categoria: Expense category (Alimentación, Transporte, Ocio, etc.)
        importe: Amount with Spanish comma decimal (e.g., "362,67")
        descripcion: Brief description of the expense/merchant

    Returns:
        JSON with:
        - is_valid (bool): Whether categorization is correct
        - feedback (str|null): Explanation if invalid
        - corrected_category (str|null): Correct category if wrong
        - corrected_type (str|null): Correct type if wrong
    """
    logger.info(f"validate_expense called for: {descripcion} - {categoria}")

    # Build the expense data to send to validator
    expense_data = {
        "fecha": fecha,
        "tipo": tipo,
        "categoria": categoria,
        "importe": importe,
        "descripcion": descripcion,
    }

    # First, do basic format validation
    format_errors = _validate_format(fecha, tipo, categoria, importe)
    if format_errors:
        return json.dumps({
            "is_valid": False,
            "feedback": "; ".join(format_errors),
            "corrected_category": None,
            "corrected_type": None,
        })

    # Use Gemini for semantic validation with business rules
    try:
        validator_prompt = get_validator_prompt()
        provider = settings.orchestrator.validator_provider

        # Get model from llm_manager
        model = llm_manager.get_model(provider)
        if not model:
            logger.warning(f"Validator model not available ({provider}), skipping AI validation")
            return json.dumps({
                "is_valid": True,
                "feedback": None,
                "corrected_category": None,
                "corrected_type": None,
            })

        # Call the validator model directly
        from agents import Agent, Runner, ModelSettings

        validator_agent = Agent(
            name="ValidadorGastos",
            instructions=validator_prompt,
            model=model,
            model_settings=ModelSettings(temperature=0.0),
        )

        # Send expense data to validator
        message = json.dumps(expense_data, ensure_ascii=False)
        result = await Runner.run(validator_agent, message)

        # Parse the validator's response
        response_text = result.final_output
        logger.debug(f"Validator response: {response_text}")

        # Try to extract JSON from response
        validation_result = _parse_validator_response(response_text)

        logger.info(f"Validation result: is_valid={validation_result.get('is_valid')}")
        return json.dumps(validation_result)

    except Exception as e:
        logger.exception(f"Error in AI validation: {e}")
        # Fall back to accepting the expense if validator fails
        return json.dumps({
            "is_valid": True,
            "feedback": f"Validación AI no disponible: {e}",
            "corrected_category": None,
            "corrected_type": None,
        })


def _validate_format(fecha: str, tipo: str, categoria: str, importe: str) -> list[str]:
    """Validate basic format requirements.

    Returns list of error messages, empty if all valid.
    """
    errors = []

    # Valid categories
    valid_categories = [
        "Alimentación", "Transporte", "Ocio", "Hogar", "Ropa",
        "Inversiones", "Suscripciones", "Otros", "Ahorros"
    ]

    # Valid types
    valid_types = ["Gasto", "Ingreso"]

    # Check date format (DD/MM/YYYY)
    try:
        parsed_date = datetime.strptime(fecha, "%d/%m/%Y").date()
        today = date.today()
        if parsed_date > today:
            errors.append(f"La fecha ({fecha}) no puede ser futura")
        one_year_ago = today - timedelta(days=365)
        if parsed_date < one_year_ago:
            errors.append(f"La fecha ({fecha}) es de hace más de un año")
    except ValueError:
        errors.append(f"Formato de fecha inválido: {fecha}. Debe ser DD/MM/YYYY")

    # Check type
    if tipo not in valid_types:
        errors.append(f"Tipo inválido: {tipo}. Debe ser 'Gasto' o 'Ingreso'")

    # Check category
    if categoria not in valid_categories:
        errors.append(f"Categoría inválida: {categoria}. Categorías válidas: {', '.join(valid_categories)}")

    # Check importe format (Spanish comma decimal)
    importe_pattern = r"^\d+,\d{2}$"
    if not re.match(importe_pattern, importe):
        # Also allow whole numbers like "32,00"
        if not re.match(r"^\d+,\d{1,2}$", importe):
            errors.append(f"Formato de importe inválido: {importe}. Debe usar coma decimal (ej: 362,67)")

    return errors


def _parse_validator_response(response_text: str) -> dict:
    """Parse the validator's response, extracting JSON.

    Args:
        response_text: Raw response from validator agent

    Returns:
        Parsed validation result dict
    """
    # Default response
    default = {
        "is_valid": True,
        "feedback": None,
        "corrected_category": None,
        "corrected_type": None,
    }

    if not response_text:
        return default

    # Try to parse as direct JSON
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    json_patterns = [
        r"```json\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
        r"\{[^{}]*\}",
    ]

    for pattern in json_patterns:
        matches = re.findall(pattern, response_text, re.DOTALL)
        for match in matches:
            try:
                result = json.loads(match)
                if "is_valid" in result:
                    return result
            except json.JSONDecodeError:
                continue

    # Could not parse, assume valid
    logger.warning(f"Could not parse validator response: {response_text[:200]}")
    return default


# --- MCP Tools for Google Sheets ---
@function_tool
async def write_range(
    range: str,
    values: list[list[str]],
) -> str:
    """Write data to Google Sheets via MCP server.

    Use this tool to persist expense data to the Google Sheets document.
    Before writing, you should use get_ranges to find the next empty row.

    Args:
        range: Sheet range in A1 notation (e.g., "Gastos!A55:E55")
        values: 2D array of values to write (e.g., [["05/11/2025", "Gasto", "Otros", "362,67", "IRPF 2024"]])

    Returns:
        JSON with success status and details
    """
    logger.info(f"write_range called: {range}")
    logger.debug(f"Values: {values}")

    if not mcp_client.is_connected:
        logger.warning("MCP server not connected, attempting to establish connection")

    try:
        result = await mcp_client.call_tool(
            "write_range",
            {
                "range": range,
                "values": values,
            }
        )

        if result.get("success"):
            logger.info(f"Successfully wrote to {range}")
            return json.dumps({
                "success": True,
                "range": range,
                "rows_written": len(values),
                "message": f"Datos guardados en {range}",
            })
        else:
            error = result.get("error", "Error desconocido del servidor MCP")
            logger.error(f"MCP write_range failed: {error}")
            return json.dumps({
                "success": False,
                "error": error,
            })

    except Exception as e:
        logger.exception(f"Error calling MCP write_range: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
        })


@function_tool
async def get_ranges(
    ranges: list[str],
) -> str:
    """Read data from Google Sheets via MCP server.

    Use this tool to read existing data, particularly to find the last row
    with data before writing a new expense.

    Args:
        ranges: List of ranges to read in A1 notation (e.g., ["Gastos!A1:E100"])

    Returns:
        JSON with the data from the requested ranges
    """
    logger.info(f"get_ranges called: {ranges}")

    if not mcp_client.is_connected:
        logger.warning("MCP server not connected, attempting to establish connection")

    try:
        result = await mcp_client.call_tool(
            "get_ranges",
            {
                "ranges": ranges,
            }
        )

        if result.get("success"):
            logger.info(f"Successfully read {len(ranges)} range(s)")
            return json.dumps({
                "success": True,
                "data": result.get("data") or result.get("values") or result,
            })
        else:
            error = result.get("error", "Error desconocido del servidor MCP")
            logger.error(f"MCP get_ranges failed: {error}")
            return json.dumps({
                "success": False,
                "error": error,
            })

    except Exception as e:
        logger.exception(f"Error calling MCP get_ranges: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
        })
