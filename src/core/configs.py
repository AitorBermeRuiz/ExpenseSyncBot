"""Configuration management for ExpenseSyncBot.

This module provides:
- LLM provider registry with dynamic configuration
- Application settings via Pydantic Settings
- MCP server configuration
- Integration with OpenAI Agents SDK
"""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# --- LLM Configuration ---
class LLMConfig(BaseModel):
    """Configuration for a single LLM provider."""

    model_name: str
    base_url: str
    api_key_env_var: str


# Static registry of available LLM providers.
# Add new providers here without modifying other code.
AVAILABLE_LLMS: dict[str, LLMConfig] = {
    "openai": LLMConfig(
        model_name="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key_env_var="OPENAI_API_KEY",
    ),
    "openai-gpt4": LLMConfig(
        model_name="gpt-4o",
        base_url="https://api.openai.com/v1",
        api_key_env_var="OPENAI_API_KEY",
    ),
    "gemini": LLMConfig(
        model_name="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env_var="GOOGLE_API_KEY",
    ),
    "deepseek": LLMConfig(
        model_name="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key_env_var="DEEPSEEK_API_KEY",
    ),
    "groq": LLMConfig(
        model_name="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
        api_key_env_var="GROQ_API_KEY",
    ),
    "groq-fast": LLMConfig(
        model_name="llama-3.1-8b-instant",
        base_url="https://api.groq.com/openai/v1",
        api_key_env_var="GROQ_API_KEY",
    ),
}

# Dynamic Literal type from registry keys for type safety
LLMProvider = Literal["openai", "openai-gpt4", "gemini", "deepseek", "groq", "groq-fast"]


# --- Application Settings ---
class MCPSettings(BaseModel):
    """MCP Server connection settings."""

    server_url: str = Field(
        default="http://localhost:5000/sse",
        description="URL of the MCP server SSE endpoint",
    )
    connection_timeout: float = Field(
        default=30.0, description="Connection timeout in seconds"
    )
    retry_attempts: int = Field(default=3, description="Number of retry attempts")
    retry_delay: float = Field(
        default=1.0, description="Delay between retries in seconds"
    )


class OrchestratorSettings(BaseModel):
    """Orchestrator agent settings."""

    max_correction_attempts: int = Field(
        default=3, description="Maximum categorization retry attempts"
    )
    llm_provider: LLMProvider = Field(
        default="openai", description="LLM provider for orchestrator"
    )
    categorizer_provider: LLMProvider = Field(
        default="openai", description="LLM provider for categorization (GPT)"
    )
    validator_provider: LLMProvider = Field(
        default="gemini", description="LLM provider for validation (Gemini)"
    )


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    debug: bool = Field(default=False, description="Debug mode")

    # CORS Configuration
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins. Use ['*'] for all origins or specify domains like ['https://app.example.com']",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Log level")

    # MCP Settings
    mcp: MCPSettings = Field(default_factory=MCPSettings)

    # Orchestrator Settings
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)

    # LLM API Keys
    # These fields allow Pydantic to load API keys from the environment (.env)
    # into the `settings` object so other modules can read them without
    # parsing the .env file directly.
    openai_api_key: str | None = Field(default=None, env="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, env="GOOGLE_API_KEY")
    deepseek_api_key: str | None = Field(default=None, env="DEEPSEEK_API_KEY")
    groq_api_key: str | None = Field(default=None, env="GROQ_API_KEY")


# Global settings instance
settings = Settings()
