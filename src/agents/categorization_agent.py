"""Categorization Agent - Classifies transactions into expense categories."""

from agents import Agent, function_tool

from src.models.transaction import Transaction, TransactionAction


CATEGORIZATION_INSTRUCTIONS = """Eres un agente experto en categorización de gastos personales.

Tu tarea es analizar transacciones bancarias y para cada una:
1. Asignar una categoría apropiada
2. Decidir la acción: register (registrar), skip (omitir), o review (revisar)

## CATEGORÍAS DISPONIBLES:
- Alimentación: supermercados, restaurantes, comida rápida, delivery
- Transporte: gasolina, transporte público, parking, peajes, Uber/Cabify
- Hogar: alquiler, hipoteca, suministros (luz, agua, gas), seguros hogar
- Salud: farmacia, médicos, seguro médico, dentista
- Ocio: entretenimiento, cine, suscripciones streaming, viajes, bares
- Ropa: tiendas de ropa, calzado, accesorios
- Tecnología: electrónica, software, suscripciones tech (GitHub, cloud)
- Educación: cursos, libros, formación, idiomas
- Finanzas: transferencias entre cuentas, comisiones bancarias
- Otros: cualquier cosa que no encaje en las anteriores

## REGLAS DE DECISIÓN:
- **register**: Gastos normales que deben registrarse en el presupuesto
- **skip**: Transferencias entre cuentas propias, devoluciones, movimientos internos, Bizum a conocidos
- **review**: Transacciones dudosas, importes inusuales, o que necesitan verificación manual

## IMPORTANTE:
- Analiza el campo "description" y "merchant" para determinar la categoría
- Los importes negativos son gastos, positivos son ingresos
- Sé consistente: el mismo comercio siempre debe tener la misma categoría
- Si no estás seguro, usa "review" en lugar de adivinar

Usa la herramienta `categorize_transaction` para cada transacción que recibas."""


@function_tool
def categorize_transaction(
    transaction_id: str,
    category: str,
    action: str,
    skip_reason: str = "",
    notes: str = ""
) -> dict:
    """
    Categorize a single transaction.
    
    Args:
        transaction_id: The unique ID of the transaction
        category: The expense category (Alimentación, Transporte, Hogar, etc.)
        action: What to do with the transaction (register, skip, review)
        skip_reason: If action is 'skip', explain why
        notes: Additional notes about the categorization
    
    Returns:
        Confirmation of the categorization
    """
    return {
        "transaction_id": transaction_id,
        "category": category,
        "action": action,
        "skip_reason": skip_reason,
        "notes": notes,
        "status": "categorized"
    }


class CategorizationAgent:
    """Agent that categorizes bank transactions."""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.agent = Agent(
            name="CategorizadorGastos",
            instructions=CATEGORIZATION_INSTRUCTIONS,
            model=model,
            tools=[categorize_transaction]
        )
    
    def get_agent(self) -> Agent:
        """Return the underlying Agent instance."""
        return self.agent
    
    def format_transactions_prompt(self, transactions: list[Transaction]) -> str:
        """Format transactions into a prompt for the agent."""
        lines = ["Categoriza las siguientes transacciones:\n"]
        
        for tx in transactions:
            lines.append(
                f"- ID: {tx.id}\n"
                f"  Fecha: {tx.date.isoformat()}\n"
                f"  Importe: {tx.amount} {tx.currency}\n"
                f"  Descripción: {tx.description}\n"
                f"  Comercio: {tx.merchant_name or 'No especificado'}\n"
            )
        
        lines.append("\nUsa la herramienta categorize_transaction para cada una.")
        return "\n".join(lines)
