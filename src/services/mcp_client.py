"""MCP Client for connecting to external MCP servers via SSE.

This module provides a persistent connection manager that maintains
a long-lived SSE connection to the MCP server with automatic reconnection.
"""

import asyncio
from contextlib import AsyncExitStack
from typing import Any

from loguru import logger
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import Tool

from src.core.configs import settings


class MCPClientManager:
    """Manager for maintaining a persistent MCP client connection.

    This class manages a long-lived SSE connection to the MCP server,
    with automatic reconnection if the connection drops.P
    """

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._tools: dict[str, Tool] = {}
        self._connected: bool = False
        self._connection_lock = asyncio.Lock()
        self._exit_stack: AsyncExitStack | None = None

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected and self._session is not None

    async def startup(self) -> bool:
        """Initialize MCP client connection on application startup.

        Establishes a persistent SSE connection that will be reused
        for all tool calls.

        Returns:
            True if connection successful
        """
        logger.info("Starting MCP client manager")
        return await self._connect()

    async def _connect(self) -> bool:
        """Establish persistent connection to MCP server.

        Returns:
            True if connection successful, False otherwise
        """
        async with self._connection_lock:
            # Close existing connection if any
            if self._session or self._exit_stack:
                await self._disconnect_internal()

            try:
                server_url = settings.mcp.server_url
                logger.info(f"Establishing persistent connection to MCP server at {server_url}")

                # Use AsyncExitStack for proper context manager lifecycle
                self._exit_stack = AsyncExitStack()
                await self._exit_stack.__aenter__()

                # Enter SSE client context
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    sse_client(url=server_url, timeout=3600)
                )

                # Enter session context
                self._session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )

                # Initialize the session
                await asyncio.wait_for(
                    self._session.initialize(),
                    timeout=settings.mcp.connection_timeout,
                )
                logger.info("MCP session initialized")

                # Discover available tools
                tools_result = await self._session.list_tools()
                self._tools = {tool.name: tool for tool in tools_result.tools}

                logger.info(
                    f"Discovered {len(self._tools)} MCP tools: {list(self._tools.keys())}"
                )

                self._connected = True
                logger.success("MCP client manager started successfully with persistent connection")
                return True

            except TimeoutError:
                logger.warning("MCP server connection timed out")
                await self._disconnect_internal()
                return False

            except Exception as e:
                logger.warning(f"Failed to connect to MCP server: {e}")
                await self._disconnect_internal()
                return False

    async def _disconnect_internal(self) -> None:
        """Internal method to close the connection without acquiring lock."""
        try:
            # Close all contexts via AsyncExitStack
            if self._exit_stack:
                await self._exit_stack.aclose()

        except Exception as e:
            logger.debug(f"Error during disconnect: {e}")

        finally:
            self._session = None
            self._exit_stack = None
            self._tools = {}
            self._connected = False

    async def _ensure_connected(self) -> bool:
        """Ensure the connection is alive, reconnecting if necessary.

        Returns:
            True if connected (or successfully reconnected), False otherwise
        """
        if self.is_connected:
            return True

        logger.warning("MCP connection lost, attempting to reconnect...")

        # Try to reconnect with retries
        for attempt in range(settings.mcp.retry_attempts):
            logger.info(f"Reconnection attempt {attempt + 1}/{settings.mcp.retry_attempts}")

            if await self._connect():
                logger.success("Successfully reconnected to MCP server")
                return True

            if attempt < settings.mcp.retry_attempts - 1:
                await asyncio.sleep(settings.mcp.retry_delay * (attempt + 1))  # Exponential backoff

        logger.error("Failed to reconnect to MCP server after all attempts")
        return False

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an MCP tool using the persistent connection.

        Automatically reconnects if the connection has been lost.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result dictionary with 'success' field
        """
        # Ensure we're connected (reconnect if needed)
        if not await self._ensure_connected():
            return {
                "success": False,
                "error": "Could not establish connection to MCP server",
            }

        if not self._session:
            return {
                "success": False,
                "error": "MCP session not available",
            }

        # Check if tool exists
        if tool_name not in self._tools:
            available = list(self._tools.keys())
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not found. Available tools: {available}",
            }

        logger.info(f"Calling MCP tool: {tool_name}")
        logger.debug(f"Tool arguments: {arguments}")

        try:
            # Call the tool using the persistent session
            result = await self._session.call_tool(tool_name, arguments)

            # Process result content
            if result.content:
                for content in result.content:
                    if hasattr(content, "text"):
                        try:
                            import json

                            response_data = json.loads(content.text)
                            logger.info(f"MCP tool '{tool_name}' completed successfully")
                            return {"success": True, **response_data}

                        except json.JSONDecodeError:
                            logger.info(f"MCP tool '{tool_name}' completed (non-JSON response)")
                            return {"success": True, "result": content.text}

            logger.info(f"MCP tool '{tool_name}' completed with no content")
            return {"success": True}

        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")

            # Mark as disconnected so next call will attempt reconnection
            self._connected = False

            return {"success": False, "error": str(e)}

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Get available tools from MCP server.

        Uses cached tools from the persistent connection.

        Returns:
            List of tool schemas in OpenAI format
        """
        if not await self._ensure_connected():
            logger.warning("Cannot fetch tools: not connected to MCP server")
            return []

        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or f"MCP tool: {tool.name}",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                },
            })

        return schemas

    async def shutdown(self) -> None:
        """Cleanup on application shutdown."""
        logger.info("Shutting down MCP client manager")
        async with self._connection_lock:
            await self._disconnect_internal()
        logger.info("MCP client manager shutdown complete")


# Global singleton instance
mcp_client = MCPClientManager()
