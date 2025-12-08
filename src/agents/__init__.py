"""Agent components for ExpenseSyncBot using OpenAI Agents SDK.

Architecture:
- Specialized agents converted to tools via .as_tool():
  - CategorizadorGastos (GPT): Extracts and categorizes expenses
  - ValidadorGastos (Gemini): Validates with business rules
  - PersistenciaGastos: Writes to Google Sheets via MCP
- Single orchestrator agent (GestorGastos) that coordinates the workflow
- One Runner.run() call executes the entire flow

Pattern:
    categorizer_agent = create_categorizer_agent()
    validator_agent = create_validator_agent()
    persistence_agent = create_persistence_agent()
    categorizer_tool = categorizer_agent.as_tool(tool_name="categorize_expense", ...)
    validator_tool = validator_agent.as_tool(tool_name="validate_categorization", ...)
    persistence_tool = persistence_agent.as_tool(tool_name="save_expense", ...)
    orchestrator = Agent(tools=[categorizer_tool, validator_tool, persistence_tool, WebSearchTool()])
    result = await Runner.run(orchestrator, message)
"""

from src.agents.orchestrator import (
    OrchestratorAgent,
    create_categorizer_agent,
    create_expense_orchestrator,
    create_persistence_agent,
    create_validator_agent,
    get_orchestrator,
    process_receipt_with_agents,
)
from src.agents.prompts import (
    CATEGORIZER_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    PERSISTENCE_SYSTEM_PROMPT,
    get_validator_prompt,
    load_business_rules,
)
from src.agents.tools import (
    get_ranges,
    write_range,
)

__all__ = [
    # Orchestrator
    "OrchestratorAgent",
    "create_categorizer_agent",
    "create_validator_agent",
    "create_persistence_agent",
    "create_expense_orchestrator",
    "get_orchestrator",
    "process_receipt_with_agents",
    # Prompts
    "CATEGORIZER_SYSTEM_PROMPT",
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "PERSISTENCE_SYSTEM_PROMPT",
    "get_validator_prompt",
    "load_business_rules",
    # MCP Tools
    "get_ranges",
    "write_range",
]
