"""Function tools for the expense processing agents.

These are MCP tools that complement the agent-based tools created via .as_tool()
in orchestrator.py. They provide Google Sheets persistence functionality.

Tools:
- write_range: Write data to Google Sheets via MCP
- get_ranges: Read data from Google Sheets via MCP

Note: Validation is handled by the ValidadorGastos agent (via .as_tool()),
not by a separate @function_tool. This avoids redundancy in the system.
"""

import json

from agents import function_tool
from loguru import logger

from src.services.mcp_client import mcp_client


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
                "range": ranges,  # FIX: El servidor MCP .NET espera "range" no "ranges"
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
