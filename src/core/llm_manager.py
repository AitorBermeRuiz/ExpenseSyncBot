"""LLM client management following the registry pattern.

This module provides a centralized way to create and manage OpenAI-compatible
clients for different LLM providers.
"""

import os

from loguru import logger
from openai import AsyncOpenAI

from src.core.configs import AVAILABLE_LLMS, LLMConfig, LLMProvider


class LLMManager:
    """Manages OpenAI-compatible client instances for different LLM providers.

    Uses the registry pattern from configs.py to dynamically create clients
    for any configured provider.
    """

    def __init__(self) -> None:
        self._clients: dict[str, AsyncOpenAI] = {}

    def get_client(self, provider: LLMProvider) -> AsyncOpenAI | None:
        """Get or create an AsyncOpenAI client for the specified provider.

        Args:
            provider: The LLM provider key from AVAILABLE_LLMS

        Returns:
            AsyncOpenAI client configured for the provider, or None if API key missing
        """
        if provider in self._clients:
            return self._clients[provider]

        config = AVAILABLE_LLMS.get(provider)
        if not config:
            logger.error(f"Unknown LLM provider: {provider}")
            return None

        api_key = os.getenv(config.api_key_env_var)
        if not api_key:
            logger.warning(
                f"API key not found for provider '{provider}' "
                f"(env var: {config.api_key_env_var})"
            )
            return None

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.base_url,
        )
        self._clients[provider] = client
        logger.info(f"Created LLM client for provider: {provider}")

        return client

    def get_model_name(self, provider: LLMProvider) -> str | None:
        """Get the model name for a provider.

        Args:
            provider: The LLM provider key

        Returns:
            Model name string or None if provider not found
        """
        config = AVAILABLE_LLMS.get(provider)
        return config.model_name if config else None

    def get_config(self, provider: LLMProvider) -> LLMConfig | None:
        """Get the full configuration for a provider.

        Args:
            provider: The LLM provider key

        Returns:
            LLMConfig instance or None if provider not found
        """
        return AVAILABLE_LLMS.get(provider)

    @property
    def available_providers(self) -> list[str]:
        """List all available provider keys."""
        return list(AVAILABLE_LLMS.keys())

    def is_provider_configured(self, provider: LLMProvider) -> bool:
        """Check if a provider has its API key configured.

        Args:
            provider: The LLM provider key

        Returns:
            True if the provider's API key is set in environment
        """
        config = AVAILABLE_LLMS.get(provider)
        if not config:
            return False
        return bool(os.getenv(config.api_key_env_var))


# Global singleton instance
llm_manager = LLMManager()
