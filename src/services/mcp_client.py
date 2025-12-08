"""MCP Client for connecting to external MCP servers via SSE.

This module provides a client that connects to an MCP server (like the C# server)
using Server-Sent Events (SSE) transport and exposes discovered tools.
"""

import asyncio
from typing import Any

from loguru import logger
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import Tool

from src.core.configs import settings


class MCPClient:
    """Client for connecting to MCP servers via SSE.

    Manages the connection lifecycle and provides access to MCP tools
    like AddExpense from external servers.
    """

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._tools: dict[str, Tool] = {}
        self._connected: bool = False
        self._server_url: str = settings.mcp.server_url

    @property
    def is_connected(self) -> bool:
        """Check if connected to MCP server."""
        return self._connected and self._session is not None

    @property
    def available_tools(self) -> list[str]:
        """List available tool names from MCP server."""
        return list(self._tools.keys())

    def get_tool_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Get the OpenAI-compatible tool schema for an MCP tool.

        Args:
            tool_name: Name of the MCP tool

        Returns:
            Tool schema in OpenAI function calling format, or None if not found
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return None

        # Convert MCP tool to OpenAI function schema
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or f"MCP tool: {tool.name}",
                "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
            },
        }

    def get_all_tool_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI-compatible schemas for all available MCP tools.

        Returns:
            List of tool schemas in OpenAI function calling format
        """
        return [
            schema
            for tool_name in self._tools
            if (schema := self.get_tool_schema(tool_name)) is not None
        ]

    async def connect(self) -> bool:
        """Connect to the MCP server and discover available tools.

        Returns:
            True if connection successful, False otherwise
        """
        logger.info(f"Connecting to MCP server at {self._server_url}")

        for attempt in range(settings.mcp.retry_attempts):
            try:
                # Create SSE client context
                async with sse_client(self._server_url) as (read_stream, write_stream):
                    # Create and initialize session
                    async with ClientSession(read_stream, write_stream) as session:
                        self._session = session

                        # Initialize the connection
                        await session.initialize()
                        logger.info("MCP session initialized")

                        # Discover available tools
                        tools_result = await session.list_tools()
                        self._tools = {tool.name: tool for tool in tools_result.tools}

                        logger.info(
                            f"Discovered {len(self._tools)} MCP tools: {list(self._tools.keys())}"
                        )

                        self._connected = True
                        return True

            except Exception as e:
                logger.warning(
                    f"MCP connection attempt {attempt + 1}/{settings.mcp.retry_attempts} "
                    f"failed: {e}"
                )
                if attempt < settings.mcp.retry_attempts - 1:
                    await asyncio.sleep(settings.mcp.retry_delay)

        logger.error(
            f"Failed to connect to MCP server after {settings.mcp.retry_attempts} attempts"
        )
        self._connected = False
        return False

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an MCP tool with the given arguments.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments as a dictionary

        Returns:
            Tool result as a dictionary

        Raises:
            RuntimeError: If not connected or tool not found
        """
        if not self.is_connected or self._session is None:
            raise RuntimeError("Not connected to MCP server")

        if tool_name not in self._tools:
            raise RuntimeError(f"Tool '{tool_name}' not found. Available: {self.available_tools}")

        logger.info(f"Calling MCP tool: {tool_name}")
        logger.debug(f"Tool arguments: {arguments}")

        try:
            result = await self._session.call_tool(tool_name, arguments)

            # Process result content
            if result.content:
                # MCP returns content as a list of content blocks
                # Extract text content
                response_data = {}
                for content in result.content:
                    if hasattr(content, "text"):
                        # Try to parse as JSON
                        try:
                            import json

                            response_data = json.loads(content.text)
                        except json.JSONDecodeError:
                            response_data = {"result": content.text}
                        break

                logger.info(f"MCP tool '{tool_name}' completed successfully")
                return {"success": True, **response_data}

            return {"success": True, "result": None}

        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return {"success": False, "error": str(e)}

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._session:
            logger.info("Disconnecting from MCP server")
            # Session cleanup is handled by context manager
            self._session = None
            self._tools = {}
            self._connected = False


class MCPClientManager:
    """Manager for maintaining a persistent MCP client connection.

    This class is designed to be used with FastAPI's lifespan for
    connection management across the application lifecycle.
    """

    def __init__(self) -> None:
        self._client: MCPClient | None = None
        self._read_stream: Any = None
        self._write_stream: Any = None
        self._session: ClientSession | None = None

    @property
    def client(self) -> MCPClient | None:
        """Get the managed MCP client."""
        return self._client

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._client is not None and self._client.is_connected

    async def startup(self) -> bool:
        """Initialize MCP client connection on application startup.

        Returns:
            True if connection successful
        """
        logger.info("Starting MCP client manager")

        try:
            server_url = settings.mcp.server_url

            # Create SSE connection
            # Note: We need to maintain the connection outside of async with
            # for persistent connections in FastAPI lifespan
            self._client = MCPClient()

            # For demonstration, we'll try a simple connect
            # In production, you'd want more sophisticated connection management
            connected = await self._try_connect()

            if connected:
                logger.info("MCP client manager started successfully")
            else:
                logger.warning(
                    "MCP client manager started but server not available. "
                    "External tools will be unavailable."
                )

            return connected

        except Exception as e:
            logger.error(f"Failed to start MCP client manager: {e}")
            return False

    async def _try_connect(self) -> bool:
        """Attempt to connect to MCP server by actually establishing an SSE connection.

        This validates the server is reachable and speaks MCP protocol,
        rather than assuming a /health endpoint exists.
        """
        try:
            # Actually try to connect via SSE and initialize MCP session
            # This is the most reliable way to check if the server is available
            async with sse_client(settings.mcp.server_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    # If we can initialize, the server is working
                    await asyncio.wait_for(
                        session.initialize(),
                        timeout=settings.mcp.connection_timeout,
                    )
                    logger.info("MCP server connection verified via SSE handshake")
                    return True

        except asyncio.TimeoutError:
            logger.warning("MCP server connection timed out")
            return False
        except Exception as e:
            # Server not available, but we can still start the app
            logger.debug(f"MCP server not reachable: {e}")
            return False

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an MCP tool, establishing connection if needed.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result dictionary
        """
        logger.info(f"Calling MCP tool via manager: {tool_name}")

        try:
            # Establish connection for this call
            async with sse_client(settings.mcp.server_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Call the tool
                    result = await session.call_tool(tool_name, arguments)

                    # Process result
                    if result.content:
                        for content in result.content:
                            if hasattr(content, "text"):
                                try:
                                    import json

                                    return {"success": True, **json.loads(content.text)}
                                except json.JSONDecodeError:
                                    return {"success": True, "result": content.text}

                    return {"success": True}

        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return {"success": False, "error": str(e)}

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Get available tools from MCP server.

        Returns:
            List of tool schemas in OpenAI format
        """
        try:
            async with sse_client(settings.mcp.server_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()

                    schemas = []
                    for tool in tools_result.tools:
                        schemas.append({
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description or f"MCP tool: {tool.name}",
                                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                            },
                        })

                    return schemas

        except Exception as e:
            logger.warning(f"Could not fetch MCP tools: {e}")
            return []

    async def shutdown(self) -> None:
        """Cleanup on application shutdown."""
        logger.info("Shutting down MCP client manager")
        if self._client:
            await self._client.disconnect()
        self._client = None


# Global singleton instance
mcp_client = MCPClientManager()
