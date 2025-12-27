"""Orchestrator agent for expense processing using OpenAI Agents SDK.

This module implements the expense processing workflow using the correct
Agent pattern: specialized agents converted to tools via .as_tool() and
passed to a main orchestrator agent.

Architecture:
1. Categorizer Agent (GPT): Extracts and categorizes expenses from email text
2. Validator Agent (Gemini): Validates categorization with business rules
3. Persistence Agent: Writes to Google Sheets via MCP (get_ranges, write_range)
4. Orchestrator: Coordinates all agents + WebSearchTool for unknown merchants

Pattern:
    categorizer_tool = categorizer_agent.as_tool(...)
    validator_tool = validator_agent.as_tool(...)
    persistence_tool = persistence_agent.as_tool(...)
    orchestrator = Agent(tools=[categorizer_tool, validator_tool, persistence_tool, WebSearchTool()])
    result = await Runner.run(orchestrator, message)
"""

from agents import Agent, Runner, ModelSettings, WebSearchTool, trace
from loguru import logger

from src.expense_agents.constants import (
    TOOL_CATEGORIZE_EXPENSE,
    TOOL_SAVE_EXPENSE,
    TOOL_VALIDATE_CATEGORIZATION,
)
from src.expense_agents.prompts import (
    CATEGORIZER_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    PERSISTENCE_SYSTEM_PROMPT,
    get_validator_prompt,
)
from src.expense_agents.tools import get_next_row, get_ranges, write_range
from src.core.configs import settings
from src.core.llm_manager import llm_manager
from src.models.schemas import (
    CategorizedExpense,
    OrchestratorResult,
    ProcessingStatus,
    ProcessReceiptResponse,
    ValidationResult,
)


# --- Specialized Agents ---
def create_categorizer_agent() -> Agent:
    """Create the receipt categorizer agent (GPT) with Structured Output.

    This agent specializes in extracting structured expense data from
    messy receipt emails (HTML, signatures, noise) and categorizing them.

    Uses output_type=CategorizedExpense to enforce structured, validated output
    directly from the LLM, eliminating manual JSON parsing.

    Returns:
        Agent configured with GPT model for categorization and structured output
    """
    provider = settings.orchestrator.categorizer_provider
    model = llm_manager.get_model(provider)

    if not model:
        raise RuntimeError(
            f"Could not create model for categorizer provider: {provider}. "
            f"Check that the API key is configured."
        )

    return Agent(
        name="CategorizadorGastos",
        instructions=CATEGORIZER_SYSTEM_PROMPT,
        model=model,
        model_settings=ModelSettings(temperature=0.1),
        output_type=CategorizedExpense,
    )


def create_validator_agent() -> Agent:
    """Create the expense validator agent (Gemini).

    This agent validates categorized expenses against business rules
    and provides corrections if needed.

    Returns:
        Agent configured with Gemini model for validation
    """
    provider = settings.orchestrator.validator_provider
    model = llm_manager.get_model(provider)

    if not model:
        raise RuntimeError(
            f"Could not create model for validator provider: {provider}. "
            f"Check that the API key is configured."
        )

    return Agent(
        name="ValidadorGastos",
        instructions=get_validator_prompt(),
        model=model,
        model_settings=ModelSettings(temperature=0.0),
        output_type=ValidationResult,
    )


def create_persistence_agent() -> Agent:
    """Create the persistence agent for Google Sheets.

    This agent handles writing expenses to Google Sheets via MCP tools.
    It uses get_ranges to find the next empty row and write_range to persist.

    Returns:
        Agent configured with MCP tools for Google Sheets
    """
    provider = settings.orchestrator.llm_provider
    model = llm_manager.get_model(provider)

    if not model:
        raise RuntimeError(
            f"Could not create model for persistence provider: {provider}. "
            f"Check that the API key is configured."
        )

    return Agent(
        name="PersistenciaGastos",
        instructions=PERSISTENCE_SYSTEM_PROMPT,
        model=model,
        model_settings=ModelSettings(temperature=0.0),
        tools=[get_next_row, get_ranges, write_range],
    )


# --- Main Orchestrator Setup ---
def create_expense_orchestrator() -> Agent:
    """Create the main expense orchestrator agent.

    This agent:
    1. Has access to the categorizer agent as a tool (.as_tool())
    2. Has access to the validator agent as a tool (.as_tool())
    3. Has access to the persistence agent as a tool (.as_tool())
    4. Has access to WebSearchTool for unknown merchants
    5. Coordinates the full workflow: categorize → validate → (retry) → persist

    Returns:
        Configured orchestrator Agent with all tools
    """
    # Create specialized agents
    categorizer_agent = create_categorizer_agent()
    validator_agent = create_validator_agent()
    persistence_agent = create_persistence_agent()

    # Convert agents to tools using .as_tool()
    categorizer_tool = categorizer_agent.as_tool(
        tool_name=TOOL_CATEGORIZE_EXPENSE,
        tool_description=(
            "Extrae y categoriza los datos de un gasto desde el texto de un email/notificación bancaria. "
            "Devuelve un objeto estructurado con: fecha (DD/MM/YYYY), tipo (Gasto/Ingreso), categoria, importe (con coma decimal), descripcion. "
            "Pásale el contenido completo del email o notificación. "
            "Si la validación falla, llama de nuevo a esta herramienta pasando el mensaje de error (feedback) "
            "junto con el texto original para corregirlo. Formato: 'FEEDBACK: [mensaje de error]\\nTEXTO ORIGINAL: [texto]'"
        ),
    )

    validator_tool = validator_agent.as_tool(
        tool_name=TOOL_VALIDATE_CATEGORIZATION,
        tool_description=(
            "Valida si la categorización de un gasto es correcta según las reglas de negocio. "
            "Pásale los datos del gasto: descripcion, categoria, tipo. "
            "Devuelve: is_valid, feedback, corrected_category, corrected_type."
        ),
    )

    persistence_tool = persistence_agent.as_tool(
        tool_name=TOOL_SAVE_EXPENSE,
        tool_description=(
            "Guarda un gasto validado en Google Sheets. "
            "Pásale los datos completos del gasto: fecha, tipo, categoria, importe, descripcion. "
            "Primero lee las filas existentes para encontrar la siguiente fila vacía, luego escribe."
        ),
    )

    # Combine agent-tools with utility tools
    tools = [
        categorizer_tool,      # Agent as tool (.as_tool())
        validator_tool,        # Agent as tool (.as_tool())
        persistence_tool       # Agent as tool (.as_tool())
                               # For unknown merchants
    ]

    # Get orchestrator model
    provider = settings.orchestrator.llm_provider
    model = llm_manager.get_model(provider)

    if not model:
        raise RuntimeError(
            f"Could not create model for orchestrator provider: {provider}. "
            f"Check that the API key is configured."
        )

    return Agent(
        name="GestorGastos",
        instructions=ORCHESTRATOR_SYSTEM_PROMPT,
        model=model,
        model_settings=ModelSettings(temperature=0.1),
        tools=tools,
        output_type=OrchestratorResult,
    )


