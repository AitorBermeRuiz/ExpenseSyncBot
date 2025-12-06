"""Pydantic schemas for request/response models and internal data structures."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExpenseCategory(str, Enum):
    """Supported expense categories."""

    ALIMENTACION = "alimentacion"
    TRANSPORTE = "transporte"
    ENTRETENIMIENTO = "entretenimiento"
    SALUD = "salud"
    HOGAR = "hogar"
    ROPA = "ropa"
    TECNOLOGIA = "tecnologia"
    EDUCACION = "educacion"
    VIAJES = "viajes"
    RESTAURANTES = "restaurantes"
    SUPERMERCADO = "supermercado"
    SERVICIOS = "servicios"
    SUSCRIPCIONES = "suscripciones"
    OTROS = "otros"


class ProcessingStatus(str, Enum):
    """Status of receipt processing."""

    SUCCESS = "success"
    VALIDATION_FAILED = "validation_failed"
    CATEGORIZATION_FAILED = "categorization_failed"
    MCP_ERROR = "mcp_error"
    ERROR = "error"


# --- Request/Response Models ---
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
    """Expense data extracted from receipt."""

    comercio: str = Field(..., description="Merchant/business name")
    importe: Decimal = Field(..., description="Amount in original currency", gt=0)
    moneda: str = Field(default="EUR", description="Currency code")
    fecha: date = Field(..., description="Transaction date")
    categoria: ExpenseCategory = Field(..., description="Expense category")
    descripcion: str | None = Field(
        default=None,
        description="Additional description or notes",
    )
    confianza: float = Field(
        default=1.0,
        description="Confidence score of categorization (0-1)",
        ge=0,
        le=1,
    )

    class Config:
        json_encoders = {
            Decimal: lambda v: float(v),
            date: lambda v: v.isoformat(),
        }


class ValidationResult(BaseModel):
    """Result of expense validation."""

    is_valid: bool = Field(..., description="Whether the expense passes validation")
    error_message: str | None = Field(
        default=None,
        description="Error message if validation failed",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking warnings",
    )


# --- Tool Response Models ---
class CategorizationToolResponse(BaseModel):
    """Response from categorize_receipt tool."""

    success: bool
    expense: CategorizedExpense | None = None
    error: str | None = None


class ValidationToolResponse(BaseModel):
    """Response from validate_expense tool."""

    result: ValidationResult


class AddExpenseToolResponse(BaseModel):
    """Response from MCP AddExpense tool."""

    success: bool
    expense_id: str | None = None
    error: str | None = None


# --- OpenAI Tool Schemas ---
CATEGORIZE_RECEIPT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "categorize_receipt",
        "description": "Extract and categorize expense information from receipt email text. Use this to parse raw email content into structured expense data.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The raw email body text containing the receipt",
                },
                "feedback": {
                    "type": "string",
                    "description": "Optional feedback from previous validation failure to guide correction",
                },
            },
            "required": ["text"],
        },
    },
}

VALIDATE_EXPENSE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "validate_expense",
        "description": "Validate categorized expense data against business rules. Call this after categorization to ensure data integrity.",
        "parameters": {
            "type": "object",
            "properties": {
                "comercio": {"type": "string", "description": "Merchant name"},
                "importe": {"type": "number", "description": "Amount"},
                "moneda": {"type": "string", "description": "Currency code"},
                "fecha": {"type": "string", "description": "Date in ISO format (YYYY-MM-DD)"},
                "categoria": {"type": "string", "description": "Expense category"},
                "descripcion": {"type": "string", "description": "Optional description"},
            },
            "required": ["comercio", "importe", "fecha", "categoria"],
        },
    },
}
