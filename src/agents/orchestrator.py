"""Orchestrator - Coordinates agents and MCP tools for expense sync."""

import json
import logging
from typing import Optional

from agents import Agent, Runner, function_tool
from mcp import ClientSession

from src.models.transaction import Transaction, TransactionAction
from src.agents.categorization_agent import CategorizationAgent
from src.agents.validation_agent import ValidationAgent

logger = logging.getLogger(__name__)


class ExpenseSyncOrchestrator:
    """
    Orchestrates the expense sync workflow using OpenAI Agents SDK.
    
    Flow:
    1. Categorization Agent classifies transactions
    2. Validation Agent double-checks (optional)
    3. Writer Agent sends to Google Sheets via MCP
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        enable_validation: bool = True,
        custom_rules: Optional[str] = None
    ):
        self.model = model
        self.enable_validation = enable_validation
        
        # Initialize agents
        self.categorization_agent = CategorizationAgent(model=model)
        self.validation_agent = ValidationAgent(
            model=model,
            custom_rules=custom_rules
        ) if enable_validation else None
        
        # MCP session will be set when running
        self._mcp_session: Optional[ClientSession] = None
        self._mcp_tools: list = []
    
    async def setup_mcp_tools(self, session: ClientSession) -> None:
        """
        Setup MCP tools from the .NET server.
        
        Args:
            session: Active MCP client session
        """
        self._mcp_session = session
        
        # Get available tools from MCP server
        tools_response = await session.list_tools()
        
        logger.info(f"🔧 MCP Tools disponibles: {[t.name for t in tools_response.tools]}")
        
        # Store tool definitions for the writer agent
        self._mcp_tools = tools_response.tools
    
    def _create_writer_agent(self) -> Agent:
        """Create the writer agent with MCP tools."""
        
        # We need to capture self for the closure
        orchestrator = self
        
        @function_tool
        async def write_expenses_to_sheet(
            range: str,
            values: list[list[str]]
        ) -> str:
            """
            Write expense data to Google Sheets.
            
            Args:
                range: Sheet range in A1 notation (e.g., "Gastos!A2:F10")
                values: 2D array of values to write
            
            Returns:
                Result message from the sheet operation
            """
            if not orchestrator._mcp_session:
                return "Error: MCP session not initialized"
            
            try:
                result = await orchestrator._mcp_session.call_tool(
                    "write_range",
                    {"range": range, "values": values}
                )
                return str(result)
            except Exception as e:
                return f"Error writing to sheet: {e}"
        
        @function_tool
        async def read_sheet_range(ranges: list[str]) -> str:
            """
            Read data from Google Sheets to check existing entries.
            
            Args:
                ranges: List of ranges to read in A1 notation
            
            Returns:
                Data from the specified ranges
            """
            if not orchestrator._mcp_session:
                return "Error: MCP session not initialized"
            
            try:
                result = await orchestrator._mcp_session.call_tool(
                    "get_ranges",
                    {"range": ranges}
                )
                return str(result)
            except Exception as e:
                return f"Error reading sheet: {e}"
        
        return Agent(
            name="EscritorGastos",
            instructions="""Eres un agente que escribe gastos en Google Sheets.

Tu trabajo es:
1. Recibir transacciones categorizadas y validadas
2. Formatear los datos para la hoja de cálculo
3. Escribir en el rango correcto

## FORMATO DE LA HOJA:
- Columna A: Fecha (dd/mm/yyyy)
- Columna B: Descripción
- Columna C: Comercio
- Columna D: Categoría
- Columna E: Importe (positivo, sin signo)
- Columna F: Notas

## IMPORTANTE:
- Solo escribe transacciones con acción "register"
- El importe debe ser positivo (valor absoluto del gasto)
- Usa el rango "Gastos!A:F" para añadir al final

