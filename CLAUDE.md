# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install dependencies
uv sync

# Run API (development with hot reload)
DEBUG=true uvicorn src.main:app --reload --port 8000

# Run API (production)
uv run src/main.py

# Code quality
ruff check src/           # Lint
ruff format src/          # Format
mypy src/                 # Type check

# Testing
pytest                    # Run all tests
pytest tests/test_file.py::test_name  # Run single test
```

## Architecture Overview

ExpenseSyncBot is a FastAPI-based expense automation API using the **OpenAI Agents SDK** with a multi-agent architecture. It processes expense emails and persists them to Google Sheets via MCP (Model Context Protocol).

### Request Flow

```
POST /process-receipt → OrchestratorAgent
    ↓
    ├─→ categorizer_agent (GPT) → CategorizedExpense
    ├─→ validator_agent (Gemini) → ValidationResult (with retry logic)
    └─→ persistence_agent (OpenAI) → Google Sheets via MCP tools
```

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| FastAPI Entry | `src/main.py` | HTTP endpoints, lifespan management |
| Orchestrator | `src/expense_agents/orchestrator.py` | Multi-agent coordination, workflow logic |
| Function Tools | `src/expense_agents/tools.py` | `@function_tool` decorated MCP wrappers |
| MCP Client | `src/services/mcp_client.py` | Persistent SSE connection to C# MCP server |
| LLM Manager | `src/core/llm_manager.py` | Multi-provider model factory (singleton) |
| Prompts | `src/expense_agents/prompts.py` | System prompts (Spanish) |
| Business Rules | `src/expense_agents/business_rules.txt` | Categorization rules |

### Agent Pattern (OpenAI Agents SDK)

Agents are created with `Agent()` and converted to tools via `.as_tool()`:

```python
categorizer = Agent(name="categorizer", model=model, instructions=prompt, output_type=CategorizedExpense)
categorizer_tool = categorizer.as_tool(tool_name="categorize_expense", ...)
orchestrator = Agent(tools=[categorizer_tool, validator_tool, persistence_tool])
result = await Runner.run(orchestrator, message)
```

### Configuration

- **Provider Registry**: `src/core/configs.py` defines 6 LLM providers (openai, gemini, deepseek, groq, etc.)
- **Nested Settings**: `MCPSettings`, `OrchestratorSettings` loaded from environment with `MCP__` and `ORCHESTRATOR__` prefixes
- **Environment Template**: `.env.example` has all required variables

### MCP Integration

The `MCPClientManager` maintains a persistent SSE connection with auto-reconnection. Tools are discovered at startup and cached. Key MCP tools:
- `get_ranges()` - Read from Google Sheets
- `write_range()` - Write to Google Sheets
- `get_next_row()` - Calculate next available row (prevents overwrites)

## Code Style Notes

- Spanish language used in prompts, business rules, and expense field names
- Type hints throughout (Python 3.11+ syntax)
- Pydantic v2 models for all data structures
- Loguru for structured logging
