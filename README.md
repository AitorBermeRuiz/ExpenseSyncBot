# ExpenseSyncBot

Agent-based expense automation API with MCP integration. This service processes receipt emails, extracts expense data using AI, and persists it via an external MCP server.

## Architecture

```
┌─────────────┐     POST /process-receipt     ┌────────────────────────┐
│    n8n      │ ─────────────────────────────▶│   FastAPI Service      │
│  (Trigger)  │                               │                        │
└─────────────┘                               │  ┌──────────────────┐  │
                                              │  │   Orchestrator   │  │
                                              │  │      Agent       │  │
                                              │  └────────┬─────────┘  │
                                              │           │            │
                                              │     ┌─────┴─────┐      │
                                              │     │           │      │
                                              │  ┌──▼───┐  ┌────▼───┐  │
                                              │  │Categ.│  │Validate│  │
                                              │  │ Tool │  │  Tool  │  │
                                              │  └──────┘  └────────┘  │
                                              └───────────┬────────────┘
                                                          │ MCP/SSE
                                              ┌───────────▼────────────┐
                                              │   C# MCP Server        │
                                              │   (AddExpense tool)    │
                                              └────────────────────────┘
```

## Features

- **AI-powered categorization**: Extracts expense data from noisy email content (HTML, signatures, etc.)
- **Validation with correction loop**: Validates extracted data and retries with feedback on failure
- **Multi-provider LLM support**: OpenAI, Gemini, DeepSeek, Groq
- **MCP integration**: Connects to external MCP servers via SSE for persistence
- **Production-ready**: Modular architecture, logging, health checks

## Project Structure

```
ExpenseSyncBot/
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI app with lifespan
│   ├── core/
│   │   ├── __init__.py
│   │   ├── configs.py       # LLM registry + settings
│   │   ├── logging.py       # Loguru configuration
│   │   └── llm_manager.py   # LLM client management
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py       # Pydantic models
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── prompts.py       # System prompts
│   │   ├── tools.py         # Internal Python tools
│   │   └── orchestrator.py  # Main orchestration logic
│   └── services/
│       ├── __init__.py
│       └── mcp_client.py    # MCP SSE client
├── tests/
├── .env.example
├── pyproject.toml
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

# Install dependencies
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
  "message": "Recibo procesado exitosamente",
  "data": {
    "comercio": "Amazon",
    "importe": 29.99,
    "moneda": "EUR",
    "fecha": "2024-12-06",
    "categoria": "tecnologia",
    "descripcion": "Echo Dot"
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

### n8n Integration

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

## LLM Providers

The system supports multiple LLM providers through a registry pattern:

| Provider | Model | Use Case |
|----------|-------|----------|
| `openai` | gpt-4o-mini | Default orchestrator |
| `openai-gpt4` | gpt-4o | Higher accuracy |
| `gemini` | gemini-2.0-flash | Alternative |
| `deepseek` | deepseek-chat | Cost-effective |
| `groq` | llama-3.3-70b | Fast inference |
| `groq-fast` | llama-3.1-8b | Very fast, categorization |

## Processing Flow

1. **Receipt arrives** → n8n sends POST to `/process-receipt`
2. **Orchestrator** → Coordinates the workflow
3. **Categorize** → AI extracts: merchant, amount, date, category
4. **Validate** → Checks business rules (amount > 0, valid date, etc.)
5. **Correction Loop** → If validation fails, retry with feedback (max 3 attempts)
6. **Persist** → Call MCP `AddExpense` tool to save

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

## License

MIT
