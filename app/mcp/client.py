import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
MEMORY_FILE = BASE_DIR / "data" / "MemoryMCP" / "memory.jsonl"

async def main():
    # Define the server parameters. Here we use npx to run the memory server.
    server_params = StdioServerParameters(
        command="npx.cmd",
        args=["-y", "@modelcontextprotocol/server-memory"],
        env={
            **os.environ,
            "MEMORY_FILE_PATH": str(MEMORY_FILE)
        }
    )

    
    print("Connecting to Memory MCP server...")
    # Connect using stdio
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to Memory MCP server")
            
            # List available tools
            print("\nAvailable Tools:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")
            
            # Test tool: create entities
            print("\nTesting Memory MCP Server:")
            print("Storing a test value...")
            await session.call_tool("create_entities", {
                "entities": [
                    {
                        "name": "Jarvis Test",
                        "entityType": "TestObject",
                        "observations": ["This is a test to verify MCP connection works."]
                    }
                ]
            })
            print("Value stored successfully!")
            
            print("Retrieving the test value...")
            result = await session.call_tool("read_graph", {
                "entities": [
                    {
                        "name": "Jarvis Test"
                    }
                ]
            })
            print(f"Retrieved Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
