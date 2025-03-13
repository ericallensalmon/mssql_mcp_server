import pytest
import os
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

def has_odbc_driver():
    """Check if the ODBC driver is available."""
    try:
        import pyodbc
        drivers = pyodbc.drivers()
        return any('SQL Server' in driver for driver in drivers)
    except Exception:
        return False

def has_db_config():
    """Check if database configuration is available."""
    required_vars = ['MSSQL_HOST', 'MSSQL_USER', 'MSSQL_PASSWORD', 'MSSQL_DATABASE']
    return all(var in os.environ for var in required_vars)

# Skip integration tests if ODBC driver or DB config is not available
integration_marker = pytest.mark.skipif(
    not (has_odbc_driver() and has_db_config()),
    reason="ODBC driver not found or database configuration not available"
)

@pytest.mark.asyncio
@integration_marker
async def test_sql_syntax_error():
    """Test handling of SQL syntax errors with real database."""
    result = await call_tool("execute_sql", {"query": "SELECTT * FROM sys.tables"})
    assert len(result) == 1
    assert result[0].isError is True
    assert "syntax" in result[0].text.lower()

@pytest.mark.asyncio
@integration_marker
async def test_table_not_found_error():
    """Test handling of missing table errors with real database."""
    result = await call_tool("execute_sql", {"query": "SELECT * FROM nonexistent_table"})
    assert len(result) == 1
    assert result[0].isError is True
    assert "invalid object name" in result[0].text.lower()

@pytest.mark.asyncio
@integration_marker
async def test_column_not_found_error():
    """Test handling of missing column errors with real database."""
    # First create a test table
    await call_tool("execute_sql", {"query": """
        IF OBJECT_ID('test_table', 'U') IS NOT NULL DROP TABLE test_table;
        CREATE TABLE test_table (id INT);
    """})
    
    # Test invalid column
    result = await call_tool("execute_sql", {"query": "SELECT nonexistent_column FROM test_table"})
    assert len(result) == 1
    assert result[0].isError is True
    assert "invalid column name" in result[0].text.lower()
    
    # Cleanup
    await call_tool("execute_sql", {"query": "DROP TABLE test_table"})

@pytest.mark.asyncio
@integration_marker
async def test_permission_error():
    """Test handling of permission errors with real database."""
    # Create a test login and user with minimal permissions
    setup_queries = [
        "IF EXISTS (SELECT * FROM sys.server_principals WHERE name = 'test_user') DROP LOGIN test_user",
        "CREATE LOGIN test_user WITH PASSWORD = 'TestPass123!'",
        "CREATE USER test_user FOR LOGIN test_user",
        "REVOKE ALL FROM test_user"
    ]
    
    for query in setup_queries:
        await call_tool("execute_sql", {"query": query})
    
    # Attempt operation that should fail due to permissions
    result = await call_tool("execute_sql", {"query": "CREATE TABLE test_table (id INT)"})
    assert len(result) == 1
    assert result[0].isError is True
    assert any(err in result[0].text.lower() for err in ["permission", "privilege", "access"])
    
    # Cleanup
    cleanup_queries = [
        "IF EXISTS (SELECT * FROM sys.server_principals WHERE name = 'test_user') DROP LOGIN test_user",
        "IF EXISTS (SELECT * FROM sys.database_principals WHERE name = 'test_user') DROP USER test_user"
    ]
    
    for query in cleanup_queries:
        await call_tool("execute_sql", {"query": query})

@pytest.mark.asyncio
@integration_marker
async def test_transaction_rollback():
    """Test handling of transaction rollback with real database."""
    # Setup - create test table
    await call_tool("execute_sql", {"query": """
        IF OBJECT_ID('test_rollback', 'U') IS NOT NULL DROP TABLE test_rollback;
        CREATE TABLE test_rollback (id INT PRIMARY KEY);
    """})
    
    # Test transaction that should fail and rollback
    result = await call_tool("execute_sql", {"query": """
        BEGIN TRANSACTION;
        INSERT INTO test_rollback (id) VALUES (1);
        INSERT INTO test_rollback (id) VALUES (1); -- This should fail (duplicate key)
        COMMIT;
    """})
    
    assert len(result) == 1
    assert result[0].isError is True
    assert "violation of primary key constraint" in result[0].text.lower()
    
    # Verify rollback worked (table should be empty)
    verify_result = await call_tool("execute_sql", {"query": "SELECT COUNT(*) as count FROM test_rollback"})
    assert "0" in verify_result[0].text
    
    # Cleanup
    await call_tool("execute_sql", {"query": "DROP TABLE test_rollback"})

@pytest.mark.asyncio
@integration_marker
async def test_list_tables_functionality():
    """Test list_tables functionality with real database."""
    # Create test tables
    setup_queries = [
        "IF OBJECT_ID('test_table1', 'U') IS NOT NULL DROP TABLE test_table1",
        "IF OBJECT_ID('test_table2', 'U') IS NOT NULL DROP TABLE test_table2",
        "CREATE TABLE test_table1 (id INT)",
        "CREATE TABLE test_table2 (id INT)"
    ]
    
    for query in setup_queries:
        await call_tool("execute_sql", {"query": query})
    
    # Test list_tables
    result = await call_tool("list_tables", {})
    assert len(result) == 1
    assert result[0].isError is False
    assert "test_table1" in result[0].text
    assert "test_table2" in result[0].text
    
    # Cleanup
    cleanup_queries = [
        "DROP TABLE test_table1",
        "DROP TABLE test_table2"
    ]
    
    for query in cleanup_queries:
        await call_tool("execute_sql", {"query": query})

@pytest.mark.asyncio
@integration_marker
async def test_list_resources():
    """Test listing resources (requires database connection)."""
    resources = await list_resources()
    assert isinstance(resources, list)
    # We should have at least system tables
    assert len(resources) > 0