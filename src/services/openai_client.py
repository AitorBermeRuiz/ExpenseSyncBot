"""OpenAI integration - Legacy service for standalone use."""

import json
import logging
from typing import Optional

from openai import OpenAI

from src.models.transaction import Transaction, TransactionAction

logger = logging.getLogger(__name__)


CATEGORIZATION_SYSTEM_PROMPT = """Eres un asistente experto en categorización de gastos personales.

Tu tarea es analizar transacciones bancarias y asignarles:
1. Una categoría apropiada
2. Decidir si se debe registrar, omitir, o marcar para revisión

CATEGORÍAS DISPONIBLES:
- Alimentación (supermercados, restaurantes, comida rápida)
- Transporte (gasolina, transporte público, parking, peajes)
- Hogar (alquiler, hipoteca, suministros, seguros hogar)
- Salud (farmacia, médicos, seguro médico)
- Ocio (entretenimiento, suscripciones, viajes)
- Ropa (tiendas de ropa, calzado)
- Tecnología (electrónica, software, suscripciones tech)
- Educación (cursos, libros, formación)
- Finanzas (transferencias entre cuentas, comisiones)
- Otros (cualquier cosa que no encaje)

REGLAS DE DECISIÓN:
- REGISTER: Gastos normales que deben registrarse
- SKIP: Transferencias entre cuentas propias, devoluciones, movimientos internos
- REVIEW: Transacciones dudosas o que necesitan verificación manual

Responde SIEMPRE en formato JSON."""


class OpenAICategorizationService:
    """
    Legacy service for categorizing transactions using OpenAI Chat API.
    
    Note: For new implementations, use the CategorizationAgent instead.
    This service is kept for standalone use or testing.
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        custom_rules: Optional[str] = None
    ):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.custom_rules = custom_rules
    
    def categorize_transactions(
        self,
        transactions: list[Transaction]
    ) -> list[Transaction]:
        """Categorize a list of transactions using chat completions."""
        
        if not transactions:
            return []
        
        logger.info(f"🧠 [Legacy] Categorizando {len(transactions)} transacciones...")
        
        tx_data = [
            {
                "id": tx.id,
                "date": tx.date.isoformat(),
                "amount": tx.amount,
                "description": tx.description,
                "merchant": tx.merchant_name
            }
            for tx in transactions
        ]
        
        system_prompt = CATEGORIZATION_SYSTEM_PROMPT
        if self.custom_rules:
            system_prompt += f"\n\nREGLAS PERSONALIZADAS:\n{self.custom_rules}"
        
        user_prompt = f"""Categoriza estas transacciones y responde en JSON:
{{
    "transactions": [
        {{"id": "...", "category": "...", "action": "register|skip|review", "skip_reason": "...", "notes": "..."}}
    ]
}}

Transacciones:
{json.dumps(tx_data, indent=2, ensure_ascii=False)}"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            result = json.loads(response.choices[0].message.content)
            categorized = result.get("transactions", [])
            
            tx_map = {tx.id: tx for tx in transactions}
            
            for cat in categorized:
                tx_id = cat.get("id")
                if tx_id in tx_map:
                    tx = tx_map[tx_id]
                    tx.category = cat.get("category")
                    tx.action = TransactionAction(cat.get("action", "register"))
                    tx.skip_reason = cat.get("skip_reason")
                    tx.notes = cat.get("notes")
            
            return transactions
            
        except Exception as e:
            logger.error(f"❌ Error en categorización: {e}")
            raise
