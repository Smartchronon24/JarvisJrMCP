"""
JarvisMCP runtime integration.

Provides framework-neutral MCP configuration generation for exposing the
canonical Tool Registry through the JarvisMCP gateway to agent runtimes.

Architecture:
    Tool Registry
        ↓
    JarvisMCP gateway (stdio MCP server)
        ↓
    HTTP transport
        ↓
    Agent runtime (Claude, Codex, Copilot, etc.)

This module is responsible for:
1. Creating gateway sessions (with bearer tokens)
2. Generating MCP configuration files for the gateway
3. Managing configuration cleanup on session close
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.gateway import JarvisToolGateway
    from app.tools.transport import GatewayTransport

logger = logging.getLogger("jarvis.runtime.jarvis_mcp")


class JarvisMCPConfig:
    """
    Framework-neutral JarvisMCP configuration generator.
    
    Generates temporary MCP configuration files that expose the canonical
    Tool Registry through the JarvisMCP gateway to any agent framework.
    
    The configuration uses stdio transport with HTTP gateway dispatch.
    """
    
    def __init__(self, gateway_transport: GatewayTransport, gateway: JarvisToolGateway):
        """
        Initialize JarvisMCP config generator.
        
        Args:
            gateway_transport: GatewayTransport instance for session management
            gateway: JarvisToolGateway instance (tool registry + executor)
        """
        self.gateway_transport = gateway_transport
        self.gateway = gateway
    
    def create_config(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Create a temporary MCP configuration for the JarvisMCP gateway.
        
        Returns:
            (token, config_file_path) where:
            - token: bearer token for gateway authentication
            - config_file_path: path to temporary MCP config JSON file
            
        Returns (None, None) if gateway is unavailable.
        """
        try:
            # Create gateway session with bearer token
            session = self.gateway_transport.create_session(self.gateway)
            token = str(session["token"])
            
            # Path to the MCP gateway stdio adapter
            bridge = Path(__file__).resolve().parents[1] / "tools" / "mcp_compat_stdio.py"
            
            # Generate MCP configuration
            config = {
                "mcpServers": {
                    "jarvis": {
                        "command": sys.executable,
                        "args": [str(bridge)],
                        "env": {
                            "JARVIS_GATEWAY_URL": "http://127.0.0.1:8000/api/jarvis/gateway",
                            "JARVIS_GATEWAY_TOKEN": token,
                        },
                    }
                }
            }
            
            # Write to temporary file
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix="jarvis-mcp-",
                delete=False,
            )
            try:
                json.dump(config, handle, ensure_ascii=True)
            finally:
                handle.close()
            
            logger.info("JarvisMCP configuration created: %s (token=%s)", handle.name, token[:8])
            return token, handle.name
            
        except Exception as exc:
            logger.error("Failed to create JarvisMCP configuration: %s", exc)
            return None, None
    
    @staticmethod
    def cleanup_config(token: Optional[str], config_path: Optional[str], gateway_transport: GatewayTransport) -> None:
        """
        Clean up a JarvisMCP configuration session.
        
        Args:
            token: bearer token to revoke
            config_path: temporary config file path to delete
            gateway_transport: transport for revoking session
        """
        if token:
            try:
                gateway_transport.revoke_session(token)
                logger.debug("Revoked JarvisMCP session token")
            except Exception as exc:
                logger.warning("Failed to revoke JarvisMCP session token: %s", exc)
        
        if config_path:
            try:
                Path(config_path).unlink(missing_ok=True)
                logger.debug("Deleted JarvisMCP config file: %s", config_path)
            except OSError as exc:
                logger.warning("Failed to delete JarvisMCP config file: %s", exc)