# --- Main Processing Function ---
async def process_receipt_with_agents(
    email_body: str,
    email_subject: str | None = None,
    sender: str | None = None,
) -> ProcessReceiptResponse:
    """Process a receipt email using the agent-based workflow.

    Single Runner.run() call that executes the entire workflow:
    categorize → validate → (retry if needed) → persist

    Args:
        email_body: Raw email body content
        email_subject: Optional email subject
        sender: Optional sender address

    Returns:
        ProcessReceiptResponse with the processing result
    """
    logger.info("Starting agent-based receipt processing")

    # Build the message for the orchestrator
    context_parts = []
    if sender:
        context_parts.append(f"De: {sender}")
    if email_subject:
        context_parts.append(f"Asunto: {email_subject}")
    context_parts.append(f"\nContenido del email:\n\n{email_body}")

    message = f"""Procesa el siguiente movimiento bancario/recibo y guárdalo en Google Sheets:
    {chr(10).join(context_parts)}
    """

    # Create the orchestrator with all tools
    orchestrator = create_expense_orchestrator()

    try:
        # Single Runner.run() call - the orchestrator handles the full workflow
        with trace("ExpenseProcessing"):
            result = await Runner.run(orchestrator, message)

        # Get structured output from the orchestrator
        orchestrator_result: OrchestratorResult = result.final_output

        if not orchestrator_result:
            logger.error("Orchestrator returned no output")
            return ProcessReceiptResponse(
                status=ProcessingStatus.ERROR,
                message="El orquestador no devolvió respuesta",
                attempts=1,
                errors=["No output from orchestrator"],
            )

        logger.info(f"Orchestrator finished. Success: {orchestrator_result.success}")

        # Map OrchestratorResult to ProcessReceiptResponse
        if orchestrator_result.success:
            # Build success message
            if orchestrator_result.sheet_row and orchestrator_result.expense_data:
                message = (
                    f"Gasto guardado exitosamente en {orchestrator_result.sheet_row}: "
                    f"{orchestrator_result.expense_data.descripcion} - "
                    f"{orchestrator_result.expense_data.importe}€ "
                    f"({orchestrator_result.expense_data.categoria})"
                )
            else:
                message = "Gasto procesado exitosamente"

            # Prepare expense data for response
            expense_dict = (
                orchestrator_result.expense_data.model_dump()
                if orchestrator_result.expense_data
                else None
            )

            return ProcessReceiptResponse(
                status=ProcessingStatus.SUCCESS,
                message=message,
                data=expense_dict,
                attempts=1,
                errors=[],
            )
        else:
            # Handle error case
            error_msg = orchestrator_result.error_message or "Error desconocido en el procesamiento"
            logger.error(f"Orchestrator reported error: {error_msg}")

            return ProcessReceiptResponse(
                status=ProcessingStatus.ERROR,
                message=error_msg,
                data=None,
                attempts=1,
                errors=[error_msg],
            )

    except Exception as e:
        logger.exception(f"Error in orchestrator: {e}")
        return ProcessReceiptResponse(
            status=ProcessingStatus.ERROR,
            message=f"Error interno: {e}",
            attempts=1,
            errors=[str(e)],
        )


# --- FastAPI Compatibility Layer ---
class OrchestratorAgent:
    """Wrapper class for compatibility with existing FastAPI dependency injection."""

    def __init__(self) -> None:
        logger.info(
            f"OrchestratorAgent initialized - "
            f"orchestrator: {settings.orchestrator.llm_provider}, "
            f"categorizer: {settings.orchestrator.categorizer_provider}, "
            f"validator: {settings.orchestrator.validator_provider}"
        )

    async def process_receipt(
        self,
        email_body: str,
        email_subject: str | None = None,
        sender: str | None = None,
    ) -> ProcessReceiptResponse:
        """Process a receipt email through the agent workflow."""
        return await process_receipt_with_agents(
            email_body=email_body,
            email_subject=email_subject,
            sender=sender,
        )


async def get_orchestrator() -> OrchestratorAgent:
    """Factory function to create orchestrator instance."""
    return OrchestratorAgent()
