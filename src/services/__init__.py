"""Services package for external integrations.

To avoid circular imports when importing submodules (for example
`from src.services.mcp_client import mcp_client`), do NOT import
submodules at package import time here. Import submodules directly
from their module instead. Example:

    from src.services.mcp_client import mcp_client

This file intentionally does not import `mcp_client` to prevent a
circular import during package initialization.
"""

__all__ = [
    "MCPClient",
    "mcp_client",
]
