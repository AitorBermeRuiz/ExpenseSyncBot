# ExpenseSyncBot v2.0

Agent-based expense automation API built with **OpenAI Agents SDK** and MCP integration. This service processes receipt emails, extracts expense data using AI agents, and persists it via an external MCP server.

## Architecture

```
┌─────────────┐     POST /process-receipt     ┌─────────────────────────────────┐
│    n8n      │ ─────────────────────────────▶│      FastAPI Service            │
│  (Trigger)  │                               │                                 │
└─────────────┘                               │  ┌───────────────────────────┐  │
                                              │  │  Categorizer Agent        │  │
                                              │  │  (Agent + Runner.run)     │  │
                                              │  │  output_type: Expense     │  │
                                              │  └─────────────┬─────────────┘  │
                                              │                │                │
                                              │  ┌─────────────▼─────────────┐  │
                                              │  │     @function_tool        │  │
                                              │  │  ┌─────────┐ ┌─────────┐  │  │
                                              │  │  │validate │ │add_mcp  │  │  │
                                              │  │  │_expense │ │_expense │  │  │
                                              │  │  └─────────┘ └────┬────┘  │  │
                                              │  └───────────────────┼──────┘  │
                                              └──────────────────────┼─────────┘
                                                                     │ MCP/SSE
                                              ┌──────────────────────▼─────────┐
                                              │      C# MCP Server             │
                                              │      (AddExpense tool)         │
                                              └────────────────────────────────┘
```

## What's New in v2.0

- **OpenAI Agents SDK**: Replaced manual conversation loops with declarative `Agent` and `Runner.run()`
- **@function_tool decorator**: Auto-generated tool schemas from Python functions
- **Structured outputs**: `output_type=ExtractedExpense` for type-safe agent responses
- **Simplified architecture**: No more manual message history management

## Features

- **AI-powered categorization**: Uses `Agent[ExtractedExpense]` with structured output
- **Validation with correction loop**: `@function_tool` validates and retries with feedback
- **Multi-provider LLM support**: OpenAI, Gemini, DeepSeek, Groq via registry pattern
- **MCP integration**: Connects to external MCP servers via SSE for persistence
- **Production-ready**: Modular architecture, logging, health checks

## Project Structure

```
ExpenseSyncBot/
├── src/
│   ├── main.py                 # FastAPI app with lifespan
│   ├── core/
│   │   ├── configs.py          # LLM registry + settings
│   │   ├── logging.py          # Loguru configuration
│   │   └── llm_manager.py      # LLM client management
│   ├── models/
│   │   └── schemas.py          # Pydantic models (API only, no tool schemas)
│   ├── agents/
│   │   ├── prompts.py          # System prompts + MERCHANT_HINTS
│   │   ├── tools.py            # @function_tool decorated tools
│   │   └── orchestrator.py     # Agent definitions + Runner.run workflow
│   └── services/
│       └── mcp_client.py       # MCP SSE client
├── pyproject.toml              # Dependencies including openai-agents
└── README.md
```

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd ExpenseSyncBot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies (includes openai-agents SDK)
pip install -e .

# Or with uv
uv sync
```

## Configuration

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` with your API keys and settings:
```env
# Required: At least one LLM provider API key
OPENAI_API_KEY=sk-your-key
# Or
GROQ_API_KEY=your-groq-key

# MCP Server URL (your C# server)
MCP__SERVER_URL=http://localhost:5000/sse

# Choose providers
ORCHESTRATOR__LLM_PROVIDER=openai
ORCHESTRATOR__CATEGORIZER_PROVIDER=groq-fast
```

## Usage

### Start the API

```bash
# Development mode (with hot reload)
DEBUG=true python -m src.main

# Or with uvicorn directly
uvicorn src.main:app --reload --port 8000
```

### API Endpoints

#### Process Receipt
```bash
POST /process-receipt

{
  "email_body": "Your receipt email content...",
  "email_subject": "Receipt from Amazon",  # optional
  "sender": "orders@amazon.com"             # optional
}
```

