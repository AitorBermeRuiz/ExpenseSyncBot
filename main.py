#!/usr/bin/env python3
"""
ExpenseSyncBot - Automated expense tracking with OpenAI Agents SDK.

Architecture:
┌─────────────────────────────────────────────────────────────┐
│                    ExpenseSyncOrchestrator                   │
├─────────────────┬─────────────────┬─────────────────────────┤
│ Categorization  │   Validation    │        Writer           │
│     Agent       │     Agent       │        Agent            │
│  (classifies)   │  (double-check) │   (MCP → Sheets)        │
└─────────────────┴─────────────────┴─────────────────────────┘
"""

import asyncio
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from mcp.client.sse import sse_client
from mcp import ClientSession

# Load environment variables
load_dotenv()

# Import local modules (after dotenv)
from config.settings import AppConfig
from src.services.gocardless import GoCardlessService
from src.services.mcp_server import MCPServerManager
from src.agents.orchestrator import ExpenseSyncOrchestrator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def print_banner():
    """Print startup banner."""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                      ExpenseSyncBot v0.2                       ║
║              Powered by OpenAI Agents SDK + MCP                ║
╚═══════════════════════════════════════════════════════════════╝
    """
    print(banner)


async def run_agent_pipeline(config: AppConfig) -> None:
    """
    Main pipeline that orchestrates the expense sync process.
    
    Args:
        config: Application configuration
    """
    print_banner()
    
    # =========================================================================
    # STEP 1: Fetch transactions from GoCardless
    # =========================================================================
    logger.info("=" * 60)
    logger.info("📊 FASE 1: Obteniendo transacciones bancarias")
    logger.info("=" * 60)
    
    try:
        gocardless = GoCardlessService(
            secret_id=config.gocardless.secret_id,
            secret_key=config.gocardless.secret_key
        )
        
        date_from = date.today() - timedelta(days=config.days_to_fetch)
        transactions = gocardless.get_transactions(
            account_id=config.gocardless.account_id,
            date_from=date_from
        )
        
        if not transactions:
            logger.info("💤 No hay transacciones nuevas. Finalizando.")
            return
        
        # Filter expenses only (negative amounts)
        expenses = [tx for tx in transactions if tx.is_expense]
        logger.info(f"📉 {len(expenses)} gastos de {len(transactions)} transacciones totales")
        
        if not expenses:
            logger.info("💤 No hay gastos nuevos. Finalizando.")
            return
            
    except Exception as e:
        logger.error(f"❌ Error obteniendo transacciones: {e}")
        raise
    
    # =========================================================================
    # STEP 2: Start MCP Server and run Agent Pipeline
    # =========================================================================
    logger.info("\n" + "=" * 60)
    logger.info("🤖 FASE 2: Ejecutando pipeline de agentes")
    logger.info("=" * 60)
    
    server = MCPServerManager(
        project_path=config.mcp_server.project_path,
        url=config.mcp_server.url,
        startup_timeout=config.mcp_server.startup_timeout,
        configuration=config.mcp_server.configuration
    )
    
    try:
        # Start .NET MCP server
        server.start()
        
        # Connect to MCP server via SSE
        async with sse_client(config.mcp_server.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                logger.info("🔗 Conectado al servidor MCP .NET")
                
                # Create orchestrator
                orchestrator = ExpenseSyncOrchestrator(
                    model=config.openai.model,
                    enable_validation=config.validation.enable_llm_verification
                )
                
                # Setup MCP tools
                await orchestrator.setup_mcp_tools(session)
                
                # Run the agent pipeline
                results = await orchestrator.process_transactions(
                    transactions=expenses,
                    sheet_range="Gastos!A:F"
                )
                
                # Print summary
                logger.info("\n" + "=" * 60)
                logger.info("📋 RESUMEN FINAL")
                logger.info("=" * 60)
                logger.info(f"   Total procesadas: {results['total']}")
                logger.info(f"   Categorizadas:    {results['categorized']}")
                logger.info(f"   Validadas:        {results['validated']}")
                logger.info(f"   Escritas:         {results['written']}")
                logger.info(f"   Omitidas:         {results['skipped']}")
                
                if results['errors']:
                    logger.warning(f"   Errores:          {len(results['errors'])}")
                    for err in results['errors']:
                        logger.warning(f"      - {err}")
        
        logger.info("\n✅ ExpenseSyncBot completado exitosamente!")
        
    except Exception as e:
        logger.error(f"❌ Error en pipeline: {e}")
        raise
    finally:
        server.stop()


def main():
    """Entry point."""
    try:
        # Load configuration
        config = AppConfig.from_env()
        
        # Set log level
        logging.getLogger().setLevel(config.log_level)
        
        # Set OpenAI API key for agents SDK
        os.environ["OPENAI_API_KEY"] = config.openai.api_key
        
        # Run pipeline
        asyncio.run(run_agent_pipeline(config))
        
    except ValueError as e:
        logger.error(f"❌ Error de configuración: {e}")
        logger.error("   Asegúrate de tener un archivo .env con todas las variables requeridas")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n⚠️ Interrumpido por usuario")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
