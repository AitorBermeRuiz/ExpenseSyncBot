"""Orchestrator agent for expense processing.

This module implements the main orchestration logic using OpenAI's
Chat Completions API with function calling. The orchestrator coordinates:
1. Receipt categorization
2. Expense validation
3. Correction loop on validation failures
4. Persistence via MCP tools
"""

import json
from typing import Any

from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageToolCall

from src.agents.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from src.agents.tools import categorize_receipt, validate_expense_from_dict
from src.core.configs import settings
from src.core.llm_manager import llm_manager
from src.models.schemas import (
    CATEGORIZE_RECEIPT_SCHEMA,
    VALIDATE_EXPENSE_SCHEMA,
    CategorizedExpense,
    ProcessingStatus,
    ProcessReceiptResponse,
)
from src.services.mcp_client import mcp_client


class OrchestratorAgent:
    """Agent that orchestrates the receipt processing workflow.

    Uses OpenAI function calling to coordinate between:
    - Internal Python tools (categorize, validate)
    - External MCP tools (AddExpense)
    """

    def __init__(self) -> None:
        self._orchestrator_provider = settings.orchestrator.llm_provider
        self._categorizer_provider = settings.orchestrator.categorizer_provider
        self._max_attempts = settings.orchestrator.max_correction_attempts

        # Get clients
        self._orchestrator_client = llm_manager.get_client(self._orchestrator_provider)
        self._categorizer_client = llm_manager.get_client(self._categorizer_provider)

        if not self._orchestrator_client:
            raise RuntimeError(
                f"Failed to initialize orchestrator LLM client for provider: "
                f"{self._orchestrator_provider}"
            )

        # Use orchestrator client for categorization if categorizer not available
        if not self._categorizer_client:
            logger.warning(
                f"Categorizer provider '{self._categorizer_provider}' not available, "
                f"falling back to orchestrator provider"
            )
            self._categorizer_client = self._orchestrator_client
            self._categorizer_model = llm_manager.get_model_name(self._orchestrator_provider)
        else:
            self._categorizer_model = llm_manager.get_model_name(self._categorizer_provider)

        self._orchestrator_model = llm_manager.get_model_name(self._orchestrator_provider)

    async def _get_tools(self) -> list[dict[str, Any]]:
        """Get all available tools (internal + MCP).

        Returns:
            List of tool schemas in OpenAI format
        """
        tools = [
            CATEGORIZE_RECEIPT_SCHEMA,
            VALIDATE_EXPENSE_SCHEMA,
        ]

        # Add MCP tools if available
        mcp_tools = await mcp_client.get_available_tools()
        tools.extend(mcp_tools)

        return tools

    async def _execute_tool(
        self,
        tool_call: ChatCompletionMessageToolCall,
        email_text: str,
        current_expense: CategorizedExpense | None,
    ) -> tuple[str, CategorizedExpense | None]:
        """Execute a tool call and return the result.

        Args:
            tool_call: The tool call from OpenAI
            email_text: Original email text for categorization
            current_expense: Current expense data if available

        Returns:
            Tuple of (result_string, updated_expense)
        """
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        logger.info(f"Executing tool: {tool_name}")
        logger.debug(f"Tool arguments: {arguments}")

        # Normalize tool name for comparison (handle case sensitivity)
        tool_name_lower = tool_name.lower()

        if tool_name_lower == "categorize_receipt":
            # Use the categorizer client for this tool
            text = arguments.get("text", email_text)
            feedback = arguments.get("feedback")

            result = await categorize_receipt(
                client=self._categorizer_client,
                model=self._categorizer_model,
                text=text,
                feedback=feedback,
            )

            if result.success and result.expense:
                current_expense = result.expense
                return json.dumps({
                    "success": True,
                    "expense": result.expense.model_dump(mode="json"),
                }), current_expense
            else:
                return json.dumps({
                    "success": False,
                    "error": result.error,
                }), current_expense

        elif tool_name_lower == "validate_expense":
            result = validate_expense_from_dict(arguments)
            return json.dumps({
                "is_valid": result.result.is_valid,
                "error_message": result.result.error_message,
                "warnings": result.result.warnings,
            }), current_expense

        else:
            # Any other tool is assumed to be an MCP tool (e.g., AddExpense, add_expense)
            # Use the original tool_name to preserve the exact casing the MCP server expects
            logger.info(f"Delegating to MCP tool: {tool_name}")
            result = await mcp_client.call_tool(tool_name, arguments)
            return json.dumps(result), current_expense

    async def process_receipt(
        self,
        email_body: str,
        email_subject: str | None = None,
        sender: str | None = None,
    ) -> ProcessReceiptResponse:
        """Process a receipt email through the full workflow.

        Args:
            email_body: Raw email body content
            email_subject: Optional email subject
            sender: Optional sender address

        Returns:
            ProcessReceiptResponse with processing result
        """
        logger.info("Starting receipt processing")

        errors: list[str] = []
        attempts = 0
        current_expense: CategorizedExpense | None = None

        # Build initial context
        context = f"Email Body:\n{email_body}"
        if email_subject:
            context = f"Subject: {email_subject}\n\n{context}"
        if sender:
            context = f"From: {sender}\n{context}"

        # Get available tools
        tools = await self._get_tools()
        logger.debug(f"Available tools: {[t['function']['name'] for t in tools]}")

        # Initialize conversation
        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Procesa el siguiente recibo de email:\n\n{context}",
            },
        ]

        # Main orchestration loop
        max_iterations = 10  # Safety limit
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Orchestration iteration {iteration}")

            try:
                response = await self._orchestrator_client.chat.completions.create(
                    model=self._orchestrator_model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1,
                )

                message = response.choices[0].message

                # Check if we're done (no tool calls)
                if not message.tool_calls:
                    logger.info("Orchestrator finished processing")

                    # Determine final status based on what we have
                    if current_expense:
                        return ProcessReceiptResponse(
                            status=ProcessingStatus.SUCCESS,
                            message="Recibo procesado exitosamente",
                            data=current_expense.model_dump(mode="json"),
                            attempts=attempts,
                            errors=errors,
                        )
                    else:
                        return ProcessReceiptResponse(
                            status=ProcessingStatus.CATEGORIZATION_FAILED,
                            message=message.content or "No se pudo extraer información del recibo",
                            attempts=attempts,
                            errors=errors,
                        )

                # Add assistant message to history
                messages.append(message.model_dump(exclude_none=True))

                # Process tool calls
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "categorize_receipt":
                        attempts += 1

                        if attempts > self._max_attempts:
                            logger.warning(f"Max categorization attempts ({self._max_attempts}) reached")
                            return ProcessReceiptResponse(
                                status=ProcessingStatus.CATEGORIZATION_FAILED,
                                message=f"Máximo de intentos alcanzado ({self._max_attempts})",
                                attempts=attempts,
                                errors=errors,
                            )

                    # Execute the tool
                    result_str, current_expense = await self._execute_tool(
                        tool_call,
                        email_body,
                        current_expense,
                    )

                    # Check for errors in validation
                    try:
                        result_data = json.loads(result_str)
                        if "error" in result_data and result_data.get("error"):
                            errors.append(result_data["error"])
                        if "error_message" in result_data and result_data.get("error_message"):
                            errors.append(result_data["error_message"])
                    except json.JSONDecodeError:
                        pass

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    })

            except Exception as e:
                logger.exception(f"Error in orchestration loop: {e}")
                errors.append(str(e))
                return ProcessReceiptResponse(
                    status=ProcessingStatus.ERROR,
                    message=f"Error interno: {e}",
                    attempts=attempts,
                    errors=errors,
                )

        # Max iterations reached
        logger.warning("Max orchestration iterations reached")
        return ProcessReceiptResponse(
            status=ProcessingStatus.ERROR,
            message="Se alcanzó el límite de iteraciones del orquestador",
            data=current_expense.model_dump(mode="json") if current_expense else None,
            attempts=attempts,
            errors=errors,
        )


# Factory function for dependency injection
async def get_orchestrator() -> OrchestratorAgent:
    """Factory function to create orchestrator instance.

    Returns:
        Configured OrchestratorAgent instance
    """
    return OrchestratorAgent()
