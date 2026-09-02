"""
Tests for JarvisMCPConfig — the framework-neutral JarvisMCP integration abstraction.

C1.1 validation for:
- Config creation and MCP server representation
- Bearer token generation and session management
- Temporary MCP configuration file generation
- Proper cleanup of sessions and temp files
"""

import json
import tempfile
from pathlib import Path
from unittest import mock
import pytest

from app.runtime.jarvis_mcp import JarvisMCPConfig


class TestJarvisMCPConfigCreation:
    """Verify JarvisMCPConfig creates valid MCP configurations."""
    
    def test_create_config_returns_token_and_path(self):
        """Config creation should return a bearer token and temp config file path."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "test-token-12345"}
        mock_transport.create_session.return_value = mock_session
        
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        token, config_path = mcp_config.create_config()
        
        assert token == "test-token-12345"
        assert config_path is not None
        assert config_path.endswith(".json")
        
        # Cleanup
        if Path(config_path).exists():
            Path(config_path).unlink()
    
    def test_config_file_contains_jarvis_mcp_server(self):
        """The generated config file should define a 'jarvis' MCP server."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "test-token"}
        mock_transport.create_session.return_value = mock_session
        
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        token, config_path = mcp_config.create_config()
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        assert "mcpServers" in config_data
        assert "jarvis" in config_data["mcpServers"]
        
        jarvis_server = config_data["mcpServers"]["jarvis"]
        assert "command" in jarvis_server
        assert "args" in jarvis_server
        assert "env" in jarvis_server
        
        # Cleanup
        Path(config_path).unlink()
    
    def test_config_includes_gateway_credentials(self):
        """The generated config should include gateway URL and bearer token."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "secret-token-xyz"}
        mock_transport.create_session.return_value = mock_session
        
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        token, config_path = mcp_config.create_config()
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        env = config_data["mcpServers"]["jarvis"]["env"]
        assert env["JARVIS_GATEWAY_URL"] == "http://127.0.0.1:8000/api/jarvis/gateway"
        assert env["JARVIS_GATEWAY_TOKEN"] == "secret-token-xyz"
        
        # Cleanup
        Path(config_path).unlink()
    
    def test_gateway_transport_session_created(self):
        """Config creation should invoke gateway_transport.create_session()."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "token-123"}
        mock_transport.create_session.return_value = mock_session
        
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        mcp_config.create_config()
        
        mock_transport.create_session.assert_called_once_with(mock_gateway)
        
        # Cleanup temp file
        token, config_path = mcp_config.create_config()
        if config_path and Path(config_path).exists():
            Path(config_path).unlink()
    
    def test_config_path_is_valid_file(self):
        """The returned config path should point to an actual readable file."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "token"}
        mock_transport.create_session.return_value = mock_session
        
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        token, config_path = mcp_config.create_config()
        
        path_obj = Path(config_path)
        assert path_obj.exists()
        assert path_obj.is_file()
        assert path_obj.stat().st_size > 0
        
        # Cleanup
        path_obj.unlink()


class TestJarvisMCPConfigCleanup:
    """Verify JarvisMCPConfig properly cleans up sessions and temp files."""
    
    def test_cleanup_revokes_gateway_session(self):
        """Cleanup should call gateway_transport.revoke_session() with the token."""
        mock_transport = mock.MagicMock()
        mock_transport.revoke_session.return_value = None
        
        JarvisMCPConfig.cleanup_config("test-token", "/tmp/dummy.json", mock_transport)
        
        mock_transport.revoke_session.assert_called_once_with("test-token")
    
    def test_cleanup_removes_config_file(self):
        """Cleanup should delete the temporary MCP config file."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{}')
            temp_path = f.name
        
        assert Path(temp_path).exists()
        
        mock_transport = mock.MagicMock()
        JarvisMCPConfig.cleanup_config("token", temp_path, mock_transport)
        
        # File should be removed
        assert not Path(temp_path).exists()
    
    def test_cleanup_handles_missing_file(self):
        """Cleanup should not raise if the config file doesn't exist."""
        mock_transport = mock.MagicMock()
        
        # Should not raise an exception
        JarvisMCPConfig.cleanup_config("token", "/nonexistent/path/file.json", mock_transport)
        
        mock_transport.revoke_session.assert_called_once()
    
    def test_cleanup_handles_revoke_failure(self):
        """Cleanup should handle errors from gateway_transport.revoke_session()."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{}')
            temp_path = f.name
        
        try:
            mock_transport = mock.MagicMock()
            mock_transport.revoke_session.side_effect = Exception("Network error")
            
            # Should not raise; cleanup should be resilient
            JarvisMCPConfig.cleanup_config("token", temp_path, mock_transport)
            
            # File should still be cleaned up
            assert not Path(temp_path).exists()
        finally:
            # Ensure cleanup if test fails
            Path(temp_path).unlink(missing_ok=True)
    
    def test_cleanup_with_none_token(self):
        """Cleanup should handle None token gracefully."""
        mock_transport = mock.MagicMock()
        
        # Should not raise or call revoke_session
        JarvisMCPConfig.cleanup_config(None, "/tmp/dummy.json", mock_transport)
        
        # revoke_session should not be called if token is None
        mock_transport.revoke_session.assert_not_called()


class TestJarvisMCPServerRepresentation:
    """Verify the MCP server definition is correct for stdio-based gateway."""
    
    def test_server_command_is_python_interpreter(self):
        """The MCP server command should be the Python interpreter."""
        import sys
        
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "token"}
        mock_transport.create_session.return_value = mock_session
        
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        token, config_path = mcp_config.create_config()
        
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        
        command = config_data["mcpServers"]["jarvis"]["command"]
        assert command == sys.executable
        
        # Cleanup
        Path(config_path).unlink()
    
    def test_server_args_point_to_gateway_script(self):
        """The MCP server args should point to mcp_gateway_stdio.py."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "token"}
        mock_transport.create_session.return_value = mock_session
        
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        token, config_path = mcp_config.create_config()
        
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        
        args = config_data["mcpServers"]["jarvis"]["args"]
        assert len(args) == 1
        assert "mcp_gateway_stdio.py" in args[0]
        assert Path(args[0]).exists()
        
        # Cleanup
        Path(config_path).unlink()


