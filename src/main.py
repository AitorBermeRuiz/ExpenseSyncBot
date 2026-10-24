"""FastAPI application for ExpenseSyncBot.

This is the main entry point for the expense automation API.
It exposes the /process-receipt endpoint consumed by n8n and the
/transactions endpoint for real-time bank notifications.
"""

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.core.configs import settings
from src.core.logging import setup_logging
from src.expense_agents.constants import AGENT_TOOLS, FUNCTION_TOOLS
from src.expense_agents.orchestrator import process_receipt_with_agents
from src.ingestion import ingest, llm_categorize, parse_openbank
from src.ingestion.parsers import MADRID
from src.ingestion.service import Categorizer
from src.models.schemas import (
    CategorizedExpense,
    ExpenseCategory,
    MovementType,
    ProcessReceiptRequest,
    ProcessReceiptResponse,
    TransactionRequest,
    TransactionResponse,
)
from src.services.mcp_client import mcp_client
from src.services.sheets_client import (
    SheetsClient,
    SheetsError,
    service_account_token_provider,
)

NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ingestion not configured"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    Handles startup and shutdown events:
    - Startup: Initialize logging, connect to MCP server
    - Shutdown: Cleanup connections

    Note: API keys are exported to os.environ automatically when
    settings module is loaded (see src.core.configs).
    """
    # --- Startup ---
    setup_logging(settings.log_level)
    logger.info("Starting ExpenseSyncBot API")
    logger.info(f"Debug mode: {settings.debug}")

    # Initialize MCP client connection
    mcp_connected = await mcp_client.startup()
    if mcp_connected:
        logger.info("MCP server connection established")
    else:
        logger.warning(
            "MCP server not available. External tools (get_ranges, write_range) will fail. "
            "Ensure the C# MCP server is running."
        )

    yield

    # --- Shutdown ---
    logger.info("Shutting down ExpenseSyncBot API")
    await mcp_client.shutdown()


# Create FastAPI app
app = FastAPI(
    title="ExpenseSyncBot API",
    description="Agent-based expense automation service using OpenAI Agents SDK with MCP integration",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS middleware for n8n and other clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health Check Endpoints ---
@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": "ExpenseSyncBot",
        "mcp_connected": mcp_client.is_connected,
    }


@app.get("/health/detailed", tags=["Health"])
async def detailed_health_check() -> dict:
    """Detailed health check with component status."""
    mcp_tools = []
    if mcp_client.is_connected:
        try:
            mcp_tools = await mcp_client.get_available_tools()
        except Exception as e:
            logger.warning(f"Could not fetch MCP tools: {e}")

    return {
        "status": "healthy",
        "service": "ExpenseSyncBot",
        "components": {
            "api": "healthy",
            "mcp_server": "connected" if mcp_client.is_connected else "disconnected",
            "mcp_tools": [t["function"]["name"] for t in mcp_tools],
        },
        "config": {
            "orchestrator_provider": settings.orchestrator.llm_provider,
            "categorizer_provider": settings.orchestrator.categorizer_provider,
            "validator_provider": settings.orchestrator.validator_provider,
            "max_correction_attempts": settings.orchestrator.max_correction_attempts,
        },
    }


# --- Main API Endpoint ---
@app.post(
    "/process-receipt",
    response_model=ProcessReceiptResponse,
    tags=["Processing"],
    summary="Process a receipt email",
    description="Extracts expense data from email content and optionally persists it via MCP",
)
async def process_receipt(request: ProcessReceiptRequest) -> ProcessReceiptResponse:
    """Process a receipt email and extract expense data.

    This endpoint:
    1. Receives raw email content from n8n
    2. Uses AI to categorize and extract expense data
    3. Validates the extracted data
    4. Optionally persists via MCP AddExpense tool

    Args:
        request: ProcessReceiptRequest with email content

    Returns:
        ProcessReceiptResponse with processing result
    """
    logger.info("Received process-receipt request")
    logger.debug(f"Email subject: {request.email_subject}")
    logger.debug(f"Email body length: {len(request.email_body)} chars")

    try:
        result = await process_receipt_with_agents(
            email_body=request.email_body,
            email_subject=request.email_subject,
            sender=request.sender,
        )

        logger.info(f"Processing completed with status: {result.status}")
        return result

    except Exception as e:
        logger.exception(f"Error processing receipt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing receipt",
        )


# --- Real-time Ingestion ---
def require_token(x_api_token: str | None = Header(default=None)) -> None:
    """Reject requests without the shared ingestion token (fails closed if unset)."""
    expected = settings.ingest.api_token
    if not expected:
        raise NOT_CONFIGURED
    if x_api_token is None or not secrets.compare_digest(
        x_api_token.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


@lru_cache(maxsize=1)
def get_sheets_client() -> SheetsClient:
    """Build the Sheets client once (exceptions are not cached)."""
    ingest_settings = settings.ingest
    if (
        not ingest_settings.spreadsheet_id
        or not ingest_settings.google_credentials_file
    ):
        raise NOT_CONFIGURED
    return SheetsClient(
        ingest_settings.spreadsheet_id,
        service_account_token_provider(ingest_settings.google_credentials_file),
    )


def get_categorizer() -> Categorizer:
    """LLM fallback used when no "Reglas" row matches."""
    return llm_categorize


@app.post(
    "/transactions",
    response_model=TransactionResponse,
    tags=["Processing"],
    summary="Ingest a bank notification",
    dependencies=[Depends(require_token)],
)
async def ingest_transaction(
    request: TransactionRequest,
    sheets: SheetsClient = Depends(get_sheets_client),
    categorizer: Categorizer = Depends(get_categorizer),
) -> TransactionResponse:
    """Parse, deduplicate, categorize and append one bank movement."""
    # Never log raw_text: it may contain names.
    received_at = request.received_at or datetime.now(MADRID)
    tx = parse_openbank(request.raw_text, received_at)
    if tx is None:
        logger.info(
            f"Ignored transaction: source={request.source.value}, "
            f"length={len(request.raw_text)}"
        )
        return TransactionResponse(status="ignored")

    try:
        result = await ingest(tx, sheets, categorizer)
    except SheetsError as e:
        logger.error(f"Sheets write failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Sheets write failed"
        )

    if result.status == "duplicate":
        return TransactionResponse(status="duplicate")
    fecha, tipo, categoria, importe, descripcion, _ = result.row
    return TransactionResponse(
        status="saved",
        data=CategorizedExpense(
            fecha=fecha,
            tipo=MovementType(tipo),
            categoria=ExpenseCategory(categoria),
            importe=importe,
            descripcion=descripcion,
        ),
        sheet_range=result.updated_range,
    )


# --- Utility Endpoints ---
@app.get("/tools", tags=["Tools"])
async def list_available_tools() -> dict:
    """List all available tools (agent-tools + function-tools + MCP)."""
    # MCP tools (from external C# server)
    mcp_tools = []
    try:
        mcp_tool_schemas = await mcp_client.get_available_tools()
        mcp_tools = [t["function"]["name"] for t in mcp_tool_schemas]
    except Exception as e:
        logger.warning(f"Could not fetch MCP tools: {e}")

    return {
        "agent_tools": AGENT_TOOLS,
        "function_tools": FUNCTION_TOOLS,
        "mcp_tools": mcp_tools,
        "total": len(AGENT_TOOLS) + len(FUNCTION_TOOLS) + len(mcp_tools),
        "architecture": "OpenAI Agents SDK with .as_tool() pattern",
    }


# --- Entry point for uvicorn ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
