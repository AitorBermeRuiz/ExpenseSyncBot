"""Validation Agent - Double-checks categorizations with custom rules."""

from typing import Optional

from agents import Agent, function_tool

from src.models.transaction import Transaction, TransactionAction


VALIDATION_INSTRUCTIONS = """Eres un agente validador de categorizaciones de gastos.

Tu trabajo es revisar las categorizaciones hechas por otro agente y:
1. Verificar que la categoría asignada es correcta
2. Detectar errores comunes
3. Aplicar reglas de negocio específicas

## ERRORES COMUNES A DETECTAR:
- Transferencias entre cuentas propias marcadas como gastos
- Bizum a familiares/amigos categorizados como gastos reales
- Devoluciones no identificadas
- Suscripciones mal categorizadas (Netflix es Ocio, no Tecnología)
- Supermercados que venden más que comida (Carrefour electrodomésticos)

## REGLAS DE NEGOCIO:
- Las transferencias internas SIEMPRE deben ser "skip"
- Los Bizum sin contexto comercial deben ser "review"
- Amazon puede ser múltiples categorías según el producto
- Las comisiones bancarias van a "Finanzas"

## CUÁNDO CAMBIAR:
- Solo cambia si estás SEGURO de que hay un error
- Si tienes dudas, cambia a "review" en lugar de adivinar
- Documenta siempre el motivo del cambio

Usa la herramienta `validate_categorization` para cada transacción que revises."""


@function_tool
def validate_categorization(
    transaction_id: str,
    is_valid: bool,
    corrected_category: str = "",
    corrected_action: str = "",
    validation_notes: str = ""
) -> dict:
    """
    Validate or correct a transaction's categorization.
    
    Args:
        transaction_id: The unique ID of the transaction
        is_valid: Whether the current categorization is correct
        corrected_category: New category if the original was wrong
        corrected_action: New action (register/skip/review) if needed
        validation_notes: Explanation of the validation decision
    
    Returns:
        Validation result
    """
    return {
        "transaction_id": transaction_id,
        "is_valid": is_valid,
        "corrected_category": corrected_category,
        "corrected_action": corrected_action,
        "validation_notes": validation_notes,
        "status": "validated"
    }


@function_tool  
def flag_for_manual_review(
    transaction_id: str,
    reason: str
) -> dict:
    """
    Flag a transaction for manual review by the user.
    
    Args:
        transaction_id: The unique ID of the transaction
        reason: Why this needs manual review
    
    Returns:
        Confirmation of the flag
    """
    return {
        "transaction_id": transaction_id,
        "flagged": True,
        "reason": reason,
        "status": "flagged_for_review"
    }


class ValidationAgent:
    """Agent that validates and corrects categorizations."""
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        custom_rules: Optional[str] = None
    ):
        self.model = model
        
        instructions = VALIDATION_INSTRUCTIONS
        if custom_rules:
            instructions += f"\n\n## REGLAS PERSONALIZADAS:\n{custom_rules}"
        
        self.agent = Agent(
            name="ValidadorGastos",
            instructions=instructions,
            model=model,
            tools=[validate_categorization, flag_for_manual_review]
        )
    
    def get_agent(self) -> Agent:
        """Return the underlying Agent instance."""
        return self.agent
    
    def format_validation_prompt(self, transactions: list[Transaction]) -> str:
        """Format categorized transactions for validation."""
        lines = ["Valida las siguientes categorizaciones:\n"]
        
        for tx in transactions:
            lines.append(
                f"- ID: {tx.id}\n"
                f"  Descripción: {tx.description}\n"
                f"  Importe: {tx.amount} {tx.currency}\n"
                f"  Categoría asignada: {tx.category}\n"
                f"  Acción asignada: {tx.action.value}\n"
                f"  Notas: {tx.notes or 'Ninguna'}\n"
            )
        
        lines.append(
            "\nRevisa cada una y usa validate_categorization para confirmar "
            "o corregir. Usa flag_for_manual_review si necesita revisión humana."
        )
        return "\n".join(lines)
