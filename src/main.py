"""FastAPI application for ExpenseSyncBot.

This is the main entry point for the expense automation API.
It exposes the /process-receipt endpoint consumed by n8n.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.agents.orchestrator import OrchestratorAgent, get_orchestrator
from src.core.configs import settings
from src.core.logging import setup_logging
from src.models.schemas import (
    ProcessingStatus,
    ProcessReceiptRequest,
    ProcessReceiptResponse,
)
from src.services.mcp_client import mcp_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    Handles startup and shutdown events:
    - Startup: Initialize logging, connect to MCP server
    - Shutdown: Cleanup connections
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
            "MCP server not available. External tools (AddExpense) will fail. "
            "Ensure the C# MCP server is running."
        )

    yield

    # --- Shutdown ---
    logger.info("Shutting down ExpenseSyncBot API")
    await mcp_client.shutdown()


# Create FastAPI app
app = FastAPI(
    title="ExpenseSyncBot API",
    description="Agent-based expense automation service with MCP integration",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS middleware for n8n and other clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
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
async def process_receipt(
    request: ProcessReceiptRequest,
    orchestrator: OrchestratorAgent = Depends(get_orchestrator),
) -> ProcessReceiptResponse:
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
        result = await orchestrator.process_receipt(
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
            detail=f"Error processing receipt: {str(e)}",
        )


# --- Utility Endpoints ---
@app.get("/tools", tags=["Tools"])
async def list_available_tools() -> dict:
    """List all available tools (internal + MCP)."""
    internal_tools = ["categorize_receipt", "validate_expense"]

    mcp_tools = []
    try:
        mcp_tool_schemas = await mcp_client.get_available_tools()
        mcp_tools = [t["function"]["name"] for t in mcp_tool_schemas]
    except Exception as e:
        logger.warning(f"Could not fetch MCP tools: {e}")

    return {
        "internal_tools": internal_tools,
        "mcp_tools": mcp_tools,
        "total": len(internal_tools) + len(mcp_tools),
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
