"""Transaction validation with custom rules and LLM verification."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

from openai import OpenAI

from src.models.transaction import Transaction, TransactionAction

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule:
    """
    A custom validation rule for transactions.
    
    Rules can modify transaction action, category, or add notes.
    """
    name: str
    description: str
    condition: Callable[[Transaction], bool]
    action: Optional[TransactionAction] = None
    category: Optional[str] = None
    clear_category: bool = False  # Si True, pone categoría en blanco
    add_note: Optional[str] = None
    priority: int = 0  # Mayor prioridad se ejecuta primero


# Reglas predefinidas comunes
def create_skip_pattern_rule(
    name: str,
    pattern: str,
    description: str = ""
) -> ValidationRule:
    """Create a rule that skips transactions matching a pattern."""
    compiled = re.compile(pattern, re.IGNORECASE)
    return ValidationRule(
        name=name,
        description=description or f"Skip transactions matching '{pattern}'",
        condition=lambda tx: bool(compiled.search(tx.description)),
        action=TransactionAction.SKIP,
        add_note=f"Omitido por regla: {name}"
    )


def create_categorize_pattern_rule(
    name: str,
    pattern: str,
    category: str,
    description: str = ""
) -> ValidationRule:
    """Create a rule that assigns category to transactions matching a pattern."""
    compiled = re.compile(pattern, re.IGNORECASE)
    return ValidationRule(
        name=name,
        description=description or f"Categorize as '{category}' for pattern '{pattern}'",
        condition=lambda tx: bool(compiled.search(tx.description)),
        category=category
    )


class TransactionValidator:
    """
    Validates and potentially modifies transactions based on custom rules.
    
    Supports:
    - Programmatic rules (functions)
    - Pattern matching rules
    - LLM-based verification for complex cases
    """
    
    def __init__(
        self,
        rules: Optional[list[ValidationRule]] = None,
        openai_api_key: Optional[str] = None,
        enable_llm_verification: bool = False,
        llm_model: str = "gpt-4o-mini"
    ):
        """
        Initialize validator.
        
        Args:
            rules: List of validation rules to apply
            openai_api_key: OpenAI API key for LLM verification
            enable_llm_verification: Whether to use LLM for double-checking
            llm_model: Model to use for LLM verification
        """
        self.rules = sorted(rules or [], key=lambda r: -r.priority)
        self.enable_llm_verification = enable_llm_verification
        self.llm_model = llm_model
        
        if enable_llm_verification and openai_api_key:
            self.openai_client = OpenAI(api_key=openai_api_key)
        else:
            self.openai_client = None
    
    def add_rule(self, rule: ValidationRule) -> None:
        """Add a validation rule."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: -r.priority)
    
    def validate(self, transactions: list[Transaction]) -> list[Transaction]:
        """
        Validate and potentially modify transactions.
        
        Args:
            transactions: List of transactions to validate
        
        Returns:
            Validated transactions with modifications applied
        """
        if not transactions:
            return []
        
        logger.info(f"🔍 Validando {len(transactions)} transacciones...")
        
        # Aplicar reglas programáticas
        for tx in transactions:
            self._apply_rules(tx)
        
        # Verificación LLM si está habilitada
        if self.enable_llm_verification and self.openai_client:
            transactions = self._llm_verification(transactions)
        
        # Log resumen
        modified = sum(1 for tx in transactions if tx.notes and "regla:" in tx.notes.lower())
        logger.info(f"✅ Validación completada: {modified} transacciones modificadas por reglas")
        
        return transactions
    
    def _apply_rules(self, transaction: Transaction) -> None:
        """Apply all rules to a single transaction."""
        for rule in self.rules:
            try:
                if rule.condition(transaction):
                    logger.debug(
                        f"  📌 Regla '{rule.name}' aplicada a: {transaction.description[:30]}"
                    )
                    
                    if rule.action:
                        transaction.action = rule.action
                    
                    if rule.clear_category:
                        transaction.category = ""
                    elif rule.category:
                        transaction.category = rule.category
                    
                    if rule.add_note:
                        existing = transaction.notes or ""
                        transaction.notes = f"{existing} | {rule.add_note}".strip(" |")
                        
            except Exception as e:
                logger.warning(f"⚠️ Error aplicando regla '{rule.name}': {e}")
    
    def _llm_verification(self, transactions: list[Transaction]) -> list[Transaction]:
        """Use LLM to double-check categorization decisions."""
        
        # Solo verificar transacciones que se van a registrar
        to_verify = [tx for tx in transactions if tx.action == TransactionAction.REGISTER]
        
        if not to_verify:
            return transactions
        
        logger.info(f"🤖 Verificando {len(to_verify)} transacciones con LLM...")
        
        # Preparar datos
        tx_data = [
            {
                "id": tx.id,
                "description": tx.description,
                "amount": tx.amount,
                "category": tx.category,
                "action": tx.action.value
            }
            for tx in to_verify
        ]
        
        verification_prompt = f"""Verifica estas categorizaciones de transacciones.
        
Para cada una, indica si la categorización es correcta o necesita ajuste.
Presta especial atención a:
- Transferencias entre cuentas propias (deberían omitirse)
- Categorías que no coinciden con la descripción
- Gastos recurrentes mal categorizados

Transacciones a verificar:
{json.dumps(tx_data, indent=2, ensure_ascii=False)}

Responde en JSON:
{{
    "verifications": [
        {{
            "id": "id_transaccion",
            "is_correct": true/false,
            "suggested_action": "register/skip/review",
            "suggested_category": "categoría sugerida si diferente",
            "reason": "razón del cambio si aplica"
        }}
    ]
}}"""
        
        try:
            response = self.openai_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un verificador de categorización de gastos. Sé conservador: solo sugiere cambios cuando estés seguro."
                    },
                    {"role": "user", "content": verification_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            result = json.loads(response.choices[0].message.content)
            verifications = result.get("verifications", [])
            
            # Aplicar sugerencias
            tx_map = {tx.id: tx for tx in transactions}
            changes = 0
            
            for v in verifications:
                if not v.get("is_correct", True):
                    tx_id = v.get("id")
                    if tx_id in tx_map:
                        tx = tx_map[tx_id]
                        
                        if v.get("suggested_action"):
                            tx.action = TransactionAction(v["suggested_action"])
                        
                        if v.get("suggested_category"):
                            tx.category = v["suggested_category"]
                        
                        reason = v.get("reason", "")
                        existing = tx.notes or ""
                        tx.notes = f"{existing} | LLM: {reason}".strip(" |")
                        changes += 1
            
            logger.info(f"✅ Verificación LLM: {changes} transacciones ajustadas")
            
        except Exception as e:
            logger.warning(f"⚠️ Error en verificación LLM: {e}")
        
        return transactions


# Ejemplo de reglas predefinidas útiles
DEFAULT_RULES = [
    # Omitir transferencias Bizum entre cuentas
    create_skip_pattern_rule(
        name="bizum_interno",
        pattern=r"bizum.*transferencia|transferencia.*bizum",
        description="Omitir transferencias Bizum"
    ),
    
    # Omitir transferencias entre cuentas propias
    create_skip_pattern_rule(
        name="transferencia_propia",
        pattern=r"traspaso|transferencia\s+(a|de)\s+cuenta",
        description="Omitir traspasos entre cuentas propias"
    ),
    
    # Categorizar supermercados conocidos
    create_categorize_pattern_rule(
        name="mercadona",
        pattern=r"mercadona",
        category="Alimentación"
    ),
    
    create_categorize_pattern_rule(
        name="carrefour",
        pattern=r"carrefour",
        category="Alimentación"
    ),
    
    # Categorizar suscripciones tech
    create_categorize_pattern_rule(
        name="netflix",
        pattern=r"netflix",
        category="Ocio"
    ),
    
    create_categorize_pattern_rule(
        name="spotify",
        pattern=r"spotify",
        category="Ocio"
    ),
    
    create_categorize_pattern_rule(
        name="amazon_prime",
        pattern=r"amazon\s*prime|amzn\s*prime",
        category="Tecnología"
    ),
]
