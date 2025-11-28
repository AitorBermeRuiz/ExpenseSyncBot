"""GoCardless API integration for bank transaction retrieval."""

import logging
from datetime import date, timedelta
from typing import Optional

import requests

from src.models.transaction import Transaction

logger = logging.getLogger(__name__)


class GoCardlessError(Exception):
    """Exception raised for GoCardless API errors."""
    pass


class GoCardlessService:
    """Service for interacting with GoCardless Bank Account Data API."""
    
    BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"
    
    def __init__(self, secret_id: str, secret_key: str):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self._access_token: Optional[str] = None
        self._session = requests.Session()
    
    def _get_access_token(self) -> str:
        """Obtain a new access token from GoCardless."""
        if self._access_token:
            return self._access_token
        
        logger.info("🔑 Obteniendo token de acceso de GoCardless...")
        
        response = self._session.post(
            f"{self.BASE_URL}/token/new/",
            json={
                "secret_id": self.secret_id,
                "secret_key": self.secret_key
            }
        )
        
        if response.status_code != 200:
            raise GoCardlessError(
                f"Error al obtener token: {response.status_code} - {response.text}"
            )
        
        data = response.json()
        self._access_token = data.get("access")
        
        if not self._access_token:
            raise GoCardlessError("No se recibió access token en la respuesta")
        
        logger.info("✅ Token obtenido correctamente")
        return self._access_token
    
    @property
    def _headers(self) -> dict:
        """Get authorization headers."""
        return {"Authorization": f"Bearer {self._get_access_token()}"}
    
    def get_transactions(
        self,
        account_id: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None
    ) -> list[Transaction]:
        """
        Retrieve transactions for a specific account.
        
        Args:
            account_id: GoCardless account ID
            date_from: Start date for transactions (default: 7 days ago)
            date_to: End date for transactions (default: today)
        
        Returns:
            List of Transaction objects
        """
        if date_from is None:
            date_from = date.today() - timedelta(days=7)
        if date_to is None:
            date_to = date.today()
        
        logger.info(
            f"📊 Obteniendo transacciones del {date_from} al {date_to}..."
        )
        
        url = f"{self.BASE_URL}/accounts/{account_id}/transactions/"
        params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat()
        }
        
        response = self._session.get(url, headers=self._headers, params=params)
        
        if response.status_code != 200:
            raise GoCardlessError(
                f"Error al obtener transacciones: {response.status_code} - {response.text}"
            )
        
        data = response.json()
        
        # GoCardless devuelve las transacciones en "booked" y "pending"
        booked = data.get("transactions", {}).get("booked", [])
        
        transactions = [Transaction.from_gocardless(tx) for tx in booked]
        
        logger.info(f"✅ Se obtuvieron {len(transactions)} transacciones")
        
        return transactions
    
    def get_account_details(self, account_id: str) -> dict:
        """Get account details."""
        response = self._session.get(
            f"{self.BASE_URL}/accounts/{account_id}/",
            headers=self._headers
        )
        
        if response.status_code != 200:
            raise GoCardlessError(
                f"Error al obtener detalles de cuenta: {response.status_code}"
            )
        
        return response.json()
    
    def get_account_balances(self, account_id: str) -> dict:
        """Get account balances."""
        response = self._session.get(
            f"{self.BASE_URL}/accounts/{account_id}/balances/",
            headers=self._headers
        )
        
        if response.status_code != 200:
            raise GoCardlessError(
                f"Error al obtener saldos: {response.status_code}"
            )
        
        return response.json()
    
    def invalidate_token(self) -> None:
        """Clear cached access token."""
        self._access_token = None
