import pytest
from mssql_mcp_server.server import app, list_tools, list_resources, read_resource, call_tool
from pydantic import AnyUrl

def test_server_initialization():
    """Test that the server initializes correctly."""
    assert app.name == "mssql_mcp_server"

@pytest.mark.asyncio
async def test_list_tools():
    """Test that list_tools returns expected tools."""
    tools = await list_tools()
    # Verify execute_sql tool
    execute_sql = next((t for t in tools if t.name == "execute_sql"), None)
    assert execute_sql is not None
    assert execute_sql.description == "Execute an SQL query on the MSSQL server"
    assert "query" in execute_sql.inputSchema["properties"]
    assert execute_sql.inputSchema["required"] == ["query"]

    # Verify list_tables tool
    list_tables = next((t for t in tools if t.name == "list_tables"), None)
    assert list_tables is not None
    assert list_tables.description == "List all tables in the current database"
    assert list_tables.inputSchema["properties"] == {}

@pytest.mark.asyncio
async def test_call_tool_invalid_name():
    """Test calling a tool with an invalid name."""
    result = await call_tool("invalid_tool", {})
    assert len(result) == 1
    assert result[0].isError is True
    assert "Unknown tool" in result[0].text

@pytest.mark.asyncio
async def test_call_tool_missing_query():
    """Test calling execute_sql without a query."""
    result = await call_tool("execute_sql", {})
    assert len(result) == 1
    assert result[0].isError is True
    assert "Query is required" in result[0].text

# Skip database-dependent tests if no database connection
@pytest.mark.asyncio
@pytest.mark.skipif(
    not all([
        pytest.importorskip("pyodbc"),
        pytest.importorskip("mssql_mcp_server")
    ]),
    reason="MSSQL connection not available"
)
async def test_list_resources():
    """Test listing resources (requires database connection)."""
    try:
        resources = await list_resources()
        assert isinstance(resources, list)
    except ValueError as e:
        if "Missing required database configuration" in str(e):
            pytest.skip("Database configuration not available")
        raise