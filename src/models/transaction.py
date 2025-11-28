"""Transaction model definitions."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class TransactionAction(Enum):
    """Actions that can be taken on a transaction."""
    
    REGISTER = "register"
    SKIP = "skip"
    REVIEW = "review"


@dataclass
class Transaction:
    """Represents a bank transaction."""
    
    id: str
    date: date
    amount: float
    description: str
    merchant_name: Optional[str] = None
    category: Optional[str] = None
    action: TransactionAction = TransactionAction.REGISTER
    skip_reason: Optional[str] = None
    notes: Optional[str] = None
    
    # Campos adicionales de GoCardless
    currency: str = "EUR"
    balance_after: Optional[float] = None
    transaction_type: Optional[str] = None
    
    @property
    def is_expense(self) -> bool:
        """Check if transaction is an expense (negative amount)."""
        return self.amount < 0
    
    @property
    def is_income(self) -> bool:
        """Check if transaction is income (positive amount)."""
        return self.amount > 0
    
    @property
    def absolute_amount(self) -> float:
        """Return absolute value of amount."""
        return abs(self.amount)
    
    def to_sheet_row(self) -> list:
        """Convert transaction to a row for Google Sheets."""
        return [
            self.date.strftime("%d/%m/%Y"),
            self.description,
            self.merchant_name or "",
            self.category or "",
            self.absolute_amount,
            self.notes or ""
        ]
    
    @classmethod
    def from_gocardless(cls, data: dict) -> "Transaction":
        """Create Transaction from GoCardless API response."""
        # GoCardless puede usar diferentes campos según el banco
        transaction_amount = data.get("transactionAmount", {})
        amount = float(transaction_amount.get("amount", 0))
        currency = transaction_amount.get("currency", "EUR")
        
        # Obtener fecha (GoCardless usa bookingDate o valueDate)
        date_str = data.get("bookingDate") or data.get("valueDate")
        tx_date = date.fromisoformat(date_str) if date_str else date.today()
        
        # Descripción puede venir de varios campos
        description = (
            data.get("remittanceInformationUnstructured") or
            data.get("additionalInformation") or
            data.get("creditorName") or
            data.get("debtorName") or
            "Sin descripción"
        )
        
        return cls(
            id=data.get("transactionId") or data.get("internalTransactionId", ""),
            date=tx_date,
            amount=amount,
            description=description,
            merchant_name=data.get("creditorName") or data.get("merchantName"),
            currency=currency,
            transaction_type=data.get("proprietaryBankTransactionCode"),
        )
