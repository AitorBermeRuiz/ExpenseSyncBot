"""Pydantic schemas for request/response models and internal data structures.

Note: With the OpenAI Agents SDK, tool schemas are auto-generated from
@function_tool decorated functions. Manual schemas are no longer needed.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExpenseCategory(str, Enum):
    """Supported expense categories."""

    ALIMENTACION = "Alimentación"
    TRANSPORTE = "Transporte"
    OCIO = "Ocio"
    HOGAR = "Hogar"
    ROPA = "Ropa"
    INVERSIONES = "Inversiones"
    SUSCRIPCIONES = "Suscripciones"
    OTROS = "Otros"
    AHORROS = "Ahorros"


class MovementType(str, Enum):
    """Type of financial movement."""

    GASTO = "Gasto"
    INGRESO = "Ingreso"


class ProcessingStatus(str, Enum):
    """Status of receipt processing."""

    SUCCESS = "success"
    VALIDATION_FAILED = "validation_failed"
    CATEGORIZATION_FAILED = "categorization_failed"
    MCP_ERROR = "mcp_error"
    ERROR = "error"


# --- Request/Response Models (FastAPI) ---
class ProcessReceiptRequest(BaseModel):
    """Request body for processing a receipt email."""

    email_body: str = Field(
        ...,
        description="Raw email body content (may contain HTML)",
        min_length=1,
    )
    email_subject: str | None = Field(
        default=None,
        description="Email subject line for additional context",
    )
    sender: str | None = Field(
        default=None,
        description="Sender email address",
    )


class ProcessReceiptResponse(BaseModel):
    """Response from receipt processing endpoint."""

    status: ProcessingStatus = Field(..., description="Processing result status")
    message: str = Field(..., description="Human-readable status message")
    data: dict[str, Any] | None = Field(
        default=None,
        description="Processed expense data if successful",
    )
    attempts: int = Field(
        default=1,
        description="Number of categorization attempts made",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="List of errors encountered during processing",
    )


# --- Internal Data Models ---
class CategorizedExpense(BaseModel):
    """Expense data extracted from receipt.

    Used internally after categorization, with Spanish format:
    - Date: DD/MM/YYYY
    - Amount: comma decimal (362,67)
    """

    fecha: str = Field(..., description="Transaction date in DD/MM/YYYY format")
    tipo: MovementType = Field(..., description="Movement type: Gasto or Ingreso")
    categoria: ExpenseCategory = Field(..., description="Expense category")
    importe: str = Field(..., description="Amount with Spanish comma decimal (e.g., 362,67)")
    descripcion: str = Field(..., description="Brief description or merchant name")


class ValidationResult(BaseModel):
    """Result of expense validation by Gemini."""

    is_valid: bool = Field(..., description="Whether the categorization is correct")
    feedback: str | None = Field(
        default=None,
        description="Explanation if categorization is wrong",
    )
    corrected_category: str | None = Field(
        default=None,
        description="Correct category if original was wrong",
    )
    corrected_type: str | None = Field(
        default=None,
        description="Correct type if original was wrong",
    )