Usa write_expenses_to_sheet para escribir los datos.""",
            model=self.model,
            tools=[write_expenses_to_sheet, read_sheet_range]
        )
    
    async def process_transactions(
        self,
        transactions: list[Transaction],
        sheet_range: str = "Gastos!A:F"
    ) -> dict:
        """
        Process transactions through the agent pipeline.
        
        Args:
            transactions: List of transactions to process
            sheet_range: Target range in Google Sheets
        
        Returns:
            Processing results summary
        """
        results = {
            "total": len(transactions),
            "categorized": 0,
            "validated": 0,
            "written": 0,
            "skipped": 0,
            "errors": []
        }
        
        if not transactions:
            logger.info("📭 No hay transacciones para procesar")
            return results
        
        # Step 1: Categorization
        logger.info(f"\n🏷️  PASO 1: Categorizando {len(transactions)} transacciones...")
        
        categorized = await self._run_categorization(transactions)
        results["categorized"] = len(categorized)
        
        # Step 2: Validation (optional)
        if self.enable_validation and self.validation_agent:
            logger.info(f"\n✅ PASO 2: Validando categorizaciones...")
            validated = await self._run_validation(categorized)
        else:
            logger.info("\n⏭️  PASO 2: Validación deshabilitada, continuando...")
            validated = categorized
        
        results["validated"] = len(validated)
        
        # Filter by action
        to_register = [tx for tx in validated if tx.action == TransactionAction.REGISTER]
        to_skip = [tx for tx in validated if tx.action == TransactionAction.SKIP]
        to_review = [tx for tx in validated if tx.action == TransactionAction.REVIEW]
        
        results["skipped"] = len(to_skip)
        
        logger.info(f"\n📊 Resumen:")
        logger.info(f"   ✅ A registrar: {len(to_register)}")
        logger.info(f"   ⏭️  Omitidos: {len(to_skip)}")
        logger.info(f"   👀 Para revisar: {len(to_review)}")
        
        # Step 3: Write to sheet
        if to_register and self._mcp_session:
            logger.info(f"\n📝 PASO 3: Escribiendo {len(to_register)} transacciones...")
            written = await self._run_writer(to_register, sheet_range)
            results["written"] = written
        
        return results
    
    async def _run_categorization(
        self,
        transactions: list[Transaction]
    ) -> list[Transaction]:
        """Run categorization agent on transactions."""
        
        prompt = self.categorization_agent.format_transactions_prompt(transactions)
        agent = self.categorization_agent.get_agent()
        
        # Run the agent
        result = await Runner.run(agent, prompt)
        
        # Parse tool calls from result to update transactions
        tx_map = {tx.id: tx for tx in transactions}
        
        for item in result.new_items:
            if hasattr(item, 'raw_item') and item.raw_item.get('type') == 'function_call_output':
                try:
                    output = json.loads(item.raw_item.get('output', '{}'))
                    tx_id = output.get('transaction_id')
                    
                    if tx_id in tx_map:
                        tx = tx_map[tx_id]
                        tx.category = output.get('category', '')
                        tx.action = TransactionAction(output.get('action', 'register'))
                        tx.skip_reason = output.get('skip_reason', '')
                        tx.notes = output.get('notes', '')
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"Error parsing categorization: {e}")
        
        return transactions
    
    async def _run_validation(
        self,
        transactions: list[Transaction]
    ) -> list[Transaction]:
        """Run validation agent on categorized transactions."""
        
        if not self.validation_agent:
            return transactions
        
        # Only validate transactions marked for register
        to_validate = [tx for tx in transactions if tx.action == TransactionAction.REGISTER]
        
        if not to_validate:
            return transactions
        
        prompt = self.validation_agent.format_validation_prompt(to_validate)
        agent = self.validation_agent.get_agent()
        
        result = await Runner.run(agent, prompt)
        
        # Parse validation results
        tx_map = {tx.id: tx for tx in transactions}
        
        for item in result.new_items:
            if hasattr(item, 'raw_item') and item.raw_item.get('type') == 'function_call_output':
                try:
                    output = json.loads(item.raw_item.get('output', '{}'))
                    tx_id = output.get('transaction_id')
                    
                    if tx_id in tx_map and not output.get('is_valid', True):
                        tx = tx_map[tx_id]
                        
                        if output.get('corrected_category'):
                            tx.category = output['corrected_category']
                        
                        if output.get('corrected_action'):
                            tx.action = TransactionAction(output['corrected_action'])
                        
                        if output.get('validation_notes'):
                            existing = tx.notes or ''
                            tx.notes = f"{existing} | Validación: {output['validation_notes']}".strip(' |')
                    
                    # Handle flagged for review
                    if output.get('flagged'):
                        tx = tx_map.get(tx_id)
                        if tx:
                            tx.action = TransactionAction.REVIEW
                            tx.notes = f"{tx.notes or ''} | {output.get('reason', '')}".strip(' |')
                            
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"Error parsing validation: {e}")
        
        return transactions
    
    async def _run_writer(
        self,
        transactions: list[Transaction],
        sheet_range: str
    ) -> int:
        """Run writer agent to send transactions to Google Sheets."""
        
        writer_agent = self._create_writer_agent()
        
        # Format transactions for the writer
        rows_data = []
        for tx in transactions:
            rows_data.append({
                "date": tx.date.strftime("%d/%m/%Y"),
                "description": tx.description,
                "merchant": tx.merchant_name or "",
                "category": tx.category or "",
                "amount": tx.absolute_amount,
                "notes": tx.notes or ""
            })
        
        prompt = f"""Escribe estas {len(transactions)} transacciones en Google Sheets.

Datos a escribir:
{json.dumps(rows_data, indent=2, ensure_ascii=False)}

Usa el rango: {sheet_range}

Formatea cada fila como: [fecha, descripción, comercio, categoría, importe, notas]"""
        
        try:
            result = await Runner.run(writer_agent, prompt)
            logger.info(f"✅ Escritura completada")
            return len(transactions)
        except Exception as e:
            logger.error(f"❌ Error en escritura: {e}")
            return 0