Response:
```json
{
  "status": "success",
  "message": "Recibo procesado exitosamente y guardado en el sistema",
  "data": {
    "comercio": "Amazon",
    "importe": 29.99,
    "moneda": "EUR",
    "fecha": "2024-12-06",
    "categoria": "tecnologia",
    "descripcion": "Echo Dot",
    "persisted": true
  },
  "attempts": 1,
  "errors": []
}
```

#### Health Check
```bash
GET /health
GET /health/detailed
```

#### List Tools
```bash
GET /tools
```

Returns:
```json
{
  "internal_tools": [
    "categorize_receipt",
    "validate_expense",
    "format_expense_for_persistence",
    "add_expense_mcp"
  ],
  "mcp_tools": ["AddExpense"],
  "total": 5,
  "architecture": "OpenAI Agents SDK"
}
```

## OpenAI Agents SDK Patterns

### Agent Definition with Structured Output

```python
from agents import Agent, Runner, ModelSettings

class ExtractedExpense(BaseModel):
    comercio: str
    importe: float
    fecha: str
    categoria: str
    # ...

categorizer = Agent[ExtractedExpense](
    name="CategorizadorRecibos",
    instructions="...",
    model=model,
    model_settings=ModelSettings(temperature=0.1),
    output_type=ExtractedExpense,  # Automatic JSON schema
)

# Run the agent
result = await Runner.run(categorizer, "Extrae datos de: ...")
expense = result.final_output  # Type: ExtractedExpense
```

### Function Tools with @function_tool

```python
from agents import function_tool

@function_tool
def validate_expense(
    comercio: str,
    importe: float,
    fecha: str,
    categoria: str,
    moneda: str = "EUR",
) -> str:
    """Validate expense data against business rules.

    Args:
        comercio: Merchant name
        importe: Amount
        fecha: Date in YYYY-MM-DD
        categoria: Category
        moneda: Currency code

    Returns:
        JSON with is_valid, error_message, warnings
    """
    # Validation logic...
    return result.model_dump_json()
```

### Multi-Provider Model Factory

```python
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

def _create_model(provider: str) -> OpenAIChatCompletionsModel:
    config = AVAILABLE_LLMS[provider]  # From registry
    client = AsyncOpenAI(
        api_key=os.getenv(config.api_key_env_var),
        base_url=config.base_url,
    )
    return OpenAIChatCompletionsModel(
        model=config.model_name,
        openai_client=client,
    )
```

## LLM Providers

| Provider | Model | Use Case |
|----------|-------|----------|
| `openai` | gpt-4o-mini | Default orchestrator |
| `openai-gpt4` | gpt-4o | Higher accuracy |
| `gemini` | gemini-2.5-flash | Alternative |
| `deepseek` | deepseek-chat | Cost-effective |
| `groq` | llama-3.3-70b | Fast inference |
| `groq-fast` | llama-3.1-8b | Very fast, categorization |

## Processing Flow

```
1. Receipt arrives → n8n POST to /process-receipt

2. Categorizer Agent (Runner.run)
   └─> ExtractedExpense (structured output)

3. validate_expense (@function_tool)
   └─> {is_valid, error_message, warnings}

4. If invalid → Re-run categorizer with feedback (max 3 attempts)

5. If valid → add_expense_mcp (@function_tool)
   └─> MCP SSE → C# Server → Database

6. Return ProcessReceiptResponse to n8n
```

## n8n Integration

In your n8n workflow:

1. **Trigger**: Email trigger (IMAP, Gmail, etc.)
2. **HTTP Request node**:
   - Method: POST
   - URL: `http://your-server:8000/process-receipt`
   - Body:
     ```json
     {
       "email_body": "{{ $json.text }}",
       "email_subject": "{{ $json.subject }}",
       "sender": "{{ $json.from }}"
     }
     ```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
ruff format src/
```

## Migration from v1.0

If upgrading from v1.0 (manual conversation loops):

1. **Dependencies**: Add `openai-agents>=0.0.3` to requirements
2. **Tools**: Replace manual JSON schemas with `@function_tool` decorators
3. **Orchestrator**: Replace `while` loop with `Runner.run(agent, prompt)`
4. **Outputs**: Use `output_type=Model` for structured agent responses

The FastAPI interface (`OrchestratorAgent.process_receipt()`) remains unchanged.

## License

MIT
