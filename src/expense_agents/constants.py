"""Constants for agent tools and configuration.

This module centralizes all tool names to ensure consistency
between orchestrator definitions and API documentation.
"""

# --- Agent Tool Names ---
# These are the names used when converting agents to tools via .as_tool()

TOOL_CATEGORIZE_EXPENSE = "categorize_expense"
"""Tool name for the categorizer agent (CategorizadorGastos)."""

TOOL_VALIDATE_CATEGORIZATION = "validate_categorization"
"""Tool name for the validator agent (ValidadorGastos)."""

TOOL_SAVE_EXPENSE = "save_expense"
"""Tool name for the persistence agent (PersistenciaGastos)."""


# --- MCP Function Tool Names ---
# These are the names of @function_tool decorated functions

TOOL_GET_RANGES = "get_ranges"
"""Function tool for reading Google Sheets ranges via MCP."""

TOOL_WRITE_RANGE = "write_range"
"""Function tool for writing to Google Sheets via MCP."""


# --- Tool Collections ---

AGENT_TOOLS = [
    TOOL_CATEGORIZE_EXPENSE,
    TOOL_VALIDATE_CATEGORIZATION,
    TOOL_SAVE_EXPENSE,
]
"""List of all agent-based tools (created via .as_tool())."""

FUNCTION_TOOLS = [
    TOOL_GET_RANGES,
    TOOL_WRITE_RANGE,
]
"""List of all function tools (created via @function_tool decorator)."""
