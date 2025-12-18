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


# --- Internal Data Models (Structured Outputs) ---
class CategorizedExpense(BaseModel):
    """Expense data extracted from a receipt or bank notification.

    This model is used as output_type for the Categorizer Agent,
    ensuring structured and validated output from the LLM.
    """

    fecha: str = Field(
        ...,
        description=(
            "Fecha de la transacción en formato DD/MM/YYYY. "
            "Ejemplo: '05/11/2025'. Si no hay fecha en el texto, usa la fecha actual."
        ),
    )
    tipo: MovementType = Field(
        ...,
        description=(
            "Tipo de movimiento: 'Gasto' si es un pago/cargo/compra, "
            "'Ingreso' si es dinero recibido (bizum recibido, transferencia entrante, etc.)"
        ),
    )
    categoria: ExpenseCategory = Field(
        ...,
        description=(
            "Categoría del gasto/ingreso. Opciones: Alimentación (supermercados), "
            "Transporte (gasolina, parking, taxi), Ocio (restaurantes, cine, deportes), "
            "Hogar (muebles, limpieza), Ropa (textil, calzado), Inversiones (libros, cursos), "
            "Suscripciones (Netflix, Spotify, iCloud), Ahorros (transferencias a ahorro), "
            "Otros (si no encaja en ninguna)."
        ),
    )
    importe: str = Field(
        ...,
        description=(
            "Importe con coma decimal española, sin símbolo de moneda. "
            "Ejemplos: '15,67', '362,00', '2,99'. Solo el número."
        ),
    )
    descripcion: str = Field(
        ...,
        description=(
            "Formato: 'Nombre comercio - tipo servicio/producto' (max 50 chars). "
            "SIEMPRE especifica qué es: 'Mercadona - supermercado' "
            " 'Apple - iCloud almacenamiento'."
        ),
    )


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


class OrchestratorResult(BaseModel):
    """Structured output from the main orchestrator agent.

    This model is used as output_type for the Orchestrator Agent,
    ensuring robust and type-safe results instead of parsing free text.
    """

    success: bool = Field(
        ...,
        description=(
            "True if the expense was successfully processed and saved, "
            "False if there was an error at any stage"
        ),
    )
    expense_data: CategorizedExpense | None = Field(
        default=None,
        description="The final categorized and validated expense data (null if failed)",
    )
    error_message: str | None = Field(
        default=None,
        description="Error description if success is False (null if successful)",
    )
    sheet_row: str | None = Field(
        default=None,
        description=(
            "The row where the expense was saved in Google Sheets (e.g., 'Gastos!A55:E55'). "
            "Null if not saved or if save failed."
        ),
    )
