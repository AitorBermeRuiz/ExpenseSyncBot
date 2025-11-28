# ExpenseSyncBot

🤖 Sistema automatizado de tracking de gastos usando **OpenAI Agents SDK** y **MCP (Model Context Protocol)**.

## Arquitectura

```
╔═══════════════════════════════════════════════════════════════════╗
║                     ExpenseSyncOrchestrator                        ║
╠═══════════════════╦═══════════════════╦═══════════════════════════╣
║   Categorization  ║    Validation     ║         Writer            ║
║      Agent        ║      Agent        ║         Agent             ║
║                   ║                   ║                           ║
║  • Clasifica      ║  • Verifica       ║  • Conecta MCP            ║
║  • Asigna acción  ║  • Corrige        ║  • Escribe Sheets         ║
║  • Detecta skips  ║  • Flags review   ║  • Confirma               ║
╚═══════════════════╩═══════════════════╩═══════════════════════════╝
         │                   │                      │
         ▼                   ▼                      ▼
    OpenAI GPT-4o      OpenAI GPT-4o        MCP Server (.NET)
                                                   │
                                                   ▼
                                            Google Sheets
```

## Quick Start

### Requisitos

- Python 3.11+
- .NET 8.0 SDK
- Cuenta GoCardless con banco conectado
- API key de OpenAI

### Instalación

```bash
cd ExpenseSyncBot

# Con uv (recomendado)
uv venv
source .venv/bin/activate

# Instalar en modo editable (importante para imports)
uv pip install -e .

# O con pip
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Configuración

```bash
cp .env.example .env
nano .env
```

Variables requeridas:
```env
GOCARDLESS_SECRET_ID=...
GOCARDLESS_SECRET_KEY=...
BANK_ACCOUNT_ID=...
OPENAI_API_KEY=sk-...
MCP_SERVER_PROJECT_PATH=/path/to/Budget_Automation/src
```

### Compilar servidor MCP (una vez)

```bash
cd /path/to/Budget_Automation/Budget_Automation.MCPServer/src
dotnet build -c Release
```

### Ejecutar

```bash
python main.py
```

## Estructura del Proyecto

```
ExpenseSyncBot/
├── main.py                      # Entry point
├── config/
│   ├── __init__.py
│   └── settings.py              # Configuración
├── src/
│   ├── __init__.py
│   ├── agents/                  # 🤖 OpenAI Agents
│   │   ├── __init__.py
│   │   ├── categorization_agent.py
│   │   ├── validation_agent.py
│   │   └── orchestrator.py      # Coordinador
│   ├── models/
│   │   ├── __init__.py
│   │   └── transaction.py       # Data models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gocardless.py        # Bank API
│   │   ├── mcp_server.py        # .NET lifecycle
│   │   └── openai_client.py     # Legacy (opcional)
│   └── validators/
│       ├── __init__.py
│       └── transaction_validator.py  # Reglas custom
├── .env.example
├── pyproject.toml
└── requirements.txt
```

## Agentes

### CategorizationAgent

Clasifica transacciones en categorías:
- Alimentación, Transporte, Hogar, Salud, Ocio
- Ropa, Tecnología, Educación, Finanzas, Otros

Decide la acción:
- `register`: Registrar en el presupuesto
- `skip`: Omitir (transferencias internas, devoluciones)
- `review`: Marcar para revisión manual

### ValidationAgent

Verifica las categorizaciones:
- Detecta errores comunes
- Aplica reglas de negocio
- Puede corregir categorías o cambiar acciones

### WriterAgent

Escribe en Google Sheets via MCP:
- Usa herramientas `write_range` y `get_ranges`
- Formatea datos para la hoja de gastos

## Personalización

### Habilitar validación LLM

```env
ENABLE_LLM_VERIFICATION=true
```

### Reglas personalizadas

```python
from src.validators import ValidationRule, TransactionAction

# Omitir Netflix
skip_netflix = ValidationRule(
    name="skip_netflix",
    condition=lambda tx: "netflix" in tx.description.lower(),
    action=TransactionAction.SKIP
)
```

## License

MIT