class TestJarvisMCPConfigIntegration:
    """Integration tests for JarvisMCPConfig with runtime flow."""
    
    def test_config_creation_and_cleanup_cycle(self):
        """Full cycle: create config, read it, clean it up."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_session = {"token": "integration-test-token"}
        mock_transport.create_session.return_value = mock_session
        
        # Create config
        mcp_config = JarvisMCPConfig(mock_transport, mock_gateway)
        token, config_path = mcp_config.create_config()
        assert token == "integration-test-token"
        assert Path(config_path).exists()
        
        # Read and verify
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        assert config_data["mcpServers"]["jarvis"]["env"]["JARVIS_GATEWAY_TOKEN"] == token
        
        # Cleanup
        JarvisMCPConfig.cleanup_config(token, config_path, mock_transport)
        assert not Path(config_path).exists()
        mock_transport.revoke_session.assert_called_once_with(token)
    
    def test_multiple_configs_have_different_tokens(self):
        """Each config creation should produce a unique bearer token."""
        mock_transport = mock.MagicMock()
        mock_gateway = mock.MagicMock()
        mock_transport.create_session.side_effect = [
            {"token": "token-A"},
            {"token": "token-B"},
        ]
        
        mcp_config1 = JarvisMCPConfig(mock_transport, mock_gateway)
        token1, path1 = mcp_config1.create_config()
        
        mcp_config2 = JarvisMCPConfig(mock_transport, mock_gateway)
        token2, path2 = mcp_config2.create_config()
        
        assert token1 != token2
        assert path1 != path2
        
        # Cleanup
        Path(path1).unlink()
        Path(path2).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
