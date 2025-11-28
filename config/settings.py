"""Configuration management for ExpenseSyncBot."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class GoCardlessConfig:
    """GoCardless API configuration."""
    secret_id: str
    secret_key: str
    account_id: str


@dataclass
class OpenAIConfig:
    """OpenAI API configuration."""
    api_key: str
    model: str = "gpt-4o-mini"
    categorization_model: Optional[str] = None  # Si es diferente al principal


@dataclass
class MCPServerConfig:
    """MCP Server configuration."""
    project_path: str
    url: str = "http://localhost:5000/sse"
    startup_timeout: int = 10
    configuration: str = "Release"


@dataclass
class ValidationConfig:
    """Validation configuration."""
    enable_llm_verification: bool = False
    custom_rules_file: Optional[str] = None


@dataclass
class AppConfig:
    """Main application configuration."""
    gocardless: GoCardlessConfig
    openai: OpenAIConfig
    mcp_server: MCPServerConfig
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    days_to_fetch: int = 7
    log_level: str = "INFO"
    
    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> "AppConfig":
        """
        Load configuration from environment variables.
        
        Args:
            env_path: Optional path to .env file
        
        Returns:
            AppConfig instance
        
        Raises:
            ValueError: If required environment variables are missing
        """
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()
        
        # Validar variables requeridas
        required = [
            "GOCARDLESS_SECRET_ID",
            "GOCARDLESS_SECRET_KEY",
            "BANK_ACCOUNT_ID",
            "OPENAI_API_KEY",
            "MCP_SERVER_PROJECT_PATH"
        ]
        
        missing = [var for var in required if not os.getenv(var)]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
        
        return cls(
            gocardless=GoCardlessConfig(
                secret_id=os.getenv("GOCARDLESS_SECRET_ID", ""),
                secret_key=os.getenv("GOCARDLESS_SECRET_KEY", ""),
                account_id=os.getenv("BANK_ACCOUNT_ID", "")
            ),
            openai=OpenAIConfig(
                api_key=os.getenv("OPENAI_API_KEY", ""),
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                categorization_model=os.getenv("OPENAI_CATEGORIZATION_MODEL")
            ),
            mcp_server=MCPServerConfig(
                project_path=os.getenv("MCP_SERVER_PROJECT_PATH", ""),
                url=os.getenv("MCP_SERVER_URL", "http://localhost:5000/sse"),
                startup_timeout=int(os.getenv("MCP_SERVER_STARTUP_TIMEOUT", "10")),
                configuration=os.getenv("MCP_SERVER_CONFIGURATION", "Release")
            ),
            validation=ValidationConfig(
                enable_llm_verification=os.getenv("ENABLE_LLM_VERIFICATION", "").lower() == "true",
                custom_rules_file=os.getenv("CUSTOM_RULES_FILE")
            ),
            days_to_fetch=int(os.getenv("DAYS_TO_FETCH", "7")),
            log_level=os.getenv("LOG_LEVEL", "INFO")
        )
